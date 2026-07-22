from typing import Literal, Protocol, runtime_checkable

from arthra.contracts import AttributeValues
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)

type Aggregation = Literal["AVG", "MIN", "MAX", "SUM", "COUNT", "NONE"]


@runtime_checkable
class IndustrialDataAdapter(Protocol):
    @property
    def provider_name(self) -> str: ...

    def list_devices(
        self,
        page: int = 0,
        page_size: int = 100,
        text_search: str = "",
    ) -> IndustrialDevicePage: ...

    def latest_telemetry(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> IndustrialTelemetryHistory: ...

    def telemetry_history(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 1000,
        agg: Aggregation = "NONE",
        interval: int | None = None,
    ) -> IndustrialTelemetryHistory: ...

    def attributes(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> AttributeValues: ...

    def list_alarms(
        self,
        device_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> IndustrialAlarmPage: ...
