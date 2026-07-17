from arthra.agent_tools import flatten_latest_telemetry
from arthra.contracts import AttributeValues, TelemetryValues, TimestampValues
from arthra.thingsboard import ThingsBoardClient, ThingsBoardError
from arthra.thingsboard_schemas import (
    AlarmInfo,
    AlarmPage,
    DeviceCatalogItem,
    DevicePage,
    TelemetryHistory,
)

SUPPORTED_CONTEXT_DEVICE_TYPES = {"compressor", "meter"}


class CompressorRepository:
    """Read-only ThingsBoard repository for compressed-air context construction."""

    def __init__(self, client: ThingsBoardClient | None = None):
        self.client = client or ThingsBoardClient()

    def catalog(self) -> list[DeviceCatalogItem]:
        page = DevicePage.model_validate(self.client.list_devices(page=0, page_size=1000))
        catalog: list[DeviceCatalogItem] = []
        for device in page.data:
            if device.type not in SUPPORTED_CONTEXT_DEVICE_TYPES:
                continue
            device_id = device.id.id
            try:
                attributes = AttributeValues.model_validate(self.client.attributes(device_id))
            except ThingsBoardError:
                attributes = AttributeValues({})
            catalog.append(
                DeviceCatalogItem(
                    device_id=device_id,
                    device_name=device.name,
                    device_type=device.type,
                    attributes=attributes,
                )
            )
        return catalog

    def latest(self, device_id: str, keys: list[str]) -> tuple[TelemetryValues, TimestampValues]:
        return flatten_latest_telemetry(self.client.latest_telemetry(device_id, keys or None))

    def history(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        interval_ms: int,
    ) -> TelemetryHistory:
        if not keys:
            return TelemetryHistory({})
        expected_points = max(1, (end_ts - start_ts) // interval_ms + 1)
        return TelemetryHistory.model_validate(self.client.telemetry_history(
            device_id=device_id,
            keys=keys,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=min(10_000, expected_points),
            agg="AVG",
            interval=interval_ms,
        ))

    def alarms(self, device_id: str) -> list[AlarmInfo]:
        return AlarmPage.model_validate(self.client.list_alarms(device_id)).data
