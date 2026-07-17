import math
from datetime import UTC, datetime
from typing import Any

from arthra.compressor.capabilities import UNITS, infer_capabilities, keys_for_device_type
from arthra.compressor.repository import CompressorRepository
from arthra.compressor.schemas import (
    AirSystemDevice,
    CompressorAnalysisRequest,
    CompressorSystemContext,
    DataQuality,
    SignalPoint,
    SignalSeries,
)
from arthra.config import Settings, get_settings
from arthra.thingsboard_schemas import DeviceCatalogItem, TelemetrySample


class CompressorContextError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series(key: str, raw_samples: list[TelemetrySample]) -> SignalSeries:
    points: list[SignalPoint] = []
    for raw_sample in raw_samples or []:
        sample = TelemetrySample.model_validate(raw_sample)
        value = _number(sample.value)
        if value is None:
            continue
        points.append(SignalPoint(ts=sample.ts, value=value))
    points.sort(key=lambda point: point.ts)
    return SignalSeries(key=key, unit=UNITS.get(key, ""), points=points)


def _invalid_signal_value(key: str, value: float) -> bool:
    if key.endswith("_flag") and not 0 <= value <= 1:
        return True
    if "pressure" in key and not 0 <= value <= 2:
        return True
    if key in {"meter_TotW", "air_comp_fad_flow_m3_min"} and value < 0:
        return True
    return False


class CompressorContextBuilder:
    def __init__(
        self,
        repository: CompressorRepository | None = None,
        settings: Settings | None = None,
    ):
        self.repository = repository or CompressorRepository()
        self.settings = settings or get_settings()

    def _select_catalog(
        self,
        catalog: list[DeviceCatalogItem],
        request: CompressorAnalysisRequest,
    ) -> tuple[str, list[DeviceCatalogItem]]:
        requested_ids = set(request.device_scope)
        requested = [item for item in catalog if item["device_id"] in requested_ids]
        if request.device_scope and not any(item["device_type"] == "compressor" for item in requested):
            raise CompressorContextError("所选设备范围中没有空压机")

        explicit_system = request.air_system_id
        selected_systems = {
            str(item["attributes"].get("airSystemId"))
            for item in requested
            if item["attributes"].get("airSystemId")
        }
        system_id = explicit_system or next(iter(selected_systems), self.settings.compressor_default_system_id)
        system_devices = [
            item
            for item in catalog
            if item["attributes"].get("airSystemId") == system_id
        ]
        if not system_devices:
            system_devices = requested or catalog

        compressors = [item for item in system_devices if item["device_type"] == "compressor"]
        if not compressors:
            raise CompressorContextError(f"空压系统 {system_id} 没有可访问的空压机")

        linked_meter_ids = {
            str(item["attributes"].get("linkedMeterDeviceId"))
            for item in compressors
            if item["attributes"].get("linkedMeterDeviceId")
        }
        selected = [
            item
            for item in system_devices
            if item["device_type"] == "compressor"
            or item["device_id"] in linked_meter_ids
        ]
        if not any(item["device_type"] == "meter" for item in selected):
            meters = [item for item in system_devices if item["device_type"] == "meter"]
            if len(meters) == 1:
                selected.append(meters[0])
        return system_id, selected

    def build(self, request: CompressorAnalysisRequest) -> CompressorSystemContext:
        capabilities = infer_capabilities(request.message, request.capabilities)
        start_at = request.start_at
        end_at = request.end_at
        if start_at is None or end_at is None:
            raise CompressorContextError("分析时间窗口无效")
        start_ts = int(start_at.astimezone(UTC).timestamp() * 1000)
        end_ts = int(end_at.astimezone(UTC).timestamp() * 1000)
        minimum_interval_seconds = math.ceil((end_ts - start_ts) / 1000 / 500)
        effective_interval_seconds = max(
            request.interval_seconds, minimum_interval_seconds
        )
        interval_ms = effective_interval_seconds * 1000
        system_id, selected = self._select_catalog(self.repository.catalog(), request)

        devices: list[AirSystemDevice] = []
        expected_series = 0
        available_series = 0
        coverage_values: list[float] = []
        missing_keys: list[str] = []
        stale_keys: list[str] = []
        invalid_keys: list[str] = []
        quality_warnings: list[str] = []
        expected_points = max(1, math.ceil((end_ts - start_ts) / interval_ms))
        stale_before = int(datetime.now(UTC).timestamp() * 1000) - max(interval_ms * 3, 120_000)

        for item in selected:
            keys = keys_for_device_type(capabilities, item["device_type"])
            expected_series += len(keys)
            latest, latest_timestamps = self.repository.latest(item["device_id"], keys)
            history = self.repository.history(
                item["device_id"], keys, start_ts, end_ts, interval_ms
            )
            signals: dict[str, SignalSeries] = {}
            for key in keys:
                signal = _series(key, history.get(key, []))
                signals[key] = signal
                if signal.points:
                    available_series += 1
                    coverage_values.append(min(1.0, len(signal.points) / expected_points))
                    if any(_invalid_signal_value(key, point.value) for point in signal.points):
                        invalid_keys.append(f"{item['device_name']}:{key}")
                else:
                    coverage_values.append(0.0)
                    missing_keys.append(f"{item['device_name']}:{key}")
                timestamp = latest_timestamps.get(key)
                if timestamp is not None and timestamp < stale_before:
                    stale_keys.append(f"{item['device_name']}:{key}")
            devices.append(
                AirSystemDevice(
                    device_id=item["device_id"],
                    device_name=item["device_name"],
                    device_type=item["device_type"],
                    attributes=item["attributes"],
                    latest=latest,
                    latest_timestamps=latest_timestamps,
                    signals=signals,
                    alarms=self.repository.alarms(item["device_id"]),
                )
            )

        coverage = sum(coverage_values) / len(coverage_values) if coverage_values else 0
        if coverage < self.settings.compressor_min_data_coverage:
            quality_warnings.append(
                f"历史数据覆盖率 {coverage:.1%} 低于要求 {self.settings.compressor_min_data_coverage:.0%}"
            )
        if stale_keys:
            quality_warnings.append("存在过期遥测，分析结论置信度已降低")
        quality = DataQuality(
            coverage=round(coverage, 4),
            expected_series=expected_series,
            available_series=available_series,
            missing_keys=missing_keys,
            stale_keys=stale_keys,
            invalid_keys=invalid_keys,
            warnings=quality_warnings,
        )
        return CompressorSystemContext(
            air_system_id=system_id,
            start_ts=start_ts,
            end_ts=end_ts,
            interval_seconds=effective_interval_seconds,
            capabilities=capabilities,
            requested_device_scope=request.device_scope,
            devices=devices,
            data_quality=quality,
        )
