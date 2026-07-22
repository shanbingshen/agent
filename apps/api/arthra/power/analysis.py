from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from statistics import fmean

from arthra.config import Settings, get_settings
from arthra.contracts import AnalysisWarning, Recommendation
from arthra.power.capabilities import infer_power_capabilities
from arthra.power.context import PowerContextBuilder, PowerContextError
from arthra.power.schemas import (
    AbnormalDurationMetric,
    DemandMetrics,
    EnergyPeriodMetrics,
    HarmonicOrderMetrics,
    LoadPeakEvent,
    PowerAnalysisRequest,
    PowerAnalysisResult,
    PowerCapability,
    PowerContextMeterSummary,
    PowerContextSummary,
    PowerMeterContext,
    PowerMetrics,
    PowerQualityMetrics,
    PowerSignalPoint,
    PowerSystemContext,
    RealtimePowerMetrics,
    ScalarQualityMetrics,
    VoltagePhaseMetrics,
)


def _points(meter: PowerMeterContext, key: str) -> list[PowerSignalPoint]:
    series = meter.signals.get(key)
    return series.points if series else []


def _realtime_power_metrics(meter: PowerMeterContext) -> RealtimePowerMetrics | None:
    value = meter.latest.get("meter_TotW")
    timestamp = meter.latest_timestamps.get("meter_TotW")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or timestamp is None:
        points = _points(meter, "meter_TotW")
        if not points:
            return None
        return RealtimePowerMetrics(
            active_power_kw=round(max(0, points[-1].value), 3),
            timestamp=points[-1].ts,
        )
    return RealtimePowerMetrics(
        active_power_kw=round(max(0, float(value)), 3),
        timestamp=timestamp,
    )


def _register_delta(points: list[PowerSignalPoint]) -> tuple[float | None, float | None, float | None]:
    if len(points) < 2:
        return None, None, None
    start_value = points[0].value
    end_value = points[-1].value
    if end_value < start_value:
        return start_value, end_value, None
    return start_value, end_value, end_value - start_value


def _energy_period_metrics(
    meter: PowerMeterContext,
    capability: PowerCapability,
    start_ts: int,
    end_ts: int,
) -> EnergyPeriodMetrics | None:
    points = _points(meter, "meter_SupWh")
    if len(points) < 2:
        return None
    if capability == "energy_compare":
        split_ts = start_ts + (end_ts - start_ts) // 2
        previous = [point for point in points if point.ts < split_ts]
        current = [point for point in points if point.ts >= split_ts]
        current_start, current_end, current_delta = _register_delta(current)
        _, _, previous_delta = _register_delta(previous)
        if current_delta is None or previous_delta is None:
            return None
        change = current_delta - previous_delta
        change_pct = change / previous_delta * 100 if previous_delta > 0 else None
        return EnergyPeriodMetrics(
            period_start_ts=split_ts,
            period_end_ts=end_ts,
            start_reading_kwh=round(current_start, 3) if current_start is not None else None,
            end_reading_kwh=round(current_end, 3) if current_end is not None else None,
            consumption_kwh=round(current_delta, 3),
            previous_consumption_kwh=round(previous_delta, 3),
            change_kwh=round(change, 3),
            change_pct=round(change_pct, 2) if change_pct is not None else None,
        )
    start_value, end_value, delta = _register_delta(points)
    if delta is None:
        return None
    return EnergyPeriodMetrics(
        period_start_ts=start_ts,
        period_end_ts=end_ts,
        start_reading_kwh=round(start_value, 3) if start_value is not None else None,
        end_reading_kwh=round(end_value, 3) if end_value is not None else None,
        consumption_kwh=round(delta, 3),
    )


def _duration(
    points: Iterable[PowerSignalPoint],
    predicate: Callable[[float], bool],
    interval_seconds: int,
) -> tuple[float, float, int]:
    total_seconds = 0
    longest_seconds = 0
    current_seconds = 0
    previous_ts: int | None = None
    count = 0
    for point in points:
        if previous_ts is not None and point.ts - previous_ts > interval_seconds * 1_500:
            current_seconds = 0
        if predicate(point.value):
            count += 1
            total_seconds += interval_seconds
            current_seconds += interval_seconds
            longest_seconds = max(longest_seconds, current_seconds)
        else:
            current_seconds = 0
        previous_ts = point.ts
    return round(total_seconds / 60, 2), round(longest_seconds / 60, 2), count


def _rolling_15m(points: list[PowerSignalPoint], interval_seconds: int) -> list[PowerSignalPoint]:
    if not points:
        return []
    window_ms = 15 * 60 * 1000
    expected_samples = max(1, (15 * 60 + interval_seconds - 1) // interval_seconds)
    minimum_samples = max(1, int(expected_samples * 0.8 + 0.999))
    minimum_span_ms = max(0, window_ms - interval_seconds * 1000) * 0.8
    bucket: deque[PowerSignalPoint] = deque()
    total = 0.0
    result: list[PowerSignalPoint] = []
    for point in points:
        bucket.append(point)
        total += point.value
        while bucket and bucket[0].ts < point.ts - window_ms + interval_seconds * 1000:
            total -= bucket.popleft().value
        span = point.ts - bucket[0].ts if bucket else 0
        if len(bucket) >= minimum_samples and span >= minimum_span_ms:
            result.append(PowerSignalPoint(ts=point.ts, value=total / len(bucket)))
    return result


def _top_peaks(points: list[PowerSignalPoint], kind: str, count: int = 5) -> list[LoadPeakEvent]:
    if not points:
        return []
    candidates = [
        point
        for index, point in enumerate(points)
        if (index == 0 or point.value >= points[index - 1].value)
        and (index == len(points) - 1 or point.value > points[index + 1].value)
    ]
    selected: list[PowerSignalPoint] = []
    for candidate in sorted(candidates or points, key=lambda point: point.value, reverse=True):
        if all(abs(candidate.ts - item.ts) >= 15 * 60 * 1000 for item in selected):
            selected.append(candidate)
        if len(selected) == count:
            break
    return [
        LoadPeakEvent(ts=point.ts, load_kw=round(point.value, 3), kind=kind)
        for point in sorted(selected, key=lambda point: point.ts)
    ]


def _demand_metrics(
    meter: PowerMeterContext,
    capability: PowerCapability,
    interval_seconds: int,
) -> tuple[DemandMetrics, list[str], list[AnalysisWarning]]:
    points = _points(meter, "meter_TotW")
    if not points:
        return DemandMetrics(declared_demand_kw=meter.declared_demand_kw), ["meter_TotW"], []
    rolling = _rolling_15m(points, interval_seconds)
    average_load = fmean(point.value for point in points)
    instantaneous = max(points, key=lambda point: point.value)
    maximum = max(rolling, key=lambda point: point.value) if rolling else None
    metrics = DemandMetrics(
        sample_count=len(points),
        observation_hours=round(len(points) * interval_seconds / 3600, 3),
        average_load_kw=round(average_load, 3),
        rolling_sample_count=len(rolling),
        max_demand_15m_kw=round(maximum.value, 3) if maximum else None,
        max_demand_window_start_ts=maximum.ts - 15 * 60 * 1000 if maximum else None,
        max_demand_window_end_ts=maximum.ts if maximum else None,
        instantaneous_peak_kw=round(instantaneous.value, 3),
        instantaneous_peak_ts=instantaneous.ts,
        peak_average_ratio=round(instantaneous.value / average_load, 4) if average_load > 0 else None,
        declared_demand_kw=meter.declared_demand_kw,
    )
    if capability == "peak_detection":
        metrics.peaks = _top_peaks(points, "instantaneous")
    elif capability == "demand_15m":
        metrics.peaks = _top_peaks(rolling, "rolling_15m")

    warnings: list[AnalysisWarning] = []
    if capability == "declared_demand_exceedance" and maximum:
        exceedance = max(0.0, maximum.value - meter.declared_demand_kw)
        total, longest, _ = _duration(
            rolling,
            lambda value: value > meter.declared_demand_kw,
            interval_seconds,
        )
        metrics.exceedance_kw = round(exceedance, 3)
        metrics.exceedance_pct = round(exceedance / meter.declared_demand_kw * 100, 3)
        metrics.exceedance_total_minutes = total
        metrics.exceedance_longest_minutes = longest
        if exceedance > 0:
            warnings.append(
                AnalysisWarning(
                    severity="high",
                    code="DECLARED_DEMAND_EXCEEDED",
                    metric="max_demand_15m_kw",
                    value=round(maximum.value, 3),
                    device_id=meter.device_id,
                    device_name=meter.device_name,
                    message=(
                        f"15分钟最大需量 {maximum.value:.2f} kW 超过申报需量 "
                        f"{meter.declared_demand_kw:.2f} kW"
                    ),
                    evidence={
                        "declared_demand_kw": meter.declared_demand_kw,
                        "exceedance_kw": round(exceedance, 3),
                        "window_end_ts": maximum.ts,
                    },
                )
            )
    return metrics, [] if rolling or capability not in {"demand_15m", "declared_demand_exceedance"} else ["完整15分钟窗口"], warnings


def _scalar(
    points: list[PowerSignalPoint],
    threshold: float,
    predicate: Callable[[float], bool],
    interval_seconds: int,
) -> ScalarQualityMetrics | None:
    if not points:
        return None
    total, longest, _ = _duration(points, predicate, interval_seconds)
    values = [point.value for point in points]
    return ScalarQualityMetrics(
        average=round(fmean(values), 4),
        latest=round(values[-1], 4),
        min=round(min(values), 4),
        max=round(max(values), 4),
        threshold=threshold,
        abnormal_total_minutes=total,
        abnormal_longest_minutes=longest,
    )


def _warning(
    meter: PowerMeterContext,
    code: str,
    metric: str,
    value: float,
    message: str,
) -> AnalysisWarning:
    return AnalysisWarning(
        severity="medium",
        code=code,
        metric=metric,
        value=round(value, 4),
        device_id=meter.device_id,
        device_name=meter.device_name,
        message=message,
    )


def _quality_metrics(
    meter: PowerMeterContext,
    capability: PowerCapability,
    interval_seconds: int,
    settings: Settings,
) -> tuple[PowerQualityMetrics, list[str], list[AnalysisWarning]]:
    result = PowerQualityMetrics()
    missing: list[str] = []
    warnings: list[AnalysisWarning] = []
    run_all = capability == "abnormal_duration"

    if capability == "voltage_deviation" or run_all:
        for phase in ("AB", "BC", "CA"):
            key = f"meter_LinV_phs{phase}"
            points = _points(meter, key)
            if not points:
                missing.append(key)
                continue
            deviations = [abs(point.value - settings.power_nominal_voltage_v) / settings.power_nominal_voltage_v * 100 for point in points]
            total, longest, count = _duration(
                points,
                lambda value: abs(value - settings.power_nominal_voltage_v) / settings.power_nominal_voltage_v * 100 > settings.power_voltage_deviation_pct,
                interval_seconds,
            )
            result.voltage_deviation[phase] = VoltagePhaseMetrics(
                phase=phase,
                average_v=round(fmean(point.value for point in points), 3),
                latest_v=round(points[-1].value, 3),
                max_abs_deviation_pct=round(max(deviations), 3),
                abnormal_total_minutes=total,
                abnormal_longest_minutes=longest,
            )
            result.abnormal_durations.append(
                AbnormalDurationMetric(
                    code=f"VOLTAGE_DEVIATION_{phase}",
                    label=f"{phase}线电压偏差",
                    threshold=settings.power_voltage_deviation_pct,
                    unit="%",
                    total_minutes=total,
                    longest_minutes=longest,
                    abnormal_samples=count,
                )
            )
            if count:
                warnings.append(_warning(meter, f"VOLTAGE_DEVIATION_{phase}", key, max(deviations), f"{phase}线电压偏差超过 {settings.power_voltage_deviation_pct:.1f}%"))

    scalar_specs = []
    if capability == "phase_imbalance" or run_all:
        for phase in ("A", "B", "C"):
            current_points = _points(meter, f"meter_A_phs{phase}")
            if current_points:
                result.phase_currents_a[phase] = round(current_points[-1].value, 3)
            else:
                missing.append(f"meter_A_phs{phase}")
        scalar_specs.extend([
            ("voltage_unbalance", "meter_ImbNgV", settings.power_voltage_unbalance_pct, lambda value: value > settings.power_voltage_unbalance_pct, "VOLTAGE_UNBALANCE", "电压不平衡度"),
            ("current_unbalance", "meter_ImbNgA", settings.power_current_unbalance_pct, lambda value: value > settings.power_current_unbalance_pct, "CURRENT_UNBALANCE", "电流不平衡度"),
        ])
    if capability == "power_factor" or run_all:
        scalar_specs.append(("power_factor", "meter_TotPF", settings.power_factor_min, lambda value: abs(value) < settings.power_factor_min, "LOW_POWER_FACTOR", "功率因数"))
    for field, key, threshold, predicate, code, label in scalar_specs:
        points = _points(meter, key)
        metric = _scalar(points, threshold, predicate, interval_seconds)
        if metric is None:
            missing.append(key)
            continue
        setattr(result, field, metric)
        total, longest, count = _duration(points, predicate, interval_seconds)
        result.abnormal_durations.append(AbnormalDurationMetric(code=code, label=label, threshold=threshold, unit="" if key == "meter_TotPF" else "%", total_minutes=total, longest_minutes=longest, abnormal_samples=count))
        if count:
            extreme = metric.min if key == "meter_TotPF" else metric.max
            if code == "CURRENT_UNBALANCE":
                message = (
                    f"电流不平衡度触发平台内部预警阈值，疑似异常累计 {total:.1f} 分钟；"
                    "需核查缺相、CT接线与倍率、点位映射和采样同步后确认"
                )
            else:
                message = f"{label}触发平台内部预警阈值，异常累计 {total:.1f} 分钟"
            warnings.append(_warning(meter, code, key, extreme, message))

    if capability == "thd" or run_all:
        for kind, prefix, threshold, target in (
            ("THDu", "meter_ThdPhV_phs", settings.power_thdu_max_pct, result.thdu),
            ("THDi", "meter_ThdA_phs", settings.power_thdi_max_pct, result.thdi),
        ):
            for phase in ("A", "B", "C"):
                key = f"{prefix}{phase}"
                points = _points(meter, key)
                metric = _scalar(points, threshold, lambda value, limit=threshold: value > limit, interval_seconds)
                if metric is None:
                    missing.append(key)
                    continue
                target[phase] = metric
                total, longest, count = _duration(points, lambda value, limit=threshold: value > limit, interval_seconds)
                result.abnormal_durations.append(AbnormalDurationMetric(code=f"{kind.upper()}_{phase}", label=f"{kind} {phase}相", threshold=threshold, unit="%", total_minutes=total, longest_minutes=longest, abnormal_samples=count))
                if count:
                    standard_note = (
                        "是否构成标准超限需结合PCC测点、短路容量和负荷电流确认"
                        if kind == "THDi"
                        else "是否构成标准超限需结合测点和适用判据确认"
                    )
                    warnings.append(
                        _warning(
                            meter,
                            f"{kind.upper()}_{phase}",
                            key,
                            metric.max,
                            f"{kind} {phase}相触发平台内部预警阈值 {threshold:.1f}%；{standard_note}",
                        )
                    )

    if capability == "harmonics":
        voltage_scores: dict[int, float] = {}
        current_scores: dict[int, float] = {}
        for order in (3, 5, 7):
            voltage_values = [point.value for phase in ("A", "B", "C") for point in _points(meter, f"meter_ThdPhV{order}_phs{phase}")]
            current_values = [point.value for phase in ("A", "B", "C") for point in _points(meter, f"meter_ThdA{order}_phs{phase}")]
            if not voltage_values:
                missing.extend(f"meter_ThdPhV{order}_phs{phase}" for phase in ("A", "B", "C"))
            if not current_values:
                missing.extend(f"meter_ThdA{order}_phs{phase}" for phase in ("A", "B", "C"))
            voltage_scores[order] = fmean(voltage_values) if voltage_values else -1
            current_scores[order] = fmean(current_values) if current_values else -1
            result.harmonics.append(HarmonicOrderMetrics(
                order=order,
                voltage_average_pct=round(fmean(voltage_values), 4) if voltage_values else None,
                voltage_max_pct=round(max(voltage_values), 4) if voltage_values else None,
                current_average_pct=round(fmean(current_values), 4) if current_values else None,
                current_max_pct=round(max(current_values), 4) if current_values else None,
            ))
        if max(voltage_scores.values()) >= 0:
            result.dominant_voltage_harmonic_order = max(voltage_scores, key=voltage_scores.get)  # type: ignore[arg-type]
        if max(current_scores.values()) >= 0:
            result.dominant_current_harmonic_order = max(current_scores, key=current_scores.get)  # type: ignore[arg-type]
    return result, list(dict.fromkeys(missing)), warnings


class PowerAnalysisService:
    def __init__(self, context_builder: PowerContextBuilder | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.context_builder = context_builder or PowerContextBuilder(settings=self.settings)

    def analyze_context(
        self,
        context: PowerSystemContext,
        capabilities: list[PowerCapability],
        query: str,
    ) -> PowerAnalysisResult:
        realtime: dict[str, RealtimePowerMetrics] = {}
        energy: dict[str, EnergyPeriodMetrics] = {}
        demand: dict[str, DemandMetrics] = {}
        quality: dict[str, PowerQualityMetrics] = {}
        findings: list[str] = []
        warnings: list[AnalysisWarning] = []
        missing: list[str] = []
        for meter in context.meters:
            for capability in capabilities:
                if capability == "realtime_power":
                    metric = _realtime_power_metrics(meter)
                    if metric is None:
                        missing.append(f"{meter.device_name}:meter_TotW")
                    else:
                        realtime[meter.device_id] = metric
                elif capability in {"energy_consumption", "energy_compare"}:
                    metric = _energy_period_metrics(
                        meter,
                        capability,
                        context.start_ts,
                        context.end_ts,
                    )
                    if metric is None:
                        missing.append(f"{meter.device_name}:meter_SupWh")
                    else:
                        energy[meter.device_id] = metric
                elif capability in {"demand_15m", "peak_detection", "peak_average_ratio", "declared_demand_exceedance"}:
                    metric, absent, alerts = _demand_metrics(meter, capability, context.interval_seconds)
                    current = demand.get(meter.device_id)
                    if current:
                        merged = current.model_dump(mode="python")
                        incoming = metric.model_dump(mode="python", exclude_none=True)
                        if incoming.get("peaks"):
                            merged["peaks"] = incoming["peaks"]
                        merged.update({key: value for key, value in incoming.items() if key != "peaks"})
                        metric = DemandMetrics.model_validate(merged)
                    demand[meter.device_id] = metric
                    missing.extend(f"{meter.device_name}:{item}" for item in absent)
                    warnings.extend(alerts)
                else:
                    metric, absent, alerts = _quality_metrics(meter, capability, context.interval_seconds, self.settings)
                    current = quality.get(meter.device_id, PowerQualityMetrics())
                    merged = current.model_dump(mode="python")
                    incoming = metric.model_dump(mode="python", exclude_none=True)
                    for key, value in incoming.items():
                        if isinstance(value, dict):
                            existing = merged.get(key)
                            if not isinstance(existing, dict):
                                existing = {}
                                merged[key] = existing
                            existing.update(value)
                        elif isinstance(value, list):
                            if value:
                                merged.setdefault(key, []).extend(value)
                        else:
                            merged[key] = value
                    quality[meter.device_id] = PowerQualityMetrics.model_validate(merged)
                    missing.extend(f"{meter.device_name}:{item}" for item in absent)
                    warnings.extend(alerts)

        for meter in context.meters:
            realtime_metric = realtime.get(meter.device_id)
            if realtime_metric:
                findings.append(
                    f"{meter.device_name} 当前有功功率 {realtime_metric.active_power_kw:.2f} kW"
                )
            energy_metric = energy.get(meter.device_id)
            if energy_metric and energy_metric.consumption_kwh is not None:
                if energy_metric.previous_consumption_kwh is None:
                    findings.append(
                        f"{meter.device_name} 统计周期用电量 {energy_metric.consumption_kwh:.2f} kWh"
                    )
                else:
                    findings.append(
                        f"{meter.device_name} 本期用电量 {energy_metric.consumption_kwh:.2f} kWh，"
                        f"上期 {energy_metric.previous_consumption_kwh:.2f} kWh"
                    )
            metric = demand.get(meter.device_id)
            if metric and metric.max_demand_15m_kw is not None:
                findings.append(f"{meter.device_name} 15分钟最大需量 {metric.max_demand_15m_kw:.2f} kW，峰均比 {metric.peak_average_ratio:.3f}")
            qmetric = quality.get(meter.device_id)
            if qmetric:
                qmetric.abnormal_durations = list(
                    {
                        item.code: item
                        for item in qmetric.abnormal_durations
                    }.values()
                )
            if qmetric and qmetric.harmonics:
                findings.append(f"{meter.device_name} 主导电压/电流谐波次数为 {qmetric.dominant_voltage_harmonic_order}/{qmetric.dominant_current_harmonic_order} 次")

        warning_keys: set[tuple[str | None, str | None, str | None]] = set()
        unique_warnings: list[AnalysisWarning] = []
        for warning in warnings:
            key = (warning.code, warning.device_id, warning.metric)
            if key not in warning_keys:
                warning_keys.add(key)
                unique_warnings.append(warning)
        recommendations: list[Recommendation] = []
        if any(warning.code == "DECLARED_DEMAND_EXCEEDED" for warning in unique_warnings):
            recommendations.append(Recommendation(code="REVIEW_DECLARED_DEMAND", message="核查申报需量与负荷计划，并评估错峰或需量申报调整。"))
        if any(warning.code and ("THD" in warning.code or "UNBALANCE" in warning.code) for warning in unique_warnings):
            recommendations.append(Recommendation(code="TRACE_POWER_QUALITY_SOURCE", message="按异常时间窗定位谐波或不平衡负荷源，治理前先复核计量接线和采样质量。"))

        coverage = context.data_quality.coverage
        if not context.meters:
            status = "unavailable"
        elif coverage >= self.settings.power_min_data_coverage and not missing:
            status = "available"
        else:
            status = "partial"
        confidence = coverage
        if context.data_quality.stale_keys:
            confidence *= 0.9
        if context.data_quality.invalid_keys:
            confidence *= 0.9
        summary = PowerContextSummary(
            start_ts=context.start_ts,
            end_ts=context.end_ts,
            interval_seconds=context.interval_seconds,
            meters=[PowerContextMeterSummary(device_id=meter.device_id, device_name=meter.device_name, declared_demand_kw=meter.declared_demand_kw) for meter in context.meters],
            data_quality=context.data_quality,
        )
        return PowerAnalysisResult(
            data_status=status,
            query=query,
            capabilities=capabilities,
            context=summary,
            metrics=PowerMetrics(
                realtime=realtime,
                energy=energy,
                demand=demand,
                quality=quality,
            ),
            findings=findings,
            warnings=unique_warnings,
            missing_metrics=list(dict.fromkeys(missing)),
            recommendations=recommendations,
            assumptions=[
                "15分钟需量按 meter_TotW 时间序列的滚动算术平均计算。",
                "异常持续时间按聚合时间桶累计；数据断档不会被计为连续异常。",
            ],
            confidence=round(max(0, min(1, confidence)), 3),
        )

    def analyze_capability(self, payload, capability: PowerCapability, message: str) -> PowerAnalysisResult:
        request = PowerAnalysisRequest(
            message=message,
            device_scope=payload.device_scope,
            start_at=payload.start_at,
            end_at=payload.end_at,
            interval_seconds=payload.interval_seconds,
            declared_demand_kw=payload.declared_demand_kw,
            capabilities=[capability],
        )
        context = self.context_builder.build(request)
        return self.analyze_context(context, [capability], message)

    def analyze(self, request: PowerAnalysisRequest) -> PowerAnalysisResult:
        capabilities = infer_power_capabilities(request.message, request.capabilities)
        context = self.context_builder.build(request)
        return self.analyze_context(context, capabilities, request.message)


def merge_power_analysis_results(results: list[PowerAnalysisResult], query: str) -> PowerAnalysisResult:
    if not results:
        return PowerAnalysisResult(data_status="unavailable", capabilities=[], query=query, missing_metrics=["未取得任何电力工具结果"])
    capabilities = list(dict.fromkeys(capability for result in results for capability in result.capabilities))
    realtime: dict[str, RealtimePowerMetrics] = {}
    energy: dict[str, EnergyPeriodMetrics] = {}
    demand: dict[str, dict] = {}
    quality: dict[str, dict] = {}
    for result in results:
        realtime.update(result.metrics.realtime)
        energy.update(result.metrics.energy)
        for device_id, metric in result.metrics.demand.items():
            demand.setdefault(device_id, {}).update(metric.model_dump(mode="python", exclude_none=True))
        for device_id, metric in result.metrics.quality.items():
            target = quality.setdefault(device_id, {})
            incoming = metric.model_dump(mode="python", exclude_none=True)
            for key, value in incoming.items():
                if isinstance(value, dict):
                    existing = target.get(key)
                    if not isinstance(existing, dict):
                        existing = {}
                        target[key] = existing
                    existing.update(value)
                elif isinstance(value, list):
                    if value:
                        target.setdefault(key, []).extend(value)
                else:
                    target[key] = value
    warnings = {(warning.code, warning.device_id, warning.metric): warning for result in results for warning in result.warnings}
    recommendations = {item.code: item for result in results for item in result.recommendations}
    statuses = {result.data_status for result in results}
    status = "available" if statuses == {"available"} else "partial" if "available" in statuses or "partial" in statuses else "unavailable"
    return PowerAnalysisResult(
        data_status=status,
        query=query,
        capabilities=capabilities,
        context=next((result.context for result in results if result.context), None),
        metrics=PowerMetrics(
            realtime=realtime,
            energy=energy,
            demand={key: DemandMetrics.model_validate(value) for key, value in demand.items()},
            quality={key: PowerQualityMetrics.model_validate(value) for key, value in quality.items()},
        ),
        findings=list(dict.fromkeys(item for result in results for item in result.findings)),
        warnings=list(warnings.values()),
        missing_metrics=list(dict.fromkeys(item for result in results for item in result.missing_metrics)),
        recommendations=list(recommendations.values()),
        assumptions=list(dict.fromkeys(item for result in results for item in result.assumptions)),
        confidence=min(result.confidence for result in results),
    )


def analyze_power_query(message: str, device_scope: list[str], *, service: PowerAnalysisService | None = None) -> PowerAnalysisResult:
    if not device_scope:
        return PowerAnalysisResult(data_status="no_scope", capabilities=infer_power_capabilities(message), missing_metrics=["请选择至少一个电表设备"])
    settings = get_settings()
    end_at = datetime.now(UTC)
    request = PowerAnalysisRequest(
        message=message,
        device_scope=device_scope,
        start_at=end_at - timedelta(hours=settings.power_analysis_window_hours),
        end_at=end_at,
        interval_seconds=settings.power_history_interval_seconds,
    )
    try:
        return (service or PowerAnalysisService(settings=settings)).analyze(request)
    except PowerContextError as exc:
        return PowerAnalysisResult(data_status="unavailable", capabilities=infer_power_capabilities(message), warnings=[AnalysisWarning(severity="high", code="CONTEXT_ERROR", message=str(exc))], missing_metrics=[str(exc)])
