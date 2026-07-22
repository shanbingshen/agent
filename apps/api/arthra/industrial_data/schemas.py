from pydantic import Field, RootModel

from arthra.contracts import (
    AttributeValues,
    JsonObject,
    StrictModel,
    TelemetryScalar,
)


class IndustrialEntityId(StrictModel):
    id: str
    entity_type: str | None = None


class IndustrialDevice(StrictModel):
    id: IndustrialEntityId
    name: str
    type: str
    label: str | None = None


class IndustrialDevicePage(StrictModel):
    data: list[IndustrialDevice]
    total_pages: int = Field(default=1, ge=0)
    total_elements: int = Field(default=0, ge=0)
    has_next: bool = False


class IndustrialTelemetrySample(StrictModel):
    ts: int = Field(ge=0)
    value: TelemetryScalar


class IndustrialTelemetryHistory(
    RootModel[dict[str, list[IndustrialTelemetrySample]]]
):
    def __getitem__(self, key: str) -> list[IndustrialTelemetrySample]:
        return self.root[key]

    def __iter__(self):
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def get(self, key: str, default=None):
        return self.root.get(key, default)

    def items(self):
        return self.root.items()


class IndustrialAlarm(StrictModel):
    id: IndustrialEntityId | None = None
    type: str = "unknown"
    severity: str = "INDETERMINATE"
    status: str = "unknown"
    created_time: int = Field(default=0, ge=0)
    details: JsonObject = Field(default_factory=lambda: JsonObject({}))


class IndustrialAlarmPage(StrictModel):
    data: list[IndustrialAlarm]
    total_pages: int = Field(default=1, ge=0)
    total_elements: int = Field(default=0, ge=0)
    has_next: bool = False


class IndustrialDeviceCatalogItem(StrictModel):
    device_id: str
    device_name: str
    device_type: str
    attributes: AttributeValues


class MockIndustrialDataSet(StrictModel):
    devices: list[IndustrialDevice] = Field(default_factory=list)
    telemetry: dict[str, IndustrialTelemetryHistory] = Field(default_factory=dict)
    attributes: dict[str, AttributeValues] = Field(default_factory=dict)
    alarms: dict[str, list[IndustrialAlarm]] = Field(default_factory=dict)
