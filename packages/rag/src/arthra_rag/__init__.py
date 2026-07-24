from arthra_rag.schemas import KnowledgeFilters, RetrievalRequest, RetrievalResponse

__all__ = [
    "KnowledgeFilters",
    "RetrievalRequest",
    "RetrievalResponse",
    "ingest_text",
    "retrieve",
    "retrieve_citations",
]


def __getattr__(name: str):
    if name == "retrieve":
        from arthra_rag.retriever import retrieve

        return retrieve
    if name in {"ingest_text", "retrieve_citations"}:
        from arthra_rag import service

        return getattr(service, name)
    raise AttributeError(name)
