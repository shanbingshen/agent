"""Compatibility splitter backed by the existing Arthra implementation."""

from arthra.knowledge import chunk_text


def split_text(text: str, *, size: int = 800, overlap: int = 100) -> list[str]:
    return chunk_text(text, size=size, overlap=overlap)
