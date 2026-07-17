from collections.abc import Iterator, Mapping

from pydantic import BaseModel, ConfigDict, Field, RootModel

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type TelemetryScalar = str | int | float | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExternalModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SimulatorDevice(StrictModel):
    name: str
    device_type: str
    token: str = ""
    entity_id: str = ""


class AttributePayload(RootModel[dict[str, JsonValue]], Mapping[str, JsonValue]):
    def __getitem__(self, key: str) -> JsonValue:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)


class TelemetryPayload(RootModel[dict[str, TelemetryScalar]], Mapping[str, TelemetryScalar]):
    def __getitem__(self, key: str) -> TelemetryScalar:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def items(self):
        return self.root.items()


class HistoryRow(StrictModel):
    ts: int = Field(ge=0)
    values: TelemetryPayload


class LoginResponse(ExternalModel):
    token: str


class EntityId(ExternalModel):
    id: str


class DeviceEntity(ExternalModel):
    id: EntityId
    name: str
    type: str


class DevicePage(ExternalModel):
    data: list[DeviceEntity]


class DeviceCredentials(ExternalModel):
    credentialsId: str


class RpcRequest(StrictModel):
    method: str
    params: JsonValue = None


class RpcResponse(StrictModel):
    success: bool
    method: str
