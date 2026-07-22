from arthra.agent_tools import flatten_latest_telemetry
from arthra.contracts import AttributeValues, TelemetryValues, TimestampValues
from arthra.industrial_data import IndustrialDataError, IndustrialDataService
from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.schemas import (
    IndustrialDeviceCatalogItem,
    IndustrialTelemetryHistory,
)


class PowerRepository:
    """Domain repository backed by the source-neutral industrial data service."""

    def __init__(self, service: IndustrialDataService | None = None):
        self.service = service or get_industrial_data_service()

    def catalog(self) -> list[IndustrialDeviceCatalogItem]:
        page = self.service.list_devices(page=0, page_size=1000)
        meters: list[IndustrialDeviceCatalogItem] = []
        for device in page.data:
            if device.type != "meter":
                continue
            device_id = device.id.id
            try:
                attributes = self.service.attributes(device_id)
            except IndustrialDataError:
                attributes = AttributeValues({})
            meters.append(
                IndustrialDeviceCatalogItem(
                    device_id=device_id,
                    device_name=device.name,
                    device_type=device.type,
                    attributes=attributes,
                )
            )
        return meters

    def latest(
        self,
        device_id: str,
        keys: list[str],
    ) -> tuple[TelemetryValues, TimestampValues]:
        return flatten_latest_telemetry(
            self.service.latest_telemetry(device_id, keys or None)
        )

    def history(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        interval_ms: int,
    ) -> IndustrialTelemetryHistory:
        if not keys:
            return IndustrialTelemetryHistory({})
        expected_points = max(1, (end_ts - start_ts) // interval_ms + 1)
        return self.service.telemetry_history(
            device_id=device_id,
            keys=keys,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=min(10_000, expected_points),
            agg="AVG",
            interval=interval_ms,
        )
