"""Agent-facing retrieval service."""

from arthra.contracts import Citation
from arthra.knowledge import search_knowledge
from sqlalchemy.orm import Session

from arthra_rag.schemas import RetrievalRequest


def retrieve(db: Session, request: RetrievalRequest) -> list[Citation]:
    """Retrieve citations within the tenant/factory boundary.

    Domain filters are part of the stable contract. The current Milvus schema
    enforces tenant/factory scope and keeps future domain filtering explicit.
    """
    results = search_knowledge(
        db,
        request.query,
        limit=request.limit,
        tenant_id=request.filters.tenant_id,
        factory_id=request.filters.factory_id,
    )
    return [
        Citation(
            source_id=str(result.document_id),
            title=result.document_name,
            excerpt=result.content,
            score=result.score,
        )
        for result in results
        if result.score >= request.min_score
    ]
