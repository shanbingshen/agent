from datetime import datetime
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from arthra.contracts import StrictModel
from arthra.power.analysis import PowerAnalysisService
from arthra.power.schemas import (
    PowerAnalysisResult,
    PowerCapability,
    PowerSystemContext,
    PowerToolInput,
)

TOOL_CAPABILITIES: dict[str, tuple[PowerCapability, str, str]] = {
    "get_meter_realtime": (
        "realtime_power",
        "查询电表实时有功功率",
        "只读取所选电表最新有功功率及其数据时间。",
    ),
    "get_energy_consumption": (
        "energy_consumption",
        "计算统计周期用电量",
        "根据累计正向有功电量的期末值减期初值计算周期用电量。",
    ),
    "compare_energy_periods": (
        "energy_compare",
        "比较相邻周期用电量",
        "根据两个相邻周期的累计电量差值计算变化量和变化率。",
    ),
    "calculate_rolling_15m_max_demand": ("demand_15m", "计算15分钟滚动最大需量", "按历史有功功率计算15分钟滚动平均与最大需量。"),
    "detect_power_peaks": ("peak_detection", "识别负荷峰值", "识别历史有功功率序列中的局部负荷峰值。"),
    "analyze_peak_average_ratio": ("peak_average_ratio", "分析峰均比", "计算负荷峰值与窗口平均负荷之比。"),
    "detect_declared_demand_exceedance": ("declared_demand_exceedance", "识别需量控制目标越限", "将15分钟滚动需量与需量控制目标比较并计算越限时长。"),
    "detect_voltage_deviation": ("voltage_deviation", "识别电压偏差", "按额定线电压计算三相线电压偏差与越限时长。"),
    "detect_three_phase_imbalance": ("phase_imbalance", "识别三相不平衡", "分析电压和电流不平衡度及越限持续时间。"),
    "detect_power_factor_anomaly": ("power_factor", "识别功率因数异常", "识别总功率因数低于阈值的时间区间。"),
    "detect_thdu_thdi_anomaly": ("thd", "识别THDu/THDi异常", "分析三相电压和电流总谐波畸变率及越限时长。"),
    "analyze_3_5_7_harmonics": ("harmonics", "分析3/5/7次谐波特征", "汇总三相3、5、7次电压与电流谐波并识别主导次数。"),
    "calculate_power_quality_abnormal_duration": ("abnormal_duration", "计算电能质量异常持续时间", "统一计算电压偏差、不平衡、功率因数和THD异常持续时间。"),
}


def _direct_tool(name: str, capability: PowerCapability, message: str, description: str) -> BaseTool:
    @tool(name, args_schema=PowerToolInput, description=description)
    def invoke(
        device_scope: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        interval_seconds: int = 60,
        declared_demand_kw: float | None = None,
    ) -> PowerAnalysisResult:
        payload = PowerToolInput(
            device_scope=device_scope,
            start_at=start_at,
            end_at=end_at,
            interval_seconds=interval_seconds,
            declared_demand_kw=declared_demand_kw,
        )
        return PowerAnalysisService().analyze_capability(payload, capability, message)

    return invoke


POWER_TOOLS = tuple(
    _direct_tool(name, capability, message, description)
    for name, (capability, message, description) in TOOL_CAPABILITIES.items()
)


class PowerGraphToolInput(StrictModel):
    context: Annotated[PowerSystemContext, InjectedState("power_context")]


def _graph_tool(name: str, capability: PowerCapability, message: str, description: str) -> BaseTool:
    @tool(
        name,
        args_schema=PowerGraphToolInput,
        response_format="content_and_artifact",
        description=description,
    )
    def invoke(context: PowerSystemContext) -> tuple[str, PowerAnalysisResult]:
        result = PowerAnalysisService().analyze_context(context, [capability], message)
        return result.model_dump_json(), result

    return invoke


POWER_GRAPH_TOOLS = tuple(
    _graph_tool(name, capability, message, description)
    for name, (capability, message, description) in TOOL_CAPABILITIES.items()
)
