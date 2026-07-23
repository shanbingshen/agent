import hashlib
from collections.abc import Callable
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from pydantic import Field

from arthra.config import Settings
from arthra.contracts import JsonValue, StrictModel
from arthra.daily_schemas import DailyDeviceStatistics, DailySnapshot

type DailyExpert = Literal["operations", "power", "compressor", "risk", "carbon"]
type InsightTone = Literal["info", "good", "warning", "critical", "muted"]
DailyRenderer = Callable[[str, DailySnapshot], str]
DailyNarrator = Callable[[str, DailySnapshot, Settings], str]


class DailyInsightMetric(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    value: JsonValue
    unit: str | None = Field(default=None, max_length=32)


class DailyInsightEvidence(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)


class DailyInsightSection(StrictModel):
    section_id: str = Field(min_length=1, max_length=64)
    expert: DailyExpert
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    tone: InsightTone = "info"
    metrics: list[DailyInsightMetric] = Field(default_factory=list, max_length=20)
    evidence: list[DailyInsightEvidence] = Field(default_factory=list, max_length=20)


class DailyInsightResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experts: list[DailyExpert]
    sections: list[DailyInsightSection]
    content: str
    generation_status: Literal["deterministic", "generated", "fallback"]
    model_name: str
    deterministic_hash: str = Field(min_length=64, max_length=64)


class DailyInsightState(StrictModel):
    title: str
    snapshot: DailySnapshot
    experts: list[DailyExpert] = Field(default_factory=list)
    sections: list[DailyInsightSection] = Field(default_factory=list)
    deterministic_content: str = ""
    content: str = ""
    generation_status: Literal["deterministic", "generated", "fallback"] = "deterministic"
    model_name: str = "deterministic-fallback"
    deterministic_hash: str = ""


def _latest_metric(device: DailyDeviceStatistics, key: str) -> float | None:
    metric = device.metrics.get(key)
    return metric.latest if metric is not None else None


def _route_experts(state: DailyInsightState) -> dict[str, Any]:
    device_types = {device.device_type for device in state.snapshot.devices}
    experts: list[DailyExpert] = ["operations"]
    if "meter" in device_types:
        experts.append("power")
    if "compressor" in device_types:
        experts.append("compressor")
    if state.snapshot.warnings or state.snapshot.thingsboard_alarms:
        experts.append("risk")
    experts.append("carbon")
    return {"experts": list(dict.fromkeys(experts))}


def _build_sections(state: DailyInsightState) -> dict[str, Any]:
    snapshot = state.snapshot
    overview = snapshot.overview
    source_evidence = [
        DailyInsightEvidence(label="数据来源", value="统一工业数据接口"),
        DailyInsightEvidence(
            label="设备覆盖",
            value=f"{overview.available_device_count}/{overview.device_count} 台",
        ),
    ]
    sections: list[DailyInsightSection] = [
        DailyInsightSection(
            section_id="operations-overview",
            expert="operations",
            title="经营概览",
            summary="基于已接入设备形成确定性运行概览。",
            tone="good" if not snapshot.warnings else "warning",
            metrics=[
                DailyInsightMetric(label="可用设备", value=overview.available_device_count, unit="台"),
                DailyInsightMetric(
                    label="平均有功功率",
                    value=overview.average_active_power_kw,
                    unit="kW",
                ),
                DailyInsightMetric(
                    label="统计期用电增量",
                    value=overview.energy_consumption_kwh,
                    unit="kWh",
                ),
            ],
            evidence=source_evidence,
        )
    ]
    if "power" in state.experts:
        meters = [device for device in snapshot.devices if device.device_type == "meter"]
        peaks = [metric.max for device in meters if (metric := device.metrics.get("meter_TotW"))]
        sections.append(
            DailyInsightSection(
                section_id="power-insight",
                expert="power",
                title="电力与需量洞察",
                summary="电力指标来自表计历史样本，不使用实时功率替代15分钟需量。",
                tone="info",
                metrics=[
                    DailyInsightMetric(
                        label="样本功率峰值",
                        value=max(peaks) if peaks else None,
                        unit="kW",
                    ),
                    DailyInsightMetric(label="电表数量", value=len(meters), unit="台"),
                ],
                evidence=[
                    *source_evidence,
                    DailyInsightEvidence(label="计算边界", value="历史表计样本确定性统计"),
                ],
            )
        )
    if "compressor" in state.experts:
        compressors = [
            device for device in snapshot.devices if device.device_type == "compressor"
        ]
        pressure_values = [
            value
            for device in compressors
            if (value := _latest_metric(device, "air_comp_supply_pressure")) is not None
        ]
        sections.append(
            DailyInsightSection(
                section_id="compressor-insight",
                expert="compressor",
                title="空压系统洞察",
                summary="空压指标只呈现当前数据范围内可复现的设备状态。",
                tone="info",
                metrics=[
                    DailyInsightMetric(label="空压机数量", value=len(compressors), unit="台"),
                    DailyInsightMetric(
                        label="最新最高供气压力",
                        value=max(pressure_values) if pressure_values else None,
                        unit="MPa",
                    ),
                ],
                evidence=source_evidence,
            )
        )
    if "risk" in state.experts:
        sections.append(
            DailyInsightSection(
                section_id="risk-insight",
                expert="risk",
                title="异常风险",
                summary="风险仅来自确定性规则提醒和工业数据源活动告警。",
                tone="critical" if any(item.severity == "critical" for item in snapshot.warnings) else "warning",
                metrics=[
                    DailyInsightMetric(label="规则提醒", value=len(snapshot.warnings), unit="条"),
                    DailyInsightMetric(
                        label="活动告警", value=len(snapshot.thingsboard_alarms), unit="条"
                    ),
                ],
                evidence=[
                    *source_evidence,
                    DailyInsightEvidence(label="风险口径", value="确定性规则与活动告警"),
                ],
            )
        )
    carbon_ready = overview.energy_consumption_kwh is not None
    sections.append(
        DailyInsightSection(
            section_id="carbon-readiness",
            expert="carbon",
            title="碳核算准备度",
            summary=(
                "已具备能耗活动数据；正式碳排仍需排放因子与组织边界。"
                if carbon_ready
                else "当前能耗活动数据不足，不能计算正式碳排放。"
            ),
            tone="muted",
            metrics=[
                DailyInsightMetric(label="能耗活动数据", value="已具备" if carbon_ready else "不足"),
                DailyInsightMetric(label="排放因子", value="未接入"),
            ],
            evidence=source_evidence,
        )
    )
    return {"sections": sections}


def build_daily_insight_graph(
    settings: Settings,
    *,
    renderer: DailyRenderer,
    narrator: DailyNarrator | None = None,
):
    def render(state: DailyInsightState) -> dict[str, Any]:
        deterministic_content = renderer(state.title, state.snapshot)
        digest = hashlib.sha256(
            state.snapshot.model_dump_json().encode("utf-8")
        ).hexdigest()
        return {
            "deterministic_content": deterministic_content,
            "content": deterministic_content,
            "deterministic_hash": digest,
        }

    def synthesize(state: DailyInsightState) -> dict[str, Any]:
        if narrator is None or not settings.llm_api_key:
            return {
                "content": state.deterministic_content,
                "generation_status": "deterministic",
                "model_name": "deterministic-fallback",
            }
        try:
            return {
                "content": narrator(state.title, state.snapshot, settings),
                "generation_status": "generated",
                "model_name": settings.llm_model,
            }
        except Exception:
            return {
                "content": state.deterministic_content,
                "generation_status": "fallback",
                "model_name": "deterministic-fallback",
            }

    builder = StateGraph(DailyInsightState)
    builder.add_node("route_experts", _route_experts)
    builder.add_node("deterministic_experts", _build_sections)
    builder.add_node("render_deterministic", render)
    builder.add_node("narrate", synthesize)
    builder.add_edge(START, "route_experts")
    builder.add_edge("route_experts", "deterministic_experts")
    builder.add_edge("deterministic_experts", "render_deterministic")
    builder.add_edge("render_deterministic", "narrate")
    builder.add_edge("narrate", END)
    return builder.compile()


def run_daily_insight_graph(
    title: str,
    snapshot: DailySnapshot,
    settings: Settings,
    *,
    renderer: DailyRenderer,
    narrator: DailyNarrator | None = None,
) -> DailyInsightResult:
    graph = build_daily_insight_graph(settings, renderer=renderer, narrator=narrator)
    result = graph.invoke({"title": title, "snapshot": snapshot})
    return DailyInsightResult.model_validate(
        {
            "experts": result["experts"],
            "sections": result["sections"],
            "content": result["content"],
            "generation_status": result["generation_status"],
            "model_name": result["model_name"],
            "deterministic_hash": result["deterministic_hash"],
        }
    )
