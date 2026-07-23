"""Markdown and plain-text loader.

Binary loaders are intentionally separate modules so PDF/DOCX dependencies can
be added without changing agent code.
"""

from pathlib import Path


def load_markdown_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
