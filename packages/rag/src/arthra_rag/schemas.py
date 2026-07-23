"""Stable RAG contracts shared by agents and ingestion jobs."""

import uuid
from typing import Literal

from arthra.contracts import Citation, StrictModel
from pydantic import Field

KnowledgeDomain = Literal["shared", "ems", "power", "compressor", "carbon", "customer"]


class KnowledgeFilters(StrictModel):
    tenant_id: uuid.UUID
    factory_id: uuid.UUID
    knowledge_sources: list[KnowledgeDomain] = Field(default_factory=list)
    device: str | None = None
    model: str | None = None
    customer_slug: str | None = None


class RetrievalRequest(StrictModel):
    query: str
    filters: KnowledgeFilters
    limit: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0.2, ge=-1, le=1)


class RetrievalResponse(StrictModel):
    citations: list[Citation]
