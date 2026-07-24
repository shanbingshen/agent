import math
import uuid

from arthra.agent import AgentState, conversation
from arthra.contracts import Citation
from arthra.knowledge import (
    chunk_text,
    delete_knowledge_vectors,
    local_embedding,
    search_knowledge,
    upsert_knowledge_vectors,
)
from arthra.models import (
    DEFAULT_FACTORY_ID,
    DEFAULT_TENANT_ID,
    Factory,
    KnowledgeChunk,
    KnowledgeDocument,
    Role,
    Tenant,
    User,
)
from arthra_rag.vectorstore import MilvusChunkVector, MilvusSearchHit, MilvusVectorStore
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_chunk_text_overlap():
    chunks = chunk_text("A" * 1000, size=400, overlap=50)
    assert len(chunks) == 3
    assert chunks[0][-50:] == chunks[1][:50]


def test_local_embedding_is_deterministic_and_normalized():
    first = local_embedding("空压机 能效")
    second = local_embedding("空压机 能效")
    assert first == second
    assert math.isclose(sum(value * value for value in first), 1.0)


def test_conversation_uses_retrieved_knowledge_for_unknown_question():
    state = AgentState(
        message="空压站的日常点检要求是什么？",
        citations=[
            Citation(
                source_id=str(uuid.uuid4()),
                title="空压站点检规程.md",
                excerpt="每日检查压力、温度、排水和异常振动，并记录处理结果。",
                score=0.92,
            )
        ],
    )

    response = conversation(state)

    assert "空压站点检规程.md" in response["response"]
    assert "每日检查压力" in response["response"]


class FakeVectorStore:
    def __init__(self):
        self.upserted: list[MilvusChunkVector] = []
        self.deleted_document_id: str | None = None
        self.hits: list[MilvusSearchHit] = []
        self.search_filter: tuple[str, str] | None = None

    def upsert_chunks(self, chunks: list[MilvusChunkVector]) -> None:
        self.upserted.extend(chunks)

    def delete_document(self, document_id: str) -> None:
        self.deleted_document_id = document_id

    def search(
        self,
        *,
        query_embedding: list[float],
        tenant_id: str,
        factory_id: str,
        limit: int,
    ) -> list[MilvusSearchHit]:
        self.search_filter = (tenant_id, factory_id)
        return self.hits[:limit]


def _knowledge_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Tenant.__table__.create(engine)
    Factory.__table__.create(engine)
    User.__table__.create(engine)
    KnowledgeDocument.__table__.create(engine)
    KnowledgeChunk.__table__.create(engine)
    session = Session(engine)
    session.add(Tenant(id=DEFAULT_TENANT_ID, slug="default", name="Default"))
    session.add(
        Factory(
            id=DEFAULT_FACTORY_ID,
            tenant_id=DEFAULT_TENANT_ID,
            code="default",
            name="Default Factory",
        )
    )
    session.add(User(email="admin@example.com", password_hash="test", role=Role.admin))
    session.commit()
    return session


def test_knowledge_vectors_are_upserted_to_milvus(monkeypatch):
    store = FakeVectorStore()
    monkeypatch.setattr("arthra.knowledge._vector_store", lambda: store)
    db = _knowledge_db()
    try:
        user = db.query(User).one()
        document = KnowledgeDocument(
            tenant_id=DEFAULT_TENANT_ID,
            factory_id=DEFAULT_FACTORY_ID,
            filename="规程.md",
            media_type="text/markdown",
            created_by=user.id,
        )
        db.add(document)
        db.flush()
        chunk = KnowledgeChunk(document_id=document.id, position=0, content="每日检查压力")
        db.add(chunk)
        db.flush()

        upsert_knowledge_vectors(document=document, chunks=[chunk], embeddings=[[0.1, 0.2]])

        assert store.upserted == [
            MilvusChunkVector(
                chunk_id=str(chunk.id),
                document_id=str(document.id),
                tenant_id=str(DEFAULT_TENANT_ID),
                factory_id=str(DEFAULT_FACTORY_ID),
                position=0,
                embedding=[0.1, 0.2],
            )
        ]
    finally:
        db.close()


def test_knowledge_document_delete_removes_milvus_vectors(monkeypatch):
    store = FakeVectorStore()
    monkeypatch.setattr("arthra.knowledge._vector_store", lambda: store)
    document_id = uuid.uuid4()

    delete_knowledge_vectors(document_id)

    assert store.deleted_document_id == str(document_id)


def test_search_knowledge_uses_milvus_scope_and_skips_missing_chunks(monkeypatch):
    store = FakeVectorStore()
    monkeypatch.setattr("arthra.knowledge._vector_store", lambda: store)
    db = _knowledge_db()
    try:
        user = db.query(User).one()
        document = KnowledgeDocument(
            tenant_id=DEFAULT_TENANT_ID,
            factory_id=DEFAULT_FACTORY_ID,
            filename="空压站点检规程.md",
            media_type="text/markdown",
            created_by=user.id,
        )
        db.add(document)
        db.flush()
        chunk = KnowledgeChunk(document_id=document.id, position=0, content="每日检查压力")
        db.add(chunk)
        db.flush()
        missing_chunk_id = uuid.uuid4()
        store.hits = [
            MilvusSearchHit(chunk_id=str(chunk.id), score=0.91),
            MilvusSearchHit(chunk_id=str(missing_chunk_id), score=0.88),
        ]

        results = search_knowledge(
            db,
            "点检",
            tenant_id=DEFAULT_TENANT_ID,
            factory_id=DEFAULT_FACTORY_ID,
        )

        assert store.search_filter == (str(DEFAULT_TENANT_ID), str(DEFAULT_FACTORY_ID))
        assert len(results) == 1
        assert results[0].chunk_id == chunk.id
        assert results[0].document_name == "空压站点检规程.md"
        assert results[0].score == 0.91
    finally:
        db.close()


def test_milvus_adapter_writes_filters_and_searches_by_scope():
    class FakeMilvusClient:
        def __init__(self):
            self.upsert_payload = None
            self.delete_filter = ""
            self.search_filter = ""

        def has_collection(self, collection_name):
            return True

        def upsert(self, *, collection_name, data):
            self.upsert_payload = (collection_name, data)

        def delete(self, *, collection_name, filter):
            self.delete_filter = filter

        def search(self, **kwargs):
            self.search_filter = kwargs["filter"]
            return [[{"distance": 0.93, "entity": {"chunk_id": "chunk-1"}}]]

    client = FakeMilvusClient()
    store = MilvusVectorStore(
        uri="http://localhost:19530",
        token="",
        collection_name="test_chunks",
        dimensions=384,
        client=client,
    )

    store.upsert_chunks(
        [
            MilvusChunkVector(
                chunk_id="chunk-1",
                document_id="doc-1",
                tenant_id="tenant-1",
                factory_id="factory-1",
                position=0,
                embedding=[0.1],
            )
        ]
    )
    store.delete_document("doc-1")
    hits = store.search(
        query_embedding=[0.1],
        tenant_id="tenant-1",
        factory_id="factory-1",
        limit=4,
    )

    assert client.upsert_payload[0] == "test_chunks"
    assert client.upsert_payload[1][0]["chunk_id"] == "chunk-1"
    assert client.delete_filter == 'document_id == "doc-1"'
    assert client.search_filter == 'tenant_id == "tenant-1" && factory_id == "factory-1"'
    assert hits == [MilvusSearchHit(chunk_id="chunk-1", score=0.93)]
