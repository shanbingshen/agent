"""RAG 应用服务，保留现有向量与租户过滤实现。"""

import uuid

from arthra.contracts import Citation
from sqlalchemy.orm import Session

from arthra_rag.embeddings import embed_documents
from arthra_rag.retriever import retrieve
from arthra_rag.schemas import KnowledgeFilters, RetrievalRequest
from arthra_rag.splitter import split_text


def ingest_text(content: str) -> tuple[list[str], list[list[float]]]:
    chunks = split_text(content)
    return chunks, embed_documents(chunks)


def retrieve_citations(
    db: Session,
    query: str,
    *,
    tenant_id: uuid.UUID,
    factory_id: uuid.UUID,
    limit: int,
    min_score: float,
) -> list[Citation]:
    return retrieve(
        db,
        RetrievalRequest(
            query=query,
            filters=KnowledgeFilters(
                tenant_id=tenant_id,
                factory_id=factory_id,
            ),
            limit=limit,
            min_score=min_score,
        ),
    )
