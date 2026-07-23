"""RAG ingestion pipeline facade.

The first migration milestone keeps persistence in the existing API layer. This
module defines the pipeline boundary used by future batch ingestion from
`knowledge/raw` into pgvector or Qdrant.
"""

from pathlib import Path

from arthra_rag.embeddings import embed_documents
from arthra_rag.loaders import load_markdown_text
from arthra_rag.splitter import split_text


def ingest_markdown_file(path: Path) -> tuple[list[str], list[list[float]]]:
    text = load_markdown_text(path)
    chunks = split_text(text)
    return chunks, embed_documents(chunks)
