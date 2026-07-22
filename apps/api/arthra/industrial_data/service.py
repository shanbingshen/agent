from arthra.contracts import AttributeValues
from arthra.industrial_data.ports import Aggregation, IndustrialDataAdapter
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)


class IndustrialDataError(RuntimeError):
    pass


class IndustrialDataService:
    """Source-neutral read service used by Agents and domain repositories."""

    def __init__(self, adapter: IndustrialDataAdapter):
        self.adapter = adapter

    @property
    def provider_name(self) -> str:
        return self.adapter.provider_name

    def list_devices(
        self,
        page: int = 0,
        page_size: int = 100,
        text_search: str = "",
    ) -> IndustrialDevicePage:
        return self.adapter.list_devices(page, page_size, text_search)

    def latest_telemetry(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> IndustrialTelemetryHistory:
        return self.adapter.latest_telemetry(device_id, keys)

    def telemetry_history(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 1000,
        agg: Aggregation = "NONE",
        interval: int | None = None,
    ) -> IndustrialTelemetryHistory:
        return self.adapter.telemetry_history(
            device_id,
            keys,
            start_ts,
            end_ts,
            limit,
            agg,
            interval,
        )

    def attributes(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> AttributeValues:
        return self.adapter.attributes(device_id, keys)

    def list_alarms(
        self,
        device_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> IndustrialAlarmPage:
        return self.adapter.list_alarms(device_id, page, page_size)
