"""Compatibility vector search backed by existing knowledge tables."""

from arthra.knowledge import search_knowledge

__all__ = ["search_knowledge"]


search_pgvector = search_knowledge
