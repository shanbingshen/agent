import math
import uuid

from arthra.agent import AgentState, conversation
from arthra.contracts import Citation
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


def test_conversation_uses_retrieved_knowledge_for_unknown_question():
    state = AgentState(
        message="空压站的日常点检要求是什么？",
        citations=[
            Citation(
                source_id=str(uuid.uuid4()),
                title="空压站点检规程.md",
                excerpt="每日检查压力、温度、排水和异常振动，并记录处理结果。",
                score=0.92,
            )
        ],
    )

    response = conversation(state)

    assert "空压站点检规程.md" in response["response"]
    assert "每日检查压力" in response["response"]
