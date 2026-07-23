"""Vector store adapters.

The current compatibility adapter uses the existing PostgreSQL + pgvector
tables. Qdrant can be introduced behind this package without changing agents.
"""

from arthra_rag.vectorstore.legacy_pgvector import search_pgvector

__all__ = ["search_pgvector"]
