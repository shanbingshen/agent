from typing import Literal

from pydantic import Field

from arthra.contracts import (
    AnalysisWarning,
    AttributeValues,
    StrictModel,
    TelemetryValues,
    TimestampValues,
)

type ExpertName = Literal["ems", "power", "compressor", "forecast", "report"]
type DataStatus = Literal["no_scope", "available", "partial", "unavailable"]


class DeviceContext(StrictModel):
    id: str
    name: str | None = None
    type: str = "unknown"
    telemetry: TelemetryValues = Field(default_factory=lambda: TelemetryValues({}))
    timestamps: TimestampValues = Field(default_factory=lambda: TimestampValues({}))
    attributes: AttributeValues = Field(default_factory=lambda: AttributeValues({}))
    error: str | None = None


class DeviceAnalysis(DeviceContext):
    findings: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)


class ExpertAnalysis(StrictModel):
    expert: ExpertName
    title: str
    data_status: DataStatus
    method: Literal["deterministic-first"] = "deterministic-first"
    query: str | None = None
    device_count: int = Field(default=0, ge=0)
    devices: list[DeviceAnalysis] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)

