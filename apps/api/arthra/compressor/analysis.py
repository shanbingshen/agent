import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import fmean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from arthra.compressor.capabilities import infer_capabilities
from arthra.compressor.context import CompressorContextBuilder, CompressorContextError
from arthra.compressor.schemas import (
    AirSystemDevice,
    CompressorAnalysisRequest,
    CompressorAnalysisResult,
    CompressorCapability,
    CompressorSystemContext,
    LoadUnloadRateDeviceResult,
    LoadUnloadRateToolInput,
    LoadUnloadRateToolResult,
    SignalPoint,
)
from arthra.config import Settings, get_settings


def _points(device: AirSystemDevice, key: str) -> list[SignalPoint]:
    signal = device.signals.get(key)
    return signal.points if signal else []


def _mean(points: list[SignalPoint]) -> float | None:
    return fmean(point.value for point in points) if points else None


def _delta(points: list[SignalPoint]) -> float | None:
    if len(points) < 2:
        return None
    delta = points[-1].value - points[0].value
    return delta if delta >= 0 else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _bucket_map(points: list[SignalPoint], interval_ms: int) -> dict[int, float]:
    return {round(point.ts / interval_ms): point.value for point in points}


def _aligned(
    left: list[SignalPoint], right: list[SignalPoint], interval_ms: int
) -> list[tuple[int, float, float]]:
    right_by_bucket = _bucket_map(right, interval_ms)
    aligned: list[tuple[int, float, float]] = []
    for point in left:
        bucket = round(point.ts / interval_ms)
        if bucket in right_by_bucket:
            aligned.append((point.ts, point.value, right_by_bucket[bucket]))
    return aligned


def _longest_active_minutes(points: list[SignalPoint], interval_seconds: int) -> float:
    longest = 0.0
    current = 0.0
    previous_ts: int | None = None
    max_gap_ms = interval_seconds * 1500
    for point in points:
        if previous_ts is not None and point.ts - previous_ts > max_gap_ms:
            current = 0
        if point.value > 0:
            current += max(0, min(1, point.value)) * interval_seconds / 60
            longest = max(longest, current)
        else:
            current = 0
        previous_ts = point.ts
    return round(longest, 2)


def _observation_hours(points: list[SignalPoint]) -> float | None:
    if len(points) < 2:
        return None
    duration_ms = points[-1].ts - points[0].ts
    return duration_ms / 3_600_000 if duration_ms > 0 else None


def _linked_meter(context: CompressorSystemContext, compressor: AirSystemDevice) -> AirSystemDevice | None:
    linked_id = compressor.attributes.get("linkedMeterDeviceId")
    if linked_id:
        for meter in context.meters:
            if meter.device_id == linked_id:
                return meter
    return context.meters[0] if len(context.meters) == 1 else None


def analyze_load_unload_rate_context(
    context: CompressorSystemContext,
    settings: Settings | None = None,
) -> LoadUnloadRateToolResult:
    settings = settings or get_settings()
    interval_ms = context.interval_seconds * 1000
    expected_samples = max(
        1,
        math.ceil((context.end_ts - context.start_ts) / interval_ms),
    )
    requested_ids = set(context.requested_device_scope)
    compressors = [
        compressor
        for compressor in context.compressors
        if not requested_ids or compressor.device_id in requested_ids
    ]
    devices: list[LoadUnloadRateDeviceResult] = []
    warnings: list[dict[str, Any]] = []
    missing: list[str] = []

    for compressor in compressors:
        running = _points(compressor, "air_comp_running_flag")
        loaded = _points(compressor, "air_comp_loaded_flag")
        aligned = _aligned(running, loaded, interval_ms)
        running_units = sum(max(0.0, min(1.0, run)) for _, run, _ in aligned)
        loaded_units = sum(
            min(max(0.0, min(1.0, run)), max(0.0, min(1.0, load)))
            for _, run, load in aligned
        )
        method = None
        load_rate = None
        running_minutes = None
        loaded_minutes = None
        coverage = min(1.0, len(aligned) / expected_samples)

        if aligned and running_units > 0:
            method = "aligned-state-ratio"
            load_rate = loaded_units / running_units * 100
            running_minutes = running_units * context.interval_seconds / 60
            loaded_minutes = loaded_units * context.interval_seconds / 60
        else:
            running_hours = _points(compressor, "air_comp_running_hours")
            loading_hours = _points(compressor, "air_comp_loading_hours")
            running_delta = _delta(running_hours)
            loading_delta = _delta(loading_hours)
            counter_samples = min(len(running_hours), len(loading_hours))
            coverage = min(1.0, counter_samples / expected_samples)
            if running_delta is not None and running_delta > 0 and loading_delta is not None:
                method = "cumulative-hours-delta"
                load_rate = loading_delta / running_delta * 100
                running_minutes = running_delta * 60
                loaded_minutes = min(loading_delta, running_delta) * 60

        if load_rate is None or running_minutes is None or loaded_minutes is None:
            reason = f"{compressor.device_name}: 加载/运行状态历史或累计小时差值"
            missing.append(reason)
            devices.append(
                LoadUnloadRateDeviceResult(
                    device_id=compressor.device_id,
                    device_name=compressor.device_name,
                    data_status="unavailable",
                    aligned_sample_count=len(aligned),
                    sample_coverage=round(coverage, 4),
                    unload_warning_threshold_pct=settings.compressor_unload_rate_warning_pct,
                    missing_metrics=[reason],
                )
            )
            continue

        load_rate = max(0.0, min(100.0, load_rate))
        unload_rate = 100 - load_rate
        unloaded_minutes = max(0.0, running_minutes - loaded_minutes)
        exceeds_threshold = unload_rate >= settings.compressor_unload_rate_warning_pct
        if exceeds_threshold:
            warnings.append(
                {
                    "severity": "medium",
                    "code": "HIGH_UNLOAD_RATE",
                    "device_id": compressor.device_id,
                    "device_name": compressor.device_name,
                    "message": (
                        f"卸载率 {unload_rate:.2f}% 高于配置阈值 "
                        f"{settings.compressor_unload_rate_warning_pct:.0f}%"
                    ),
                    "evidence": {
                        "load_rate_pct": round(load_rate, 2),
                        "unload_rate_pct": round(unload_rate, 2),
                        "sample_coverage": round(coverage, 4),
                    },
                }
            )
        devices.append(
            LoadUnloadRateDeviceResult(
                device_id=compressor.device_id,
                device_name=compressor.device_name,
                data_status="available",
                calculation_method=method,
                load_rate_pct=round(load_rate, 2),
                unload_rate_pct=round(unload_rate, 2),
                aligned_sample_count=len(aligned),
                running_minutes=round(running_minutes, 2),
                loaded_minutes=round(loaded_minutes, 2),
                unloaded_minutes=round(unloaded_minutes, 2),
                sample_coverage=round(coverage, 4),
                unload_warning_threshold_pct=settings.compressor_unload_rate_warning_pct,
                exceeds_unload_warning_threshold=exceeds_threshold,
            )
        )

    available_count = sum(device.data_status == "available" for device in devices)
    if not devices or available_count == 0:
        data_status = "unavailable"
    elif available_count < len(devices) or any(
        device.sample_coverage < settings.compressor_min_data_coverage for device in devices
    ):
        data_status = "partial"
    else:
        data_status = "available"
    return LoadUnloadRateToolResult(
        air_system_id=context.air_system_id,
        start_ts=context.start_ts,
        end_ts=context.end_ts,
        interval_seconds=context.interval_seconds,
        data_status=data_status,
        devices=devices,
        warnings=warnings,
        missing_metrics=missing,
    )


def _analyze_operation(
    context: CompressorSystemContext,
    settings: Settings,
    metrics: dict[str, Any],
    findings: list[str],
    warnings: list[dict[str, Any]],
    missing: list[str],
    capabilities: list[str],
) -> None:
    device_metrics: dict[str, dict[str, Any]] = {}

    if "load_rate" in capabilities:
        load_result = analyze_load_unload_rate_context(context, settings)
        warnings.extend(warning.model_dump(mode="json") for warning in load_result.warnings)
        missing.extend(load_result.missing_metrics)
        for result in load_result.devices:
            item = device_metrics.setdefault(
                result.device_id,
                {"device_name": result.device_name},
            )
            if result.data_status != "available":
                continue
            item.update(
                {
                    "load_rate_pct": result.load_rate_pct,
                    "unload_rate_pct": result.unload_rate_pct,
                    "load_unload_method": result.calculation_method,
                    "aligned_sample_count": result.aligned_sample_count,
                    "running_minutes": result.running_minutes,
                    "loaded_minutes": result.loaded_minutes,
                    "unloaded_minutes": result.unloaded_minutes,
                    "sample_coverage": result.sample_coverage,
                }
            )
            findings.append(
                f"{result.device_name}: 运行期间加载率 {result.load_rate_pct:.2f}%，"
                f"卸载率 {result.unload_rate_pct:.2f}%（{result.calculation_method}）"
            )

    for compressor in context.compressors:
        if context.requested_device_scope and compressor.device_id not in context.requested_device_scope:
            continue
        item = device_metrics.setdefault(
            compressor.device_id,
            {"device_name": compressor.device_name},
        )
        unloaded = _points(compressor, "air_comp_unloaded_running_flag")
        if "idle_running" in capabilities and unloaded:
            idle_minutes = sum(point.value for point in unloaded) * context.interval_seconds / 60
            longest_idle = _longest_active_minutes(unloaded, context.interval_seconds)
            item["idle_running_minutes"] = round(idle_minutes, 2)
            item["longest_idle_running_minutes"] = longest_idle
            findings.append(
                f"{compressor.device_name}: 窗口内卸载空载约 {idle_minutes:.2f} min，最长连续约 {longest_idle:.2f} min"
            )
            if longest_idle >= settings.compressor_idle_warning_minutes:
                warnings.append(
                    {
                        "severity": "medium",
                        "code": "EXCESSIVE_CONTINUOUS_IDLE_RUNNING",
                        "device_id": compressor.device_id,
                        "device_name": compressor.device_name,
                        "message": f"最长连续卸载空载约 {longest_idle:.2f} min",
                        "evidence": {
                            "idle_running_minutes": round(idle_minutes, 2),
                            "longest_idle_minutes": longest_idle,
                            "continuous_idle_threshold_minutes": settings.compressor_idle_warning_minutes,
                        },
                    }
                )
        elif "idle_running" in capabilities:
            missing.append(f"{compressor.device_name}: air_comp_unloaded_running_flag")

        start_points = (
            _points(compressor, "air_comp_start_count")
            if "frequent_start" in capabilities
            else []
        )
        starts = _delta(start_points) if start_points else None
        observation_hours = _observation_hours(start_points)
        if (
            "frequent_start" in capabilities
            and starts is not None
            and observation_hours is not None
        ):
            starts_per_hour = starts / observation_hours
            item["start_count"] = round(starts)
            item["start_observation_hours"] = (
                round(observation_hours, 3)
            )
            item["starts_per_hour"] = round(starts_per_hour, 3)
            findings.append(
                f"{compressor.device_name}: 有效观测 {observation_hours:.2f} h 内启动约 "
                f"{round(starts)} 次（{starts_per_hour:.3f} 次/h）"
            )
            if starts_per_hour >= settings.compressor_frequent_starts_per_hour:
                warnings.append(
                    {
                        "severity": "high",
                        "code": "FREQUENT_STARTS",
                        "device_id": compressor.device_id,
                        "device_name": compressor.device_name,
                        "message": f"启动频率 {starts_per_hour:.3f} 次/h 超过配置阈值",
                        "evidence": {
                            "start_count": round(starts),
                            "observation_hours": round(observation_hours, 3),
                        },
                    }
                )
        elif "frequent_start" in capabilities:
            missing.append(f"{compressor.device_name}: air_comp_start_count 历史")
    metrics["devices"] = device_metrics


def _numeric_latest(device: AirSystemDevice, key: str) -> float | None:
    value = device.latest.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _analyze_realtime_status(
    context: CompressorSystemContext,
    metrics: dict[str, Any],
    findings: list[str],
    missing: list[str],
) -> None:
    realtime: dict[str, dict[str, Any]] = {}
    for compressor in context.compressors:
        if context.requested_device_scope and compressor.device_id not in context.requested_device_scope:
            continue
        running_value = _numeric_latest(compressor, "air_comp_running_flag")
        loaded_value = _numeric_latest(compressor, "air_comp_loaded_flag")
        pressure = _numeric_latest(compressor, "air_comp_supply_pressure")
        temperature = _numeric_latest(compressor, "air_comp_discharge_temp")
        meter = _linked_meter(context, compressor)
        power = _numeric_latest(meter, "meter_TotW") if meter else None
        timestamp_values = [
            compressor.latest_timestamps.get(key)
            for key in (
                "air_comp_running_flag",
                "air_comp_loaded_flag",
                "air_comp_supply_pressure",
                "air_comp_discharge_temp",
            )
            if compressor.latest_timestamps.get(key) is not None
        ]
        item = {
            "device_name": compressor.device_name,
            "running": running_value >= 0.5 if running_value is not None else None,
            "loaded": loaded_value >= 0.5 if loaded_value is not None else None,
            "supply_pressure_mpa": pressure,
            "discharge_temperature_c": temperature,
            "linked_power_kw": power,
            "active_alarm_count": len(compressor.alarms),
            "data_timestamp": max(timestamp_values) if timestamp_values else None,
        }
        realtime[compressor.device_id] = item
        state = "运行" if item["running"] else "停机" if item["running"] is False else "未知"
        load_state = "加载" if item["loaded"] else "卸载" if item["loaded"] is False else "未知"
        findings.append(f"{compressor.device_name} 当前状态：{state}/{load_state}")
        if running_value is None:
            missing.append(f"{compressor.device_name}:air_comp_running_flag")
    metrics["realtime"] = realtime


def _analyze_energy_consumption(
    context: CompressorSystemContext,
    metrics: dict[str, Any],
    findings: list[str],
    missing: list[str],
) -> None:
    meters = context.meters
    if len(meters) != 1:
        missing.append("空压系统需要唯一关联电表才能计算周期用电量")
        return
    meter = meters[0]
    points = _points(meter, "meter_SupWh")
    if len(points) < 2:
        missing.append(f"{meter.device_name}:meter_SupWh 至少需要两个累计读数")
        return
    start_value = points[0].value
    end_value = points[-1].value
    if end_value < start_value:
        missing.append(f"{meter.device_name}:meter_SupWh 周期内发生复位或倒退")
        return
    consumption = end_value - start_value
    metrics["energy"] = {
        "meter_name": meter.device_name,
        "start_reading_kwh": round(start_value, 3),
        "end_reading_kwh": round(end_value, 3),
        "consumption_kwh": round(consumption, 3),
        "calculation_method": "cumulative-register-delta",
    }
    findings.append(f"空压系统统计周期用电量 {consumption:.2f} kWh")


def _analyze_pressure(
    context: CompressorSystemContext,
    settings: Settings,
    metrics: dict[str, Any],
    findings: list[str],
    warnings: list[dict[str, Any]],
    missing: list[str],
    capabilities: list[str],
) -> None:
    pressure_metrics: dict[str, Any] = {}
    interval_ms = context.interval_seconds * 1000
    for compressor in context.compressors:
        key = (
            "air_system_header_pressure_mpa"
            if _points(compressor, "air_system_header_pressure_mpa")
            else "air_comp_supply_pressure"
        )
        pressure = _points(compressor, key)
        running = _points(compressor, "air_comp_running_flag")
        if running:
            active_values = [
                value
                for _, value, running_flag in _aligned(pressure, running, interval_ms)
                if running_flag >= 0.9
            ]
        else:
            active_values = [point.value for point in pressure if point.value > 0.1]
        if not active_values:
            missing.append(f"{compressor.device_name}: 运行期间压力历史")
            continue
        p5 = _percentile(active_values, 0.05) or 0
        p95 = _percentile(active_values, 0.95) or 0
        fluctuation = p95 - p5
        high_samples = sum(value > settings.compressor_max_pressure_mpa for value in active_values)
        high_minutes = high_samples * context.interval_seconds / 60
        result = {
            "signal": key,
            "avg_mpa": round(fmean(active_values), 4),
            "min_mpa": round(min(active_values), 4),
            "max_mpa": round(max(active_values), 4),
            "p5_mpa": round(p5, 4),
            "p95_mpa": round(p95, 4),
            "p95_p5_mpa": round(fluctuation, 4),
            "stddev_mpa": round(pstdev(active_values), 4),
            "high_pressure_minutes": round(high_minutes, 2),
        }
        pressure_metrics[compressor.device_id] = result
        if "pressure_fluctuation" in capabilities:
            findings.append(
                f"{compressor.device_name}: 运行压力均值 {result['avg_mpa']:.3f} MPa，"
                f"P95-P5 波动 {fluctuation:.3f} MPa"
            )
        if (
            "pressure_fluctuation" in capabilities
            and fluctuation >= settings.compressor_pressure_fluctuation_warning_mpa
        ):
            warnings.append(
                {
                    "severity": "medium",
                    "code": "PRESSURE_FLUCTUATION",
                    "device_id": compressor.device_id,
                    "device_name": compressor.device_name,
                    "message": f"压力 P95-P5 波动 {fluctuation:.3f} MPa",
                    "evidence": result,
                }
            )
        if "high_pressure" in capabilities:
            findings.append(
                f"{compressor.device_name}: 运行压力最大值 {result['max_mpa']:.3f} MPa，"
                f"高于阈值累计约 {high_minutes:.2f} min"
            )
        if "high_pressure" in capabilities and high_minutes > 0:
            warnings.append(
                {
                    "severity": "medium",
                    "code": "HIGH_SUPPLY_PRESSURE",
                    "device_id": compressor.device_id,
                    "device_name": compressor.device_name,
                    "message": f"压力高于 {settings.compressor_max_pressure_mpa:.3f} MPa 约 {high_minutes:.2f} min",
                    "evidence": result,
                }
            )
    metrics["pressure"] = pressure_metrics


def _system_flow_by_bucket(context: CompressorSystemContext) -> dict[int, float]:
    interval_ms = context.interval_seconds * 1000
    flow_by_bucket: dict[int, float] = defaultdict(float)
    for compressor in context.compressors:
        for point in _points(compressor, "air_comp_fad_flow_m3_min"):
            flow_by_bucket[round(point.ts / interval_ms)] += max(0, point.value)
    return dict(flow_by_bucket)


def _analyze_specific_power(
    context: CompressorSystemContext,
    metrics: dict[str, Any],
    findings: list[str],
    missing: list[str],
) -> None:
    if not context.compressors:
        return
    meter = _linked_meter(context, context.compressors[0])
    if meter is None:
        missing.append("空压系统关联电表")
        return
    power = _points(meter, "meter_TotW")
    flow_by_bucket = _system_flow_by_bucket(context)
    interval_ms = context.interval_seconds * 1000
    ratios: list[float] = []
    total_power = 0.0
    total_flow = 0.0
    pairs = 0
    for point in power:
        flow = flow_by_bucket.get(round(point.ts / interval_ms))
        if flow is None or flow <= 0.5 or point.value < 0:
            continue
        ratios.append(point.value / flow)
        total_power += point.value
        total_flow += flow
        pairs += 1
    if not ratios or total_flow <= 0:
        missing.append("关联电表 meter_TotW 与产气流量 air_comp_fad_flow_m3_min 的重叠历史")
        return
    result = {
        "average_kw_per_m3_min": round(total_power / total_flow, 4),
        "p95_kw_per_m3_min": round(_percentile(ratios, 0.95) or 0, 4),
        "sample_pairs": pairs,
        "average_power_kw": round(total_power / pairs, 3),
        "average_flow_m3_min": round(total_flow / pairs, 3),
    }
    metrics["specific_power"] = result
    findings.append(
        f"空压系统比功率 {result['average_kw_per_m3_min']:.3f} kW/(m³/min)，基于 {pairs} 组功率/流量对齐样本"
    )


def _analyze_leakage(
    context: CompressorSystemContext,
    settings: Settings,
    metrics: dict[str, Any],
    findings: list[str],
    missing: list[str],
) -> None:
    flow_by_bucket = _system_flow_by_bucket(context)
    if not flow_by_bucket:
        missing.append("夜间泄漏分析需要 air_comp_fad_flow_m3_min 历史")
        return
    timezone = ZoneInfo(settings.daily_summary_timezone)
    interval_ms = context.interval_seconds * 1000
    production: list[float] = []
    off_hours: list[float] = []
    for bucket, flow in flow_by_bucket.items():
        timestamp = bucket * interval_ms / 1000
        local_hour = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(timezone).hour
        if settings.compressor_production_start_hour <= local_hour < settings.compressor_production_end_hour:
            production.append(flow)
        else:
            off_hours.append(flow)
    if not off_hours:
        missing.append("分析窗口不包含配置的非生产时段")
        return
    off_average = fmean(off_hours)
    production_average = fmean(production) if production else None
    result: dict[str, Any] = {
        "nonproduction_average_flow_m3_min": round(off_average, 3),
        "nonproduction_samples": len(off_hours),
        "method": "configured-schedule-screening",
    }
    if production_average and production_average > 0:
        result["production_average_flow_m3_min"] = round(production_average, 3)
        result["screening_leakage_rate_pct"] = round(off_average / production_average * 100, 2)
    metrics["leakage_screening"] = result
    findings.append(
        f"非生产时段平均供气流量 {off_average:.3f} m³/min；该结果仅用于泄漏初筛，需扣除合法基础用气"
    )


def _analyze_group_control(
    context: CompressorSystemContext,
    metrics: dict[str, Any],
    recommendations: list[dict[str, Any]],
    missing: list[str],
) -> None:
    if len(context.compressors) < 2:
        missing.append("多机群控至少需要两台属于同一 airSystemId 的空压机")
        return
    device_loads = metrics.get("devices", {})
    ranked = sorted(
        (
            {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "load_rate_pct": device_loads.get(device.device_id, {}).get("load_rate_pct"),
            }
            for device in context.compressors
        ),
        key=lambda item: item["load_rate_pct"] if item["load_rate_pct"] is not None else -1,
        reverse=True,
    )
    metrics["group_control"] = {"compressor_count": len(context.compressors), "load_order": ranked}
    recommendations.append(
        {
            "code": "GROUP_CONTROL_REVIEW",
            "message": "建议优先让高加载率机组承担基础负荷，并保留一台变频机组调节管网压力；执行前必须建立待审批计划。",
            "evidence": {"load_order": ranked},
        }
    )


def _estimate_savings(
    context: CompressorSystemContext,
    settings: Settings,
    metrics: dict[str, Any],
    findings: list[str],
    missing: list[str],
) -> None:
    if len(context.compressors) != 1:
        missing.append("卸载节能量初筛当前要求单台空压机与独立关联电表")
        return
    compressor = context.compressors[0]
    meter = _linked_meter(context, compressor)
    if meter is None:
        missing.append("节能量估算需要独立关联电表")
        return
    unloaded = _points(compressor, "air_comp_unloaded_running_flag")
    power = _points(meter, "meter_TotW")
    interval_ms = context.interval_seconds * 1000
    aligned = _aligned(power, unloaded, interval_ms)
    if not aligned:
        missing.append("节能量估算需要卸载状态与功率的对齐历史")
        return
    unload_energy = sum(
        power_kw * max(0, min(1, unload_flag)) * context.interval_seconds / 3600
        for _, power_kw, unload_flag in aligned
    )
    saving = unload_energy * settings.compressor_unload_savings_factor
    result = {
        "screening_savings_kwh": round(saving, 3),
        "unloaded_energy_kwh": round(unload_energy, 3),
        "assumed_reducible_fraction": settings.compressor_unload_savings_factor,
        "method": "unloaded-energy-screening",
    }
    metrics["savings_screening"] = result
    findings.append(
        f"按卸载能耗初筛，可优化电量约 {saving:.3f} kWh；这是筛查值，不替代基线测量与验证"
    )


class CompressorAnalysisService:
    def __init__(
        self,
        context_builder: CompressorContextBuilder | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.context_builder = context_builder or CompressorContextBuilder(settings=self.settings)

    def analyze_load_unload_rate(
        self,
        payload: LoadUnloadRateToolInput,
    ) -> LoadUnloadRateToolResult:
        request = CompressorAnalysisRequest(
            message="分析单机加载率和卸载率",
            device_scope=payload.device_scope,
            start_at=payload.start_at,
            end_at=payload.end_at,
            interval_seconds=payload.interval_seconds,
            capabilities=["load_rate"],
        )
        context = self.context_builder.build(request)
        return analyze_load_unload_rate_context(context, self.settings)

    def analyze_capability(
        self,
        payload: LoadUnloadRateToolInput,
        capability: CompressorCapability,
        message: str,
    ) -> CompressorAnalysisResult:
        return self.analyze(
            CompressorAnalysisRequest(
                message=message,
                device_scope=payload.device_scope,
                start_at=payload.start_at,
                end_at=payload.end_at,
                interval_seconds=payload.interval_seconds,
                capabilities=[capability],
            )
        )

    def analyze_context(
        self,
        context: CompressorSystemContext,
        capabilities: list[CompressorCapability],
        query: str | None = None,
    ) -> CompressorAnalysisResult:
        metrics: dict[str, Any] = {}
        findings: list[str] = []
        warnings: list[dict[str, Any]] = []
        missing: list[str] = []
        recommendations: list[dict[str, Any]] = []

        if "realtime_status" in capabilities:
            _analyze_realtime_status(context, metrics, findings, missing)
        if "energy_consumption" in capabilities:
            _analyze_energy_consumption(context, metrics, findings, missing)
        if any(capability in capabilities for capability in ("load_rate", "idle_running", "frequent_start")):
            _analyze_operation(
                context,
                self.settings,
                metrics,
                findings,
                warnings,
                missing,
                capabilities,
            )
        if any(capability in capabilities for capability in ("pressure_fluctuation", "high_pressure")):
            _analyze_pressure(
                context,
                self.settings,
                metrics,
                findings,
                warnings,
                missing,
                capabilities,
            )
        if "specific_power" in capabilities:
            _analyze_specific_power(context, metrics, findings, missing)
        if "leakage" in capabilities:
            _analyze_leakage(context, self.settings, metrics, findings, missing)
        if "group_control" in capabilities:
            _analyze_group_control(context, metrics, recommendations, missing)
        if "savings" in capabilities:
            _estimate_savings(context, self.settings, metrics, findings, missing)
        if "verification" in capabilities:
            missing.append("优化前后效果验证需要 baseline_id、措施生效时间和独立验证周期")

        missing.extend(context.data_quality.missing_keys)
        confidence = context.data_quality.coverage
        if context.data_quality.stale_keys:
            confidence *= 0.8
        if context.data_quality.invalid_keys:
            confidence *= 0.6
        data_status = "available"
        if not findings:
            data_status = "unavailable"
        elif missing or confidence < self.settings.compressor_min_data_coverage:
            data_status = "partial"
        assumptions = [
            "状态、压力、功率和流量按统一历史时间桶进行确定性计算",
            "非生产时段按配置班次进行泄漏初筛，未扣除合法基础用气",
        ]
        return CompressorAnalysisResult(
            query=query,
            data_status=data_status,
            capabilities=capabilities,
            context={
                "schema_version": context.schema_version,
                "air_system_id": context.air_system_id,
                "start_ts": context.start_ts,
                "end_ts": context.end_ts,
                "interval_seconds": context.interval_seconds,
                "devices": [
                    {
                        "device_id": device.device_id,
                        "device_name": device.device_name,
                        "device_type": device.device_type,
                        "model": device.attributes.get("dev_model"),
                    }
                    for device in context.devices
                ],
                "data_quality": context.data_quality.model_dump(),
            },
            metrics=metrics,
            findings=findings,
            warnings=warnings,
            missing_metrics=list(dict.fromkeys(missing)),
            recommendations=recommendations,
            assumptions=assumptions,
            confidence=round(max(0, min(1, confidence)), 3),
        )

    def analyze(self, request: CompressorAnalysisRequest) -> CompressorAnalysisResult:
        capabilities = infer_capabilities(request.message, request.capabilities)
        request.capabilities = capabilities
        context = self.context_builder.build(request)
        return self.analyze_context(context, capabilities, request.message)


def merge_compressor_analysis_results(
    results: list[CompressorAnalysisResult],
    query: str,
) -> CompressorAnalysisResult:
    if not results:
        return CompressorAnalysisResult(
            query=query,
            data_status="unavailable",
            capabilities=[],
            missing_metrics=["未取得任何空压机工具结果"],
        )

    capabilities = list(
        dict.fromkeys(
            capability
            for result in results
            for capability in result.capabilities
        )
    )
    metrics: dict[str, Any] = {}
    device_metrics: dict[str, dict[str, Any]] = {}
    for result in results:
        dumped_metrics = result.metrics.model_dump(mode="json", exclude_none=True)
        for metric_name, metric_value in dumped_metrics.items():
            if metric_name == "devices":
                for device_id, device_value in metric_value.items():
                    device_metrics.setdefault(device_id, {}).update(device_value)
            else:
                metrics[metric_name] = metric_value
    if device_metrics:
        metrics["devices"] = device_metrics

    warnings_by_key = {}
    for result in results:
        for warning in result.warnings:
            key = (
                warning.code,
                warning.device_id,
                warning.message,
            )
            warnings_by_key[key] = warning
    recommendations_by_key = {}
    for result in results:
        for recommendation in result.recommendations:
            recommendations_by_key[recommendation.code] = recommendation

    statuses = {result.data_status for result in results}
    if statuses == {"no_scope"}:
        data_status = "no_scope"
    elif statuses <= {"unavailable"}:
        data_status = "unavailable"
    elif "partial" in statuses or "unavailable" in statuses:
        data_status = "partial"
    else:
        data_status = "available"

    return CompressorAnalysisResult(
        query=query,
        data_status=data_status,
        capabilities=capabilities,
        context=next((result.context for result in results if result.context is not None), None),
        metrics=metrics,
        findings=list(
            dict.fromkeys(
                finding
                for result in results
                for finding in result.findings
            )
        ),
        warnings=list(warnings_by_key.values()),
        missing_metrics=list(
            dict.fromkeys(
                metric
                for result in results
                for metric in result.missing_metrics
            )
        ),
        recommendations=list(recommendations_by_key.values()),
        assumptions=list(
            dict.fromkeys(
                assumption
                for result in results
                for assumption in result.assumptions
            )
        ),
        confidence=min(result.confidence for result in results),
    )


def analyze_compressor_query(
    message: str,
    device_scope: list[str],
    *,
    service: CompressorAnalysisService | None = None,
) -> CompressorAnalysisResult:
    if not device_scope:
        return CompressorAnalysisResult(
            data_status="no_scope",
            capabilities=infer_capabilities(message),
            context=None,
            missing_metrics=["请选择至少一台空压机设备"],
        )
    settings = get_settings()
    end_at = datetime.now(UTC)
    request = CompressorAnalysisRequest(
        message=message,
        device_scope=device_scope,
        start_at=end_at - timedelta(hours=settings.compressor_analysis_window_hours),
        end_at=end_at,
        interval_seconds=settings.compressor_history_interval_seconds,
    )
    try:
        return (service or CompressorAnalysisService(settings=settings)).analyze(request)
    except CompressorContextError as exc:
        return CompressorAnalysisResult(
            data_status="unavailable",
            capabilities=infer_capabilities(message),
            context=None,
            warnings=[{"severity": "high", "code": "CONTEXT_ERROR", "message": str(exc)}],
            missing_metrics=[str(exc)],
        )
