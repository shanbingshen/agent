"""空压机 Agent 插件描述，不复制确定性分析逻辑。"""

from arthra_core import AgentPlugin

from compressor_agent.tools import graph_tools


def CompressorAgent() -> AgentPlugin:
    return AgentPlugin(
        name="compressor-agent",
        domain="compressor",
        allowed_tools=[tool.name for tool in graph_tools()],
        deterministic_service="arthra.compressor.analysis.CompressorAnalysisService",
    )
