"""主 Agent 的运行时装配。Gateway 不应了解图或 Checkpointer 细节。"""

from dataclasses import dataclass
from typing import Any

from arthra.config import Settings, get_settings
from langgraph.checkpoint.postgres import PostgresSaver
from main_agent.graph import agent_checkpoint_serializer, build_graph


@dataclass
class AgentRuntime:
    graph: Any
    _checkpoint_context: Any | None = None

    def close(self) -> None:
        if self._checkpoint_context is not None:
            self._checkpoint_context.__exit__(None, None, None)
            self._checkpoint_context = None


def create_agent_runtime(settings: Settings | None = None) -> AgentRuntime:
    settings = settings or get_settings()
    checkpoint_context = None
    checkpointer = None
    if settings.langgraph_database_url:
        checkpoint_context = PostgresSaver.from_conn_string(settings.langgraph_database_url)
        checkpointer = checkpoint_context.__enter__()
        checkpointer.serde = agent_checkpoint_serializer()
        checkpointer.setup()
    return AgentRuntime(graph=build_graph(checkpointer), _checkpoint_context=checkpoint_context)
