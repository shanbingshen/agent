from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel, field_validator

from arthra.contracts import AttributeValues, JsonObject, StrictModel, TelemetryScalar


class ThingsBoardExternalModel(BaseModel):
    """Validated projection of an external ThingsBoard payload."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ThingsBoardLogin(ThingsBoardExternalModel):
    token: str


class EntityId(ThingsBoardExternalModel):
    id: str
    entity_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("entityType", "entity_type"),
    )


class DeviceInfo(ThingsBoardExternalModel):
    id: EntityId
    name: str
    type: str
    label: str | None = None


class DevicePage(ThingsBoardExternalModel):
    data: list[DeviceInfo]
    total_pages: int = Field(default=1, validation_alias=AliasChoices("totalPages", "total_pages"))
    total_elements: int = Field(
        default=0,
        validation_alias=AliasChoices("totalElements", "total_elements"),
    )
    has_next: bool = Field(default=False, validation_alias=AliasChoices("hasNext", "has_next"))


class TelemetrySample(ThingsBoardExternalModel):
    ts: int
    value: TelemetryScalar


class TelemetryHistory(RootModel[dict[str, list[TelemetrySample]]]):
    def __getitem__(self, key: str) -> list[TelemetrySample]:
        return self.root[key]

    def __iter__(self):
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def get(self, key: str, default=None):
        return self.root.get(key, default)

    def items(self):
        return self.root.items()


class AlarmInfo(ThingsBoardExternalModel):
    id: EntityId | None = None
    type: str = "unknown"
    severity: str = "INDETERMINATE"
    status: str = "unknown"
    created_time: int = Field(default=0, validation_alias=AliasChoices("createdTime", "created_time"))
    details: JsonObject = Field(default_factory=lambda: JsonObject({}))

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, value: Any):
        return value or {}


class AlarmPage(ThingsBoardExternalModel):
    data: list[AlarmInfo]
    total_pages: int = Field(default=1, validation_alias=AliasChoices("totalPages", "total_pages"))
    total_elements: int = Field(
        default=0,
        validation_alias=AliasChoices("totalElements", "total_elements"),
    )
    has_next: bool = Field(default=False, validation_alias=AliasChoices("hasNext", "has_next"))


class RpcResponse(StrictModel):
    accepted: bool = True
    payload: JsonObject = Field(default_factory=lambda: JsonObject({}))


class DeviceCatalogItem(StrictModel):
    device_id: str
    device_name: str
    device_type: str
    attributes: AttributeValues
