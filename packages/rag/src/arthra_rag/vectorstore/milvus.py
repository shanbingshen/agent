"""Milvus vector store adapter for Arthra knowledge chunks."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MilvusChunkVector:
    chunk_id: str
    document_id: str
    tenant_id: str
    factory_id: str
    position: int
    embedding: list[float]


@dataclass(frozen=True)
class MilvusSearchHit:
    chunk_id: str
    score: float


class MilvusVectorStore:
    def __init__(
        self,
        *,
        uri: str,
        token: str,
        collection_name: str,
        dimensions: int,
        client: Any | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.dimensions = dimensions
        if client is not None:
            self.client = client
        else:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise RuntimeError("缺少 pymilvus 依赖，无法连接 Milvus 向量库") from exc
            self.client = MilvusClient(uri=uri, token=token or None)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            if self.client.has_collection(self.collection_name):
                return
            from pymilvus import DataType

            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=36)
            schema.add_field("document_id", DataType.VARCHAR, max_length=36)
            schema.add_field("tenant_id", DataType.VARCHAR, max_length=36)
            schema.add_field("factory_id", DataType.VARCHAR, max_length=36)
            schema.add_field("position", DataType.INT64)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dimensions)
            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )
        except ImportError as exc:
            raise RuntimeError("缺少 pymilvus 依赖，无法创建 Milvus collection") from exc
        except Exception as exc:
            raise RuntimeError("Milvus collection 初始化失败") from exc

    def upsert_chunks(self, chunks: Sequence[MilvusChunkVector]) -> None:
        if not chunks:
            return
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                data=[
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "tenant_id": chunk.tenant_id,
                        "factory_id": chunk.factory_id,
                        "position": chunk.position,
                        "embedding": chunk.embedding,
                    }
                    for chunk in chunks
                ],
            )
        except Exception as exc:
            raise RuntimeError("Milvus 知识向量写入失败") from exc

    def delete_document(self, document_id: str) -> None:
        try:
            self.client.delete(
                collection_name=self.collection_name,
                filter=f'document_id == "{document_id}"',
            )
        except Exception as exc:
            raise RuntimeError("Milvus 知识向量删除失败") from exc

    def search(
        self,
        *,
        query_embedding: list[float],
        tenant_id: str,
        factory_id: str,
        limit: int,
    ) -> list[MilvusSearchHit]:
        try:
            rows = self.client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                anns_field="embedding",
                limit=limit,
                filter=f'tenant_id == "{tenant_id}" && factory_id == "{factory_id}"',
                output_fields=["chunk_id"],
                search_params={"metric_type": "COSINE"},
            )
        except Exception as exc:
            raise RuntimeError("Milvus 知识向量检索失败") from exc
        hits = rows[0] if rows else []
        result: list[MilvusSearchHit] = []
        for hit in hits:
            entity = hit.get("entity", {}) if isinstance(hit, dict) else getattr(hit, "entity", {})
            chunk_id = entity.get("chunk_id") if isinstance(entity, dict) else entity["chunk_id"]
            raw_score = hit.get("distance") if isinstance(hit, dict) else hit.distance
            result.append(MilvusSearchHit(chunk_id=str(chunk_id), score=round(float(raw_score), 4)))
        return result
