import hashlib
import math
import re
from collections.abc import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.config import get_settings
from arthra.models import KnowledgeChunk
from arthra.schemas import KnowledgeSearchResult


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + size, len(clean))
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = end - overlap
    return chunks


def local_embedding(text: str, dimensions: int = 384) -> list[float]:
    """Deterministic, offline demo embedding. Production should configure an embedding API."""
    values = [0.0] * dimensions
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    settings = get_settings()
    batch = list(texts)
    if not settings.embedding_api_key:
        return [local_embedding(text, settings.embedding_dimensions) for text in batch]
    response = httpx.post(
        settings.embedding_base_url.rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        json={"model": settings.embedding_model, "input": batch, "dimensions": settings.embedding_dimensions},
        timeout=30,
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]


def search_knowledge(db: Session, query: str, limit: int = 5) -> list[KnowledgeSearchResult]:
    vector = embed_texts([query])[0]
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    rows = db.execute(
        select(KnowledgeChunk, distance.label("distance"))
        .where(KnowledgeChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    ).all()
    return [
        KnowledgeSearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            score=round(1 - float(item_distance), 4),
        )
        for chunk, item_distance in rows
    ]
