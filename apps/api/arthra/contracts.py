from collections.abc import Iterator, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type TelemetryScalar = str | int | float | bool | None


class StrictModel(BaseModel):
    """Default contract for data crossing module or API boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def __getitem__(self, key: str):
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


class OrmReadModel(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        from_attributes=True,
    )


class MapContract[ValueT](RootModel[dict[str, ValueT]], Mapping[str, ValueT]):
    def __getitem__(self, key: str) -> ValueT:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def get(self, key: str, default=None):
        return self.root.get(key, default)

    def items(self):
        return self.root.items()

    def values(self):
        return self.root.values()


class JsonObject(MapContract[JsonValue]):
    pass


class TelemetryValues(MapContract[TelemetryScalar]):
    pass


class TimestampValues(MapContract[int]):
    pass


class AttributeValues(MapContract[JsonValue]):
    pass


Severity = Literal["info", "low", "medium", "high", "critical", "unknown"]


class AnalysisWarning(StrictModel):
    severity: Severity = "unknown"
    message: str
    code: str | None = None
    metric: str | None = None
    value: JsonValue = None
    device_id: str | None = None
    device_name: str | None = None
    evidence: JsonObject | None = None


class Recommendation(StrictModel):
    code: str
    message: str
    evidence: JsonObject | None = None


class Citation(StrictModel):
    source_id: str
    title: str
    excerpt: str | None = None
    score: float | None = None
