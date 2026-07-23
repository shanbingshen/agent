"""PDF loader placeholder.

Milestone 1 keeps existing upload-time text ingestion. A production PDF parser
should return normalized UTF-8 text and document metadata here.
"""

from pathlib import Path


def load_pdf_text(path: Path) -> str:
    raise NotImplementedError(f"PDF ingestion is not enabled yet: {path}")
