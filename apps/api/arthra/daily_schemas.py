from pydantic import Field

from arthra.contracts import AnalysisWarning, StrictModel


class HistoryMetric(StrictModel):
    samples: int = Field(ge=1)
    first: float
    latest: float
    min: float
    max: float
    avg: float
    delta: float
    latest_bucket_avg: float | None = None


class DailyAlarm(StrictModel):
    type: str
    severity: str
    status: str
    created_time: int = Field(ge=0)
    device_id: str | None = None
    device_name: str | None = None


class DailyDeviceStatistics(StrictModel):
    device_id: str
    device_name: str
    device_type: str
    metrics: dict[str, HistoryMetric] = Field(default_factory=dict)
    alarm_count: int = Field(ge=0)
    alarms: list[DailyAlarm] = Field(default_factory=list)


class DailyOverview(StrictModel):
    device_count: int = Field(ge=0)
    available_device_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    alarm_count: int = Field(ge=0)
    average_active_power_kw: float | None = None
    energy_consumption_kwh: float | None = Field(default=None, ge=0)


class DailySnapshot(StrictModel):
    overview: DailyOverview
    devices: list[DailyDeviceStatistics]
    findings: list[str]
    missing_metrics: list[str]
    warnings: list[AnalysisWarning]
    thingsboard_alarms: list[DailyAlarm]

