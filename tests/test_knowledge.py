import math

from arthra.knowledge import chunk_text, local_embedding


def test_chunk_text_overlap():
    chunks = chunk_text("A" * 1000, size=400, overlap=50)
    assert len(chunks) == 3
    assert chunks[0][-50:] == chunks[1][:50]


def test_local_embedding_is_deterministic_and_normalized():
    first = local_embedding("空压机 能效")
    second = local_embedding("空压机 能效")
    assert first == second
    assert math.isclose(sum(value * value for value in first), 1.0)

