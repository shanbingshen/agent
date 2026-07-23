"""Agent-facing retrieval service."""

from arthra.contracts import Citation
from sqlalchemy.orm import Session

from arthra_rag.schemas import RetrievalRequest
from arthra_rag.vectorstore import search_pgvector


def retrieve(db: Session, request: RetrievalRequest) -> list[Citation]:
    """Retrieve citations within the tenant/factory boundary.

    Domain filters are part of the stable contract. The current storage schema
    does not yet persist source domains, so this adapter preserves existing
    behavior while keeping the future vector-store filter surface explicit.
    """
    results = search_pgvector(
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
