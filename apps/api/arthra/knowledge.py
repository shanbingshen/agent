import hashlib
import math
import re
import uuid
from collections.abc import Iterable

import httpx
from arthra_rag.vectorstore import MilvusChunkVector, MilvusVectorStore
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.config import get_settings
from arthra.models import KnowledgeChunk, KnowledgeDocument
from arthra.schemas import KnowledgeSearchResult


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + size, len(clean))
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = end - overlap
    return chunks


def local_embedding(text: str, dimensions: int = 384) -> list[float]:
    """Deterministic, offline demo embedding. Production should configure an embedding API."""
    values = [0.0] * dimensions
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    settings = get_settings()
    batch = list(texts)
    if not settings.embedding_api_key:
        return [local_embedding(text, settings.embedding_dimensions) for text in batch]
    response = httpx.post(
        settings.embedding_base_url.rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        json={"model": settings.embedding_model, "input": batch, "dimensions": settings.embedding_dimensions},
        timeout=30,
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]


def _vector_store() -> MilvusVectorStore:
    settings = get_settings()
    return MilvusVectorStore(
        uri=settings.milvus_uri,
        token=settings.milvus_token,
        collection_name=settings.milvus_collection,
        dimensions=settings.embedding_dimensions,
    )


def upsert_knowledge_vectors(
    *,
    document: KnowledgeDocument,
    chunks: list[KnowledgeChunk],
    embeddings: list[list[float]],
) -> None:
    _vector_store().upsert_chunks(
        [
            MilvusChunkVector(
                chunk_id=str(chunk.id),
                document_id=str(document.id),
                tenant_id=str(document.tenant_id),
                factory_id=str(document.factory_id),
                position=chunk.position,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
    )


def delete_knowledge_vectors(document_id: uuid.UUID) -> None:
    _vector_store().delete_document(str(document_id))


def search_knowledge(
    db: Session,
    query: str,
    limit: int = 5,
    *,
    tenant_id: uuid.UUID | None = None,
    factory_id: uuid.UUID | None = None,
) -> list[KnowledgeSearchResult]:
    if tenant_id is None or factory_id is None:
        return []
    vector = embed_texts([query])[0]
    hits = _vector_store().search(
        query_embedding=vector,
        tenant_id=str(tenant_id),
        factory_id=str(factory_id),
        limit=limit,
    )
    if not hits:
        return []
    score_by_chunk_id = {uuid.UUID(hit.chunk_id): hit.score for hit in hits}
    statement = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeChunk.id.in_(score_by_chunk_id))
        .where(KnowledgeDocument.tenant_id == tenant_id)
        .where(KnowledgeDocument.factory_id == factory_id)
    )
    rows = db.execute(statement).all()
    by_chunk_id = {chunk.id: (chunk, document) for chunk, document in rows}
    return [
        KnowledgeSearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=document.filename,
            content=chunk.content,
            score=score_by_chunk_id[chunk_id],
        )
        for chunk_id in score_by_chunk_id
        if chunk_id in by_chunk_id
        for chunk, document in [by_chunk_id[chunk_id]]
    ]
