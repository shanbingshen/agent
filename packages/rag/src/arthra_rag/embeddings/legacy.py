"""Compatibility embedding adapter backed by the current settings."""

from collections.abc import Iterable

from arthra.knowledge import embed_texts


def embed_documents(texts: Iterable[str]) -> list[list[float]]:
    return embed_texts(texts)
