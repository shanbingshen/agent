"""电力 Agent 插件描述，不复制确定性分析逻辑。"""

from arthra_core import AgentPlugin

from power_agent.tools import graph_tools


def PowerAgent() -> AgentPlugin:
    return AgentPlugin(
        name="power-agent",
        domain="power",
        allowed_tools=[tool.name for tool in graph_tools()],
        deterministic_service="arthra.power.analysis.PowerAnalysisService",
    )
