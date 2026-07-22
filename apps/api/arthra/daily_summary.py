import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.agent_schemas import DeviceContext
from arthra.agent_tools import analyze_device_context, flatten_latest_telemetry
from arthra.config import Settings, get_settings
from arthra.contracts import AnalysisWarning, AttributeValues, JsonObject
from arthra.daily_insight import run_daily_insight_graph
from arthra.daily_schemas import (
    DailyAlarm,
    DailyDeviceStatistics,
    DailyOverview,
    DailySnapshot,
    HistoryMetric,
)
from arthra.db import SessionLocal
from arthra.industrial_data import IndustrialDataError, IndustrialDataService
from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.ports import IndustrialDataAdapter
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)
from arthra.models import (
    DEFAULT_FACTORY_ID,
    DEFAULT_TENANT_ID,
    AuditEvent,
    DailySummary,
)
from arthra.observability import METRICS, persist_agent_trace

SUPPORTED_DEVICE_TYPES = {"ems", "meter", "compressor"}
logger = logging.getLogger(__name__)
HISTORY_KEYS: dict[str, list[str]] = {
    "ems": ["power_kw", "energy_kwh", "soc"],
    "meter": [
        "meter_TotW",
        "meter_SupWh",
        "meter_TotPF",
        "meter_Hz",
        "meter_ImbNgV",
        "meter_ImbNgA",
        "meter_ThdPhV_phsA",
        "meter_ThdPhV_phsB",
        "meter_ThdPhV_phsC",
        "meter_ThdA_phsA",
        "meter_ThdA_phsB",
        "meter_ThdA_phsC",
    ],
    "compressor": [
        "air_comp_supply_pressure",
        "air_comp_discharge_temp",
        "air_comp_main_current_a",
        "air_comp_fad_flow_m3_min",
        "air_comp_running_hours",
        "air_comp_loading_hours",
    ],
}

HISTORY_INTERVAL_MS = 300_000
ENERGY_POWER_RATIO_MIN = 0.5
ENERGY_POWER_RATIO_MAX = 1.5


class DailySummaryError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def history_statistics(
    payload: IndustrialTelemetryHistory | dict[str, Any],
) -> dict[str, HistoryMetric]:
    """Reduce unified industrial history to reproducible numeric statistics."""
    history = IndustrialTelemetryHistory.model_validate(payload)
    statistics: dict[str, HistoryMetric] = {}
    for key, raw_samples in history.items():
        samples: list[tuple[int, float]] = []
        for sample in raw_samples or []:
            value = _number(sample.value)
            if value is not None:
                samples.append((sample.ts, value))
        if not samples:
            continue
        samples.sort(key=lambda item: item[0])
        values = [value for _, value in samples]
        statistics[key] = HistoryMetric(**{
            "samples": len(values),
            "first": round(values[0], 4),
            "latest": round(values[-1], 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "avg": round(sum(values) / len(values), 4),
            "delta": round(values[-1] - values[0], 4),
            "first_ts": samples[0][0],
            "latest_ts": samples[-1][0],
            "observed_hours": round((samples[-1][0] - samples[0][0]) / 3_600_000, 4),
        })
    return statistics


def _history_coverage(metric: HistoryMetric, period_start: datetime, period_end: datetime) -> float:
    expected = max(
        1,
        round((period_end - period_start).total_seconds() * 1000 / HISTORY_INTERVAL_MS),
    )
    return min(1.0, metric.samples / expected)


def _validated_energy_delta(
    energy: HistoryMetric,
    power: HistoryMetric | None,
) -> tuple[float | None, str | None]:
    if energy.delta < 0:
        return None, "累计电量计数器在查询窗口内发生回退或复位"
    if power is None or energy.observed_hours is None or energy.observed_hours < 0.25:
        return None, "缺少足够的有功功率或累计电量观测时长，无法交叉校验用电增量"
    expected_from_power = power.avg * energy.observed_hours
    if expected_from_power <= 0:
        return None, "有功功率积分结果无效，无法交叉校验用电增量"
    ratio = energy.delta / expected_from_power
    if not ENERGY_POWER_RATIO_MIN <= ratio <= ENERGY_POWER_RATIO_MAX:
        return None, (
            f"累计电量差值 {energy.delta:.3f} kWh 与功率积分估算 "
            f"{expected_from_power:.3f} kWh 不一致（比值 {ratio:.2f}）"
        )
    return energy.delta, None


def _recent_alarms(
    payload: IndustrialAlarmPage | dict[str, Any], start_ms: int, end_ms: int
) -> list[DailyAlarm]:
    alarms: list[DailyAlarm] = []
    for alarm in IndustrialAlarmPage.model_validate(payload).data:
        created = alarm.created_time
        if not start_ms <= created <= end_ms:
            continue
        alarms.append(
            DailyAlarm(
                type=alarm.type,
                severity=alarm.severity,
                status=alarm.status,
                created_time=created,
            )
        )
    return alarms


def collect_daily_snapshot(
    client: IndustrialDataAdapter | IndustrialDataService,
    device_scope: list[str],
    period_start: datetime,
    period_end: datetime,
) -> DailySnapshot:
    page = IndustrialDevicePage.model_validate(
        client.list_devices(page=0, page_size=1000)
    )
    all_devices = page.data
    metadata = {item.id.id: item for item in all_devices}
    selected_ids = list(dict.fromkeys(device_scope)) if device_scope else [
        item.id.id
        for item in all_devices
        if item.type in SUPPORTED_DEVICE_TYPES
    ]
    if not selected_ids:
        raise DailySummaryError("没有可用于生成摘要的 EMS、电表或空压机设备")

    start_ms = int(period_start.timestamp() * 1000)
    end_ms = int(period_end.timestamp() * 1000)
    contexts: list[DeviceContext] = []
    device_statistics: list[DailyDeviceStatistics] = []
    all_alarms: list[DailyAlarm] = []

    for device_id in selected_ids:
        device = metadata.get(device_id)
        if device is None:
            contexts.append(DeviceContext(id=device_id, error="设备不存在或当前账号无权访问"))
            continue
        device_type = device.type
        try:
            latest, timestamps = flatten_latest_telemetry(client.latest_telemetry(device_id))
            attributes = client.attributes(device_id)
            keys = HISTORY_KEYS.get(device_type, [])
            history = (
                client.telemetry_history(
                    device_id,
                    keys,
                    start_ms,
                    end_ms,
                    limit=1000,
                    agg="AVG",
                    interval=300_000,
                )
                if keys
                else {}
            )
            alarms = _recent_alarms(client.list_alarms(device_id), start_ms, end_ms)
            context = DeviceContext(
                id=device_id,
                name=device.name,
                type=device_type,
                telemetry=latest,
                timestamps=timestamps,
                attributes=AttributeValues.model_validate(attributes),
            )
            contexts.append(context)
            metrics = history_statistics(history)
            for key, metric in metrics.items():
                current_value = _number(latest.get(key))
                if current_value is not None:
                    metric.latest_bucket_avg = metric.latest
                    metric.latest = round(current_value, 4)
            device_statistics.append(DailyDeviceStatistics(
                device_id=device_id,
                device_name=context.name or device_id,
                device_type=device_type,
                metrics=metrics,
                alarm_count=len(alarms),
                alarms=alarms,
            ))
            all_alarms.extend(
                alarm.model_copy(update={"device_id": device_id, "device_name": context.name})
                for alarm in alarms
            )
        except IndustrialDataError as exc:
            contexts.append(DeviceContext(
                id=device_id,
                name=device.name,
                type=device_type,
                error=str(exc),
            ))

    analysis = analyze_device_context("report", contexts, "AI 每日能源运行摘要")
    meter_power_averages: list[float] = []
    meter_power_coverages: list[float] = []
    energy_deltas: list[float] = []
    integrity_warnings: list[AnalysisWarning] = []
    integrity_missing: list[str] = []
    for device in device_statistics:
        metrics = device["metrics"]
        power_metric = metrics.get("meter_TotW")
        energy_metric = metrics.get("meter_SupWh")
        if power_metric is not None:
            meter_power_averages.append(float(power_metric.avg))
            meter_power_coverages.append(
                _history_coverage(power_metric, period_start, period_end)
            )
        if energy_metric is not None:
            energy_delta, validation_error = _validated_energy_delta(
                energy_metric, power_metric
            )
            if energy_delta is not None:
                energy_deltas.append(energy_delta)
            elif validation_error:
                message = f"{device.device_name}: {validation_error}"
                integrity_missing.append(message)
                integrity_warnings.append(
                    AnalysisWarning(
                        severity="high",
                        code="INVALID_ENERGY_COUNTER_DELTA",
                        device_id=device.device_id,
                        device_name=device.device_name,
                        metric="meter_SupWh",
                        message=message,
                        evidence={
                            "counter_delta_kwh": energy_metric.delta,
                            "average_power_kw": power_metric.avg if power_metric else None,
                            "observed_hours": energy_metric.observed_hours,
                        },
                    )
                )

    snapshot_warnings = [*analysis.warnings, *integrity_warnings]
    if energy_deltas and integrity_warnings:
        energy_status = "partial"
    elif energy_deltas:
        energy_status = "available"
    elif integrity_warnings:
        energy_status = "invalid"
    else:
        energy_status = "unavailable"

    return DailySnapshot(
        overview=DailyOverview(**{
            "device_count": len(selected_ids),
            "available_device_count": len(device_statistics),
            "warning_count": len(snapshot_warnings),
            "alarm_count": len(all_alarms),
            "average_active_power_kw": round(sum(meter_power_averages) / len(meter_power_averages), 3) if meter_power_averages else None,
            "active_power_data_coverage": round(
                sum(meter_power_coverages) / len(meter_power_coverages), 4
            ) if meter_power_coverages else None,
            "energy_consumption_kwh": round(sum(energy_deltas), 3) if energy_deltas else None,
            "energy_consumption_status": energy_status,
        }),
        devices=device_statistics,
        findings=analysis.findings,
        missing_metrics=[*analysis.missing_metrics, *integrity_missing],
        warnings=snapshot_warnings,
        thingsboard_alarms=all_alarms,
    )


def deterministic_summary(title: str, snapshot: DailySnapshot) -> str:
    overview = snapshot["overview"]
    lines = [
        f"# {title}",
        "",
        "## 运行概况",
        f"- 覆盖设备：{overview['available_device_count']} / {overview['device_count']} 台",
        f"- 确定性规则提醒：{overview['warning_count']} 条",
        f"- ThingsBoard 告警：{overview['alarm_count']} 条",
    ]
    if overview.get("average_active_power_kw") is not None:
        coverage = overview.get("active_power_data_coverage")
        coverage_text = f"，数据覆盖率 {coverage:.1%}" if coverage is not None else ""
        lines.append(
            f"- 查询窗口已有样本平均有功功率：{overview['average_active_power_kw']:.3f} kW"
            f"{coverage_text}"
        )
    if overview.get("energy_consumption_kwh") is not None:
        lines.append(f"- 查询窗口内可用数据用电增量：{overview['energy_consumption_kwh']:.3f} kWh")
    elif overview.get("energy_consumption_status") == "invalid":
        lines.append("- 查询窗口用电增量：累计表计与功率积分不一致，已拒绝输出错误电量")
    lines.extend(["", "## 当前关键读数"])
    lines.extend(f"- {finding}" for finding in snapshot["findings"][:20])
    if not snapshot["findings"]:
        lines.append("- 未获得有效设备读数。")
    lines.extend(["", "## 风险与建议"])
    if snapshot["warnings"]:
        lines.extend(
            f"- [{warning.get('severity', 'unknown')}] {warning.get('device_name', '设备')}：{warning.get('message', '状态异常')}"
            for warning in snapshot["warnings"]
        )
    else:
        lines.append("- 当前确定性规则未发现异常，建议继续观察负荷和设备趋势。")
    if snapshot["missing_metrics"]:
        lines.extend(["", "## 数据完整性"])
        lines.extend(f"- {item}" for item in snapshot["missing_metrics"][:20])
    return "\n".join(lines)


def _synthesize_with_llm(title: str, snapshot: DailySnapshot, settings: Settings) -> str:
    model = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )
    prompt = "\n".join(
        [
            "你是 Arthra 能碳大脑的每日运营摘要专家。请使用中文 Markdown 输出简洁、专业、可执行的每日摘要。",
            "只能使用下方确定性统计和 ThingsBoard 数据，严禁虚构历史趋势、节能量、告警或设备读数。",
            "结构必须包含：运行概况、能源与电能质量、空压机状态、风险提醒、今日建议。",
            "若数据缺失要明确说明；若建议涉及控制，只能建议创建待审批计划，不能声称已经执行。",
            "energy_consumption_kwh 是最近 24 小时查询窗口内已有数据的电量增量；不要声称数据一定完整覆盖 24 小时。",
            "energy_consumption_status 不是 available/partial 时，不得输出或估算用电增量。",
            "average_active_power_kw 只是已有历史样本均值，必须同时说明 active_power_data_coverage。",
            "devices.metrics 中 latest 是当前实时值，latest_bucket_avg 是最后一个 5 分钟历史桶均值；不要混淆二者。",
            "所有异常判断必须来自 warnings；所有数据缺失判断必须逐字来自 missing_metrics。",
            "不得自行新增阈值、告警、缺失指标或设备关联关系，也不得把低于阈值的指标描述为偏高。",
            f"标题：{title}",
            "24 小时确定性统计：",
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
        ]
    )
    response = model.invoke(prompt)
    return str(response.content)


def generate_daily_summary(
    db: Session,
    device_scope: list[str],
    generated_by: uuid.UUID | None,
    trigger: str = "manual",
    now: datetime | None = None,
    client: IndustrialDataAdapter | IndustrialDataService | None = None,
    settings: Settings | None = None,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    factory_id: uuid.UUID = DEFAULT_FACTORY_ID,
) -> DailySummary:
    started = perf_counter()
    settings = settings or get_settings()
    period_end = now or datetime.now(UTC)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=UTC)
    period_start = period_end - timedelta(hours=24)
    local_date = period_end.astimezone(ZoneInfo(settings.daily_summary_timezone)).date()
    title = f"Arthra AI 每日摘要 · {local_date.isoformat()}"
    snapshot = collect_daily_snapshot(
        client or get_industrial_data_service(),
        device_scope,
        period_start,
        period_end,
    )
    insight = run_daily_insight_graph(
        title,
        snapshot,
        settings,
        renderer=deterministic_summary,
        narrator=_synthesize_with_llm,
    )
    status = insight.generation_status
    model_name = insight.model_name
    content = insight.content

    summary = DailySummary(
        tenant_id=tenant_id,
        factory_id=factory_id,
        summary_date=local_date,
        period_start=period_start,
        period_end=period_end,
        title=title,
        content=content,
        device_scope=[device.device_id for device in snapshot.devices],
        statistics=snapshot.model_dump(mode="json"),
        warnings=[warning.model_dump(mode="json") for warning in snapshot.warnings],
        insight_payload=insight.model_dump(mode="json"),
        model_name=model_name,
        status=status,
        trigger=trigger,
        generated_by=generated_by,
    )
    db.add(summary)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            factory_id=factory_id,
            actor_id=generated_by,
            action="daily_summary.generated",
            resource_type="daily_summary",
            resource_id=str(summary.id),
            details=JsonObject(
                {
                    "summary_date": local_date.isoformat(),
                    "trigger": trigger,
                    "status": status,
                }
            ).model_dump(mode="json"),
        )
    )
    duration_ms = (perf_counter() - started) * 1000
    METRICS.increment(
        "daily_insight_runs_total",
        labels={"status": status},
    )
    METRICS.observe("daily_insight_duration_ms", duration_ms)
    persist_agent_trace(
        db,
        trace_id=uuid.uuid4().hex,
        request_id=str(summary.id),
        tenant_id=tenant_id,
        factory_id=factory_id,
        user_id=generated_by,
        thread_id=None,
        operation="daily_insight",
        status=status,
        duration_ms=duration_ms,
        route="daily_insight",
        tool_names=[f"daily_{expert}_expert" for expert in insight.experts],
    )
    db.commit()
    db.refresh(summary)
    return summary


def ensure_scheduled_summary() -> DailySummary | None:
    settings = get_settings()
    if not settings.daily_summary_enabled:
        return None
    local_now = datetime.now(ZoneInfo(settings.daily_summary_timezone))
    with SessionLocal() as db:
        existing = db.scalar(
            select(DailySummary).where(
                DailySummary.tenant_id == DEFAULT_TENANT_ID,
                DailySummary.factory_id == DEFAULT_FACTORY_ID,
                DailySummary.summary_date == local_now.date(),
                DailySummary.trigger == "scheduled",
            )
        )
        if existing is not None:
            return existing
        return generate_daily_summary(
            db,
            device_scope=[],
            generated_by=None,
            trigger="scheduled",
            now=local_now.astimezone(UTC),
            settings=settings,
            tenant_id=DEFAULT_TENANT_ID,
            factory_id=DEFAULT_FACTORY_ID,
        )


async def daily_summary_scheduler() -> None:
    settings = get_settings()
    if not settings.daily_summary_enabled:
        return
    timezone = ZoneInfo(settings.daily_summary_timezone)
    while True:
        now = datetime.now(timezone)
        today_run = datetime.combine(
            now.date(), time(hour=settings.daily_summary_hour), tzinfo=timezone
        )
        if now >= today_run:
            try:
                await asyncio.to_thread(ensure_scheduled_summary)
            except Exception:
                logger.exception("Scheduled daily summary generation failed")
            next_run = today_run + timedelta(days=1)
        else:
            next_run = today_run
        await asyncio.sleep(max(1, (next_run - datetime.now(timezone)).total_seconds()))
