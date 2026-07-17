from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from arthra.contracts import (
    AnalysisWarning,
    AttributeValues,
    Recommendation,
    StrictModel,
    TelemetryValues,
    TimestampValues,
)
from arthra.thingsboard_schemas import AlarmInfo

type CompressorCapability = Literal[
    "load_rate",
    "idle_running",
    "frequent_start",
    "pressure_fluctuation",
    "high_pressure",
    "specific_power",
    "group_control",
    "leakage",
    "savings",
    "verification",
]


class CompressorAnalysisRequest(StrictModel):
    message: str = "执行空压系统综合分析"
    air_system_id: str | None = None
    device_scope: list[str] = Field(default_factory=list, max_length=100)
    start_at: datetime | None = None
    end_at: datetime | None = None
    interval_seconds: int = Field(default=180, ge=30, le=3600)
    capabilities: list[CompressorCapability] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_window(self) -> "CompressorAnalysisRequest":
        end = self.end_at or datetime.now(UTC)
        start = self.start_at or end - timedelta(hours=24)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start_at 和 end_at 必须包含时区")
        if start >= end:
            raise ValueError("start_at 必须早于 end_at")
        if end - start > timedelta(days=31):
            raise ValueError("单次分析时间窗口不能超过31天")
        object.__setattr__(self, "start_at", start.astimezone(UTC))
        object.__setattr__(self, "end_at", end.astimezone(UTC))
        return self


class SignalPoint(StrictModel):
    ts: int = Field(ge=0)
    value: float


class SignalSeries(StrictModel):
    key: str
    unit: str = ""
    aggregation: Literal["AVG", "MIN", "MAX", "SUM", "COUNT", "NONE"] = "AVG"
    points: list[SignalPoint] = Field(default_factory=list)


class AirSystemDevice(StrictModel):
    device_id: str
    device_name: str
    device_type: str
    attributes: AttributeValues = Field(default_factory=lambda: AttributeValues({}))
    latest: TelemetryValues = Field(default_factory=lambda: TelemetryValues({}))
    latest_timestamps: TimestampValues = Field(default_factory=lambda: TimestampValues({}))
    signals: dict[str, SignalSeries] = Field(default_factory=dict)
    alarms: list[AlarmInfo] = Field(default_factory=list)


class DataQuality(StrictModel):
    coverage: float = Field(default=0, ge=0, le=1)
    expected_series: int = Field(default=0, ge=0)
    available_series: int = Field(default=0, ge=0)
    missing_keys: list[str] = Field(default_factory=list)
    stale_keys: list[str] = Field(default_factory=list)
    invalid_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompressorSystemContext(StrictModel):
    schema_version: str = "1.0"
    air_system_id: str
    start_ts: int = Field(ge=0)
    end_ts: int = Field(ge=0)
    interval_seconds: int = Field(ge=30, le=3600)
    capabilities: list[CompressorCapability]
    requested_device_scope: list[str]
    devices: list[AirSystemDevice]
    data_quality: DataQuality

    @property
    def compressors(self) -> list[AirSystemDevice]:
        return [device for device in self.devices if device.device_type == "compressor"]

    @property
    def meters(self) -> list[AirSystemDevice]:
        return [device for device in self.devices if device.device_type == "meter"]


class ContextDeviceSummary(StrictModel):
    device_id: str
    device_name: str
    device_type: str
    model: str | None = None


class CompressorContextSummary(StrictModel):
    schema_version: str = "1.0"
    air_system_id: str
    start_ts: int = Field(ge=0)
    end_ts: int = Field(ge=0)
    interval_seconds: int = Field(ge=30, le=3600)
    devices: list[ContextDeviceSummary]
    data_quality: DataQuality


class CompressorDeviceMetrics(StrictModel):
    device_name: str
    load_rate_pct: float | None = Field(default=None, ge=0, le=100)
    unload_rate_pct: float | None = Field(default=None, ge=0, le=100)
    idle_running_minutes: float | None = Field(default=None, ge=0)
    longest_idle_running_minutes: float | None = Field(default=None, ge=0)
    start_count: int | None = Field(default=None, ge=0)
    starts_per_hour: float | None = Field(default=None, ge=0)


class PressureMetrics(StrictModel):
    signal: str
    avg_mpa: float = Field(ge=0)
    min_mpa: float = Field(ge=0)
    max_mpa: float = Field(ge=0)
    p5_mpa: float = Field(ge=0)
    p95_mpa: float = Field(ge=0)
    p95_p5_mpa: float = Field(ge=0)
    stddev_mpa: float = Field(ge=0)
    high_pressure_minutes: float = Field(ge=0)


class SpecificPowerMetrics(StrictModel):
    average_kw_per_m3_min: float = Field(ge=0)
    p95_kw_per_m3_min: float = Field(ge=0)
    sample_pairs: int = Field(ge=1)
    average_power_kw: float = Field(ge=0)
    average_flow_m3_min: float = Field(gt=0)


class LeakageMetrics(StrictModel):
    nonproduction_average_flow_m3_min: float = Field(ge=0)
    nonproduction_samples: int = Field(ge=1)
    method: Literal["configured-schedule-screening"]
    production_average_flow_m3_min: float | None = Field(default=None, ge=0)
    screening_leakage_rate_pct: float | None = Field(default=None, ge=0)


class LoadOrderItem(StrictModel):
    device_id: str
    device_name: str
    load_rate_pct: float | None = Field(default=None, ge=0, le=100)


class GroupControlMetrics(StrictModel):
    compressor_count: int = Field(ge=2)
    load_order: list[LoadOrderItem]


class SavingsMetrics(StrictModel):
    screening_savings_kwh: float = Field(ge=0)
    unloaded_energy_kwh: float = Field(ge=0)
    assumed_reducible_fraction: float = Field(ge=0, le=1)
    method: Literal["unloaded-energy-screening"]


class CompressorMetrics(StrictModel):
    devices: dict[str, CompressorDeviceMetrics] = Field(default_factory=dict)
    pressure: dict[str, PressureMetrics] = Field(default_factory=dict)
    specific_power: SpecificPowerMetrics | None = None
    leakage_screening: LeakageMetrics | None = None
    group_control: GroupControlMetrics | None = None
    savings_screening: SavingsMetrics | None = None


class CompressorAnalysisResult(StrictModel):
    expert: str = "compressor"
    title: str = "空压机系统分析"
    data_status: Literal["no_scope", "available", "partial", "unavailable"]
    method: Literal["context-deterministic-first"] = "context-deterministic-first"
    query: str | None = None
    capabilities: list[CompressorCapability]
    context: CompressorContextSummary | None = None
    metrics: CompressorMetrics = Field(default_factory=CompressorMetrics)
    findings: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
