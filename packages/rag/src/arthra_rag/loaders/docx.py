"""DOCX loader placeholder.

Milestone 1 keeps existing upload-time text ingestion. A production DOCX parser
should return normalized UTF-8 text and document metadata here.
"""

from pathlib import Path


def load_docx_text(path: Path) -> str:
    raise NotImplementedError(f"DOCX ingestion is not enabled yet: {path}")
