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

type PowerCapability = Literal[
    "realtime_power",
    "energy_consumption",
    "energy_compare",
    "demand_15m",
    "peak_detection",
    "peak_average_ratio",
    "declared_demand_exceedance",
    "voltage_deviation",
    "phase_imbalance",
    "power_factor",
    "thd",
    "harmonics",
    "abnormal_duration",
]


class PowerAnalysisRequest(StrictModel):
    message: str = "执行用电负荷、需量与电能质量分析"
    device_scope: list[str] = Field(default_factory=list, max_length=100)
    start_at: datetime | None = None
    end_at: datetime | None = None
    interval_seconds: int = Field(default=60, ge=30, le=900)
    declared_demand_kw: float | None = Field(default=None, gt=0)
    capabilities: list[PowerCapability] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_window(self) -> "PowerAnalysisRequest":
        end = self.end_at or datetime.now(UTC)
        start = self.start_at or end - timedelta(hours=24)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start_at 和 end_at 必须包含时区")
        if start >= end:
            raise ValueError("start_at 必须早于 end_at")
        if end - start > timedelta(days=31):
            raise ValueError("单次电力分析时间窗口不能超过31天")
        object.__setattr__(self, "start_at", start.astimezone(UTC))
        object.__setattr__(self, "end_at", end.astimezone(UTC))
        return self


class PowerToolInput(StrictModel):
    device_scope: list[str] = Field(min_length=1, max_length=100)
    start_at: datetime | None = None
    end_at: datetime | None = None
    interval_seconds: int = Field(default=60, ge=30, le=900)
    declared_demand_kw: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_window(self) -> "PowerToolInput":
        request = PowerAnalysisRequest(
            device_scope=self.device_scope,
            start_at=self.start_at,
            end_at=self.end_at,
            interval_seconds=self.interval_seconds,
            declared_demand_kw=self.declared_demand_kw,
        )
        object.__setattr__(self, "start_at", request.start_at)
        object.__setattr__(self, "end_at", request.end_at)
        return self


class PowerSignalPoint(StrictModel):
    ts: int = Field(ge=0)
    value: float


class PowerSignalSeries(StrictModel):
    key: str
    unit: str = ""
    points: list[PowerSignalPoint] = Field(default_factory=list)


class PowerDataQuality(StrictModel):
    coverage: float = Field(default=0, ge=0, le=1)
    expected_series: int = Field(default=0, ge=0)
    available_series: int = Field(default=0, ge=0)
    missing_keys: list[str] = Field(default_factory=list)
    stale_keys: list[str] = Field(default_factory=list)
    invalid_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PowerMeterContext(StrictModel):
    device_id: str
    device_name: str
    attributes: AttributeValues = Field(default_factory=lambda: AttributeValues({}))
    latest: TelemetryValues = Field(default_factory=lambda: TelemetryValues({}))
    latest_timestamps: TimestampValues = Field(default_factory=lambda: TimestampValues({}))
    signals: dict[str, PowerSignalSeries] = Field(default_factory=dict)
    declared_demand_kw: float = Field(gt=0)


class PowerSystemContext(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    start_ts: int = Field(ge=0)
    end_ts: int = Field(ge=0)
    interval_seconds: int = Field(ge=30, le=900)
    capabilities: list[PowerCapability]
    requested_device_scope: list[str]
    meters: list[PowerMeterContext]
    data_quality: PowerDataQuality


class PowerContextMeterSummary(StrictModel):
    device_id: str
    device_name: str
    declared_demand_kw: float = Field(gt=0)


class PowerContextSummary(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    start_ts: int = Field(ge=0)
    end_ts: int = Field(ge=0)
    interval_seconds: int = Field(ge=30, le=900)
    meters: list[PowerContextMeterSummary]
    data_quality: PowerDataQuality


class AbnormalDurationMetric(StrictModel):
    code: str
    label: str
    threshold: float
    unit: str
    total_minutes: float = Field(ge=0)
    longest_minutes: float = Field(ge=0)
    abnormal_samples: int = Field(ge=0)


class LoadPeakEvent(StrictModel):
    ts: int = Field(ge=0)
    load_kw: float = Field(ge=0)
    kind: Literal["instantaneous", "rolling_15m"]


class DemandMetrics(StrictModel):
    sample_count: int = Field(default=0, ge=0)
    observation_hours: float | None = Field(default=None, ge=0)
    average_load_kw: float | None = Field(default=None, ge=0)
    rolling_window_minutes: Literal[15] = 15
    rolling_sample_count: int = Field(default=0, ge=0)
    max_demand_15m_kw: float | None = Field(default=None, ge=0)
    max_demand_window_start_ts: int | None = Field(default=None, ge=0)
    max_demand_window_end_ts: int | None = Field(default=None, ge=0)
    instantaneous_peak_kw: float | None = Field(default=None, ge=0)
    instantaneous_peak_ts: int | None = Field(default=None, ge=0)
    peaks: list[LoadPeakEvent] = Field(default_factory=list)
    peak_average_ratio: float | None = Field(default=None, ge=0)
    declared_demand_kw: float | None = Field(default=None, gt=0)
    exceedance_kw: float | None = Field(default=None, ge=0)
    exceedance_pct: float | None = Field(default=None, ge=0)
    exceedance_total_minutes: float | None = Field(default=None, ge=0)
    exceedance_longest_minutes: float | None = Field(default=None, ge=0)


class RealtimePowerMetrics(StrictModel):
    active_power_kw: float = Field(ge=0)
    timestamp: int = Field(ge=0)


class EnergyPeriodMetrics(StrictModel):
    period_start_ts: int = Field(ge=0)
    period_end_ts: int = Field(ge=0)
    start_reading_kwh: float | None = Field(default=None, ge=0)
    end_reading_kwh: float | None = Field(default=None, ge=0)
    consumption_kwh: float | None = Field(default=None, ge=0)
    previous_consumption_kwh: float | None = Field(default=None, ge=0)
    change_kwh: float | None = None
    change_pct: float | None = None
    calculation_method: Literal["cumulative-register-delta"] = "cumulative-register-delta"


class VoltagePhaseMetrics(StrictModel):
    phase: Literal["AB", "BC", "CA"]
    average_v: float = Field(gt=0)
    latest_v: float = Field(gt=0)
    max_abs_deviation_pct: float = Field(ge=0)
    abnormal_total_minutes: float = Field(ge=0)
    abnormal_longest_minutes: float = Field(ge=0)


class ScalarQualityMetrics(StrictModel):
    average: float
    latest: float
    min: float
    max: float
    threshold: float
    abnormal_total_minutes: float = Field(ge=0)
    abnormal_longest_minutes: float = Field(ge=0)


class HarmonicOrderMetrics(StrictModel):
    order: Literal[3, 5, 7]
    voltage_average_pct: float | None = Field(default=None, ge=0)
    voltage_max_pct: float | None = Field(default=None, ge=0)
    current_average_pct: float | None = Field(default=None, ge=0)
    current_max_pct: float | None = Field(default=None, ge=0)


class PowerQualityMetrics(StrictModel):
    phase_currents_a: dict[str, float] = Field(default_factory=dict)
    voltage_deviation: dict[str, VoltagePhaseMetrics] = Field(default_factory=dict)
    voltage_unbalance: ScalarQualityMetrics | None = None
    current_unbalance: ScalarQualityMetrics | None = None
    power_factor: ScalarQualityMetrics | None = None
    thdu: dict[str, ScalarQualityMetrics] = Field(default_factory=dict)
    thdi: dict[str, ScalarQualityMetrics] = Field(default_factory=dict)
    harmonics: list[HarmonicOrderMetrics] = Field(default_factory=list)
    dominant_voltage_harmonic_order: Literal[3, 5, 7] | None = None
    dominant_current_harmonic_order: Literal[3, 5, 7] | None = None
    abnormal_durations: list[AbnormalDurationMetric] = Field(default_factory=list)


class PowerMetrics(StrictModel):
    realtime: dict[str, RealtimePowerMetrics] = Field(default_factory=dict)
    energy: dict[str, EnergyPeriodMetrics] = Field(default_factory=dict)
    demand: dict[str, DemandMetrics] = Field(default_factory=dict)
    quality: dict[str, PowerQualityMetrics] = Field(default_factory=dict)


class PowerAnalysisResult(StrictModel):
    expert: Literal["power"] = "power"
    title: str = "用电负荷与需量专家分析"
    data_status: Literal["no_scope", "available", "partial", "unavailable"]
    method: Literal["power-deterministic-first"] = "power-deterministic-first"
    query: str | None = None
    capabilities: list[PowerCapability]
    context: PowerContextSummary | None = None
    metrics: PowerMetrics = Field(default_factory=PowerMetrics)
    findings: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
