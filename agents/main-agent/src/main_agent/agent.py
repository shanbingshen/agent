"""主 Agent 插件。

第一阶段刻意委托既有实现，确保状态、图节点与用户可见行为不发生变化。
"""

from dataclasses import dataclass
from typing import Any

from main_agent.graph import build_graph


@dataclass(frozen=True)
class MainAgent:
    name: str = "main-agent"
    version: str = "1.0"

    def build(self, checkpointer: Any | None = None):
        return build_graph(checkpointer=checkpointer)
