import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.agent_schemas import DeviceContext
from arthra.agent_tools import analyze_device_context, flatten_latest_telemetry
from arthra.config import Settings, get_settings
from arthra.contracts import AttributeValues, JsonObject
from arthra.daily_schemas import (
    DailyAlarm,
    DailyDeviceStatistics,
    DailyOverview,
    DailySnapshot,
    HistoryMetric,
)
from arthra.db import SessionLocal
from arthra.models import AuditEvent, DailySummary
from arthra.thingsboard import ThingsBoardClient, ThingsBoardError
from arthra.thingsboard_schemas import AlarmPage, DevicePage, TelemetryHistory

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
        "air_comp_running_hours",
        "air_comp_loading_hours",
    ],
}


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
    payload: TelemetryHistory | dict[str, Any],
) -> dict[str, HistoryMetric]:
    """Reduce a ThingsBoard history payload to reproducible numeric statistics."""
    history = TelemetryHistory.model_validate(payload)
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
        })
    return statistics


def _recent_alarms(
    payload: AlarmPage | dict[str, Any], start_ms: int, end_ms: int
) -> list[DailyAlarm]:
    alarms: list[DailyAlarm] = []
    for alarm in AlarmPage.model_validate(payload).data:
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
    client: ThingsBoardClient,
    device_scope: list[str],
    period_start: datetime,
    period_end: datetime,
) -> DailySnapshot:
    page = DevicePage.model_validate(client.list_devices(page=0, page_size=1000))
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
        except ThingsBoardError as exc:
            contexts.append(DeviceContext(
                id=device_id,
                name=device.name,
                type=device_type,
                error=str(exc),
            ))

    analysis = analyze_device_context("report", contexts, "AI 每日能源运行摘要")
    meter_power_averages: list[float] = []
    energy_deltas: list[float] = []
    for device in device_statistics:
        metrics = device["metrics"]
        if "meter_TotW" in metrics:
            meter_power_averages.append(float(metrics["meter_TotW"]["avg"]))
        if "meter_SupWh" in metrics:
            energy_deltas.append(max(0.0, float(metrics["meter_SupWh"]["delta"])))

    return DailySnapshot(
        overview=DailyOverview(**{
            "device_count": len(selected_ids),
            "available_device_count": len(device_statistics),
            "warning_count": len(analysis["warnings"]),
            "alarm_count": len(all_alarms),
            "average_active_power_kw": round(sum(meter_power_averages) / len(meter_power_averages), 3) if meter_power_averages else None,
            "energy_consumption_kwh": round(sum(energy_deltas), 3) if energy_deltas else None,
        }),
        devices=device_statistics,
        findings=analysis.findings,
        missing_metrics=analysis.missing_metrics,
        warnings=analysis.warnings,
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
        lines.append(f"- 24 小时平均有功功率：{overview['average_active_power_kw']:.3f} kW")
    if overview.get("energy_consumption_kwh") is not None:
        lines.append(f"- 查询窗口内可用数据用电增量：{overview['energy_consumption_kwh']:.3f} kWh")
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
            "devices.metrics 中 latest 是当前实时值，latest_bucket_avg 是最后一个 5 分钟历史桶均值；不要混淆二者。",
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
    client: ThingsBoardClient | None = None,
    settings: Settings | None = None,
) -> DailySummary:
    settings = settings or get_settings()
    period_end = now or datetime.now(UTC)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=UTC)
    period_start = period_end - timedelta(hours=24)
    local_date = period_end.astimezone(ZoneInfo(settings.daily_summary_timezone)).date()
    title = f"Arthra AI 每日摘要 · {local_date.isoformat()}"
    snapshot = collect_daily_snapshot(
        client or ThingsBoardClient(settings=settings), device_scope, period_start, period_end
    )
    status = "deterministic"
    model_name = "deterministic-fallback"
    content = deterministic_summary(title, snapshot)
    if settings.llm_api_key:
        try:
            content = _synthesize_with_llm(title, snapshot, settings)
            status = "generated"
            model_name = settings.llm_model
        except Exception:
            status = "fallback"

    summary = DailySummary(
        summary_date=local_date,
        period_start=period_start,
        period_end=period_end,
        title=title,
        content=content,
        device_scope=[device.device_id for device in snapshot.devices],
        statistics=snapshot.model_dump(mode="json"),
        warnings=[warning.model_dump(mode="json") for warning in snapshot.warnings],
        model_name=model_name,
        status=status,
        trigger=trigger,
        generated_by=generated_by,
    )
    db.add(summary)
    db.flush()
    db.add(
        AuditEvent(
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
