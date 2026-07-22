from datetime import datetime
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.schemas import (
    CompressorAnalysisRequest,
    CompressorAnalysisResult,
    CompressorCapability,
    CompressorSystemContext,
    FrequentStartToolInput,
    HighSupplyPressureToolInput,
    IdleRunningToolInput,
    LoadUnloadRateToolInput,
    LoadUnloadRateToolResult,
    PressureFluctuationToolInput,
    SpecificPowerToolInput,
)
from arthra.contracts import StrictModel


@tool(
    "analyze_compressor_load_unload_rate",
    args_schema=LoadUnloadRateToolInput,
)
def analyze_compressor_load_unload_rate_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> LoadUnloadRateToolResult:
    """分析指定空压机在时间窗口内的加载率、卸载率、运行时长与数据覆盖率。"""
    payload = LoadUnloadRateToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_load_unload_rate(payload)


@tool(
    "detect_compressor_idle_running",
    args_schema=IdleRunningToolInput,
)
def detect_compressor_idle_running_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """识别指定空压机的累计空载时间、最长连续空载时间和超阈值风险。"""
    payload = IdleRunningToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_capability(
        payload,
        "idle_running",
        "识别单机空载运行",
    )


@tool(
    "detect_compressor_frequent_starts",
    args_schema=FrequentStartToolInput,
)
def detect_compressor_frequent_starts_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """计算指定空压机的窗口启动次数和每小时启动频率，并识别频繁启停。"""
    payload = FrequentStartToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_capability(
        payload,
        "frequent_start",
        "识别单机频繁启停",
    )


@tool(
    "analyze_compressor_pressure_fluctuation",
    args_schema=PressureFluctuationToolInput,
)
def analyze_compressor_pressure_fluctuation_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """分析指定空压系统运行压力的 P5、P95、标准差和 P95-P5 波动。"""
    payload = PressureFluctuationToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_capability(
        payload,
        "pressure_fluctuation",
        "分析管网压力波动",
    )


@tool(
    "detect_compressor_high_supply_pressure",
    args_schema=HighSupplyPressureToolInput,
)
def detect_compressor_high_supply_pressure_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """识别指定空压系统超过供气压力上限的持续时间和风险。"""
    payload = HighSupplyPressureToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_capability(
        payload,
        "high_pressure",
        "识别供气压力过高",
    )


@tool(
    "calculate_compressor_specific_power",
    args_schema=SpecificPowerToolInput,
)
def calculate_compressor_specific_power_tool(
    device_scope: list[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """对齐空压系统流量和关联电表功率，计算系统比功率及 P95。"""
    payload = SpecificPowerToolInput(
        device_scope=device_scope,
        start_at=start_at,
        end_at=end_at,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze_capability(
        payload,
        "specific_power",
        "计算空压系统比功率",
    )


@tool("analyze_compressor_system")
def analyze_compressor_system_tool(
    message: str,
    device_scope: list[str],
    start_at: str,
    end_at: str,
    capabilities: list[str],
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """Run read-only deterministic compressed-air analysis over ThingsBoard history."""
    request = CompressorAnalysisRequest(
        message=message,
        device_scope=device_scope,
        start_at=datetime.fromisoformat(start_at),
        end_at=datetime.fromisoformat(end_at),
        capabilities=capabilities,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze(request)


COMPRESSOR_TOOLS = (
    analyze_compressor_load_unload_rate_tool,
    detect_compressor_idle_running_tool,
    detect_compressor_frequent_starts_tool,
    analyze_compressor_pressure_fluctuation_tool,
    detect_compressor_high_supply_pressure_tool,
    calculate_compressor_specific_power_tool,
    analyze_compressor_system_tool,
)


ADDITIONAL_CAPABILITY_TOOLS: dict[str, tuple[CompressorCapability, str, str]] = {
    "get_compressor_realtime": (
        "realtime_status",
        "查询空压机当前运行状态",
        "只读取空压机当前运行、加载、压力、温度、关联功率和告警状态。",
    ),
    "get_compressor_energy": (
        "energy_consumption",
        "计算空压系统周期用电量",
        "根据空压系统关联电表累计电量的期末值减期初值计算用电量。",
    ),
    "analyze_compressor_group_control": (
        "group_control",
        "生成多机群控优化建议",
        "根据同一空压系统内各机组负载率生成群控筛查建议。",
    ),
    "detect_compressor_leakage": (
        "leakage",
        "识别非生产时段泄漏迹象",
        "根据生产日历和非生产时段供气流量识别持续用气或泄漏迹象。",
    ),
    "estimate_compressor_energy_saving": (
        "savings",
        "估算空压系统可优化电量",
        "根据卸载状态与关联功率的对齐历史估算可优化电量。",
    ),
    "verify_compressor_optimization": (
        "verification",
        "验证空压系统优化前后效果",
        "检查是否具备基线、措施生效时间和独立验证周期。",
    ),
}


def _direct_additional_tool(
    name: str,
    capability: CompressorCapability,
    message: str,
    description: str,
) -> BaseTool:
    @tool(name, args_schema=LoadUnloadRateToolInput, description=description)
    def invoke(
        device_scope: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        interval_seconds: int = 180,
    ) -> CompressorAnalysisResult:
        payload = LoadUnloadRateToolInput(
            device_scope=device_scope,
            start_at=start_at,
            end_at=end_at,
            interval_seconds=interval_seconds,
        )
        return CompressorAnalysisService().analyze_capability(
            payload,
            capability,
            message,
        )

    return invoke


ADDITIONAL_COMPRESSOR_TOOLS = tuple(
    _direct_additional_tool(name, capability, message, description)
    for name, (capability, message, description) in ADDITIONAL_CAPABILITY_TOOLS.items()
)

COMPRESSOR_TOOLS = (*COMPRESSOR_TOOLS, *ADDITIONAL_COMPRESSOR_TOOLS)


class CompressorGraphToolInput(StrictModel):
    context: Annotated[
        CompressorSystemContext,
        InjectedState("compressor_context"),
    ]


def _graph_capability_result(
    context: CompressorSystemContext,
    capability: CompressorCapability,
    message: str,
) -> tuple[str, CompressorAnalysisResult]:
    result = CompressorAnalysisService().analyze_context(
        context,
        [capability],
        message,
    )
    return result.model_dump_json(), result


def _graph_additional_tool(
    name: str,
    capability: CompressorCapability,
    message: str,
    description: str,
) -> BaseTool:
    @tool(
        name,
        args_schema=CompressorGraphToolInput,
        response_format="content_and_artifact",
        description=description,
    )
    def invoke(context: CompressorSystemContext):
        return _graph_capability_result(context, capability, message)

    return invoke


@tool(
    "analyze_compressor_load_unload_rate",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_analyze_compressor_load_unload_rate_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点分析空压机加载率和卸载率。"""
    return _graph_capability_result(
        context,
        "load_rate",
        "分析单机加载率和卸载率",
    )


@tool(
    "detect_compressor_idle_running",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_detect_compressor_idle_running_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点识别空压机空载运行。"""
    return _graph_capability_result(
        context,
        "idle_running",
        "识别单机空载运行",
    )


@tool(
    "detect_compressor_frequent_starts",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_detect_compressor_frequent_starts_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点识别空压机频繁启停。"""
    return _graph_capability_result(
        context,
        "frequent_start",
        "识别单机频繁启停",
    )


@tool(
    "analyze_compressor_pressure_fluctuation",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_analyze_compressor_pressure_fluctuation_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点分析空压系统压力波动。"""
    return _graph_capability_result(
        context,
        "pressure_fluctuation",
        "分析管网压力波动",
    )


@tool(
    "detect_compressor_high_supply_pressure",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_detect_compressor_high_supply_pressure_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点识别空压系统供气压力过高。"""
    return _graph_capability_result(
        context,
        "high_pressure",
        "识别供气压力过高",
    )


@tool(
    "calculate_compressor_specific_power",
    args_schema=CompressorGraphToolInput,
    response_format="content_and_artifact",
)
def graph_calculate_compressor_specific_power_tool(
    context: CompressorSystemContext,
):
    """通过受控 LangGraph 节点计算空压系统比功率。"""
    return _graph_capability_result(
        context,
        "specific_power",
        "计算空压系统比功率",
    )


COMPRESSOR_GRAPH_TOOLS = (
    graph_analyze_compressor_load_unload_rate_tool,
    graph_detect_compressor_idle_running_tool,
    graph_detect_compressor_frequent_starts_tool,
    graph_analyze_compressor_pressure_fluctuation_tool,
    graph_detect_compressor_high_supply_pressure_tool,
    graph_calculate_compressor_specific_power_tool,
    *(
        _graph_additional_tool(name, capability, message, description)
        for name, (capability, message, description) in ADDITIONAL_CAPABILITY_TOOLS.items()
    ),
)
