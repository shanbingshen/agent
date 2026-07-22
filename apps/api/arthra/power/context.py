import math
from datetime import UTC, datetime
from typing import Any

from arthra.config import Settings, get_settings
from arthra.industrial_data.schemas import (
    IndustrialDeviceCatalogItem,
    IndustrialTelemetrySample,
)
from arthra.power.capabilities import POWER_UNITS, infer_power_capabilities, power_keys
from arthra.power.repository import PowerRepository
from arthra.power.schemas import (
    PowerAnalysisRequest,
    PowerDataQuality,
    PowerMeterContext,
    PowerSignalPoint,
    PowerSignalSeries,
    PowerSystemContext,
)


class PowerContextError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series(
    key: str,
    raw_samples: list[IndustrialTelemetrySample],
) -> PowerSignalSeries:
    points: list[PowerSignalPoint] = []
    for raw_sample in raw_samples or []:
        sample = IndustrialTelemetrySample.model_validate(raw_sample)
        value = _number(sample.value)
        if value is not None:
            points.append(PowerSignalPoint(ts=sample.ts, value=value))
    points.sort(key=lambda point: point.ts)
    return PowerSignalSeries(key=key, unit=POWER_UNITS.get(key, "%" if "Thd" in key else ""), points=points)


def _invalid_value(key: str, value: float) -> bool:
    if key in {"meter_TotW", "meter_SupWh"} or key.startswith("meter_A_phs"):
        return value < 0
    if "LinV" in key:
        return not 100 <= value <= 1000
    if key == "meter_TotPF":
        return not -1 <= value <= 1
    if key.startswith("meter_Imb") or "Thd" in key:
        return not 0 <= value <= 100
    return False


class PowerContextBuilder:
    def __init__(self, repository: PowerRepository | None = None, settings: Settings | None = None):
        self.repository = repository or PowerRepository()
        self.settings = settings or get_settings()

    @staticmethod
    def _select(
        catalog: list[IndustrialDeviceCatalogItem],
        request: PowerAnalysisRequest,
    ) -> list[IndustrialDeviceCatalogItem]:
        requested_ids = set(request.device_scope)
        selected = [item for item in catalog if item.device_id in requested_ids]
        if request.device_scope and not selected:
            raise PowerContextError("所选设备范围中没有可访问的电表设备")
        if not request.device_scope:
            raise PowerContextError("请至少选择一个电表设备")
        return selected

    def build(self, request: PowerAnalysisRequest) -> PowerSystemContext:
        capabilities = infer_power_capabilities(request.message, request.capabilities)
        if request.start_at is None or request.end_at is None:
            raise PowerContextError("分析时间窗口无效")
        start_ts = int(request.start_at.astimezone(UTC).timestamp() * 1000)
        end_ts = int(request.end_at.astimezone(UTC).timestamp() * 1000)
        minimum_interval = math.ceil((end_ts - start_ts) / 1000 / 5_000)
        interval_seconds = min(900, max(request.interval_seconds, minimum_interval, 30))
        interval_ms = interval_seconds * 1000
        selected = self._select(self.repository.catalog(), request)
        keys = power_keys(capabilities)

        expected_series = len(keys) * len(selected)
        available_series = 0
        coverage_values: list[float] = []
        missing_keys: list[str] = []
        stale_keys: list[str] = []
        invalid_keys: list[str] = []
        expected_points = max(1, math.ceil((end_ts - start_ts) / interval_ms))
        stale_before = int(datetime.now(UTC).timestamp() * 1000) - max(interval_ms * 3, 120_000)
        meters: list[PowerMeterContext] = []

        for item in selected:
            latest, timestamps = self.repository.latest(item.device_id, keys)
            history = self.repository.history(item.device_id, keys, start_ts, end_ts, interval_ms)
            signals: dict[str, PowerSignalSeries] = {}
            for key in keys:
                series = _series(key, history.get(key, []))
                valid_points = [point for point in series.points if not _invalid_value(key, point.value)]
                if len(valid_points) != len(series.points):
                    invalid_keys.append(f"{item.device_name}:{key}")
                series.points = valid_points
                signals[key] = series
                if valid_points:
                    available_series += 1
                    coverage_values.append(min(1.0, len(valid_points) / expected_points))
                else:
                    missing_keys.append(f"{item.device_name}:{key}")
                if key in timestamps and timestamps[key] < stale_before:
                    stale_keys.append(f"{item.device_name}:{key}")

            declared = request.declared_demand_kw
            if declared is None:
                declared = _number(item.attributes.get("declaredDemandKw"))
            declared = declared or self.settings.power_declared_demand_kw
            meters.append(
                PowerMeterContext(
                    device_id=item.device_id,
                    device_name=item.device_name,
                    attributes=item.attributes,
                    latest=latest,
                    latest_timestamps=timestamps,
                    signals=signals,
                    declared_demand_kw=declared,
                )
            )

        coverage = sum(coverage_values) / expected_series if expected_series else 0.0
        quality_warnings: list[str] = []
        if coverage < self.settings.power_min_data_coverage:
            quality_warnings.append(
                f"历史数据覆盖率 {coverage:.1%} 低于 {self.settings.power_min_data_coverage:.0%} 要求"
            )
        if stale_keys:
            quality_warnings.append(f"{len(stale_keys)} 个最新指标已陈旧")
        if invalid_keys:
            quality_warnings.append(f"{len(invalid_keys)} 个序列包含无效值并已剔除")

        return PowerSystemContext(
            start_ts=start_ts,
            end_ts=end_ts,
            interval_seconds=interval_seconds,
            capabilities=capabilities,
            requested_device_scope=request.device_scope,
            meters=meters,
            data_quality=PowerDataQuality(
                coverage=round(coverage, 4),
                expected_series=expected_series,
                available_series=available_series,
                missing_keys=missing_keys,
                stale_keys=stale_keys,
                invalid_keys=invalid_keys,
                warnings=quality_warnings,
            ),
        )
