from arthra.contracts import AttributeValues
from arthra.industrial_data.ports import Aggregation
from arthra.industrial_data.schemas import (
    IndustrialAlarm,
    IndustrialAlarmPage,
    IndustrialDevice,
    IndustrialDevicePage,
    IndustrialEntityId,
    IndustrialTelemetryHistory,
    IndustrialTelemetrySample,
)
from arthra.industrial_data.service import IndustrialDataError
from arthra.thingsboard import ThingsBoardClient, ThingsBoardError


class ThingsBoardIndustrialDataAdapter:
    """Convert validated ThingsBoard projections into source-neutral contracts."""

    def __init__(self, client: ThingsBoardClient | None = None):
        self.client = client or ThingsBoardClient()

    @property
    def provider_name(self) -> str:
        return "thingsboard"

    @staticmethod
    def _error(exc: ThingsBoardError) -> IndustrialDataError:
        return IndustrialDataError(str(exc))

    @staticmethod
    def _history(payload) -> IndustrialTelemetryHistory:
        return IndustrialTelemetryHistory.model_validate(
            {
                key: [
                    IndustrialTelemetrySample(ts=sample.ts, value=sample.value)
                    for sample in samples
                ]
                for key, samples in payload.items()
            }
        )

    def list_devices(
        self,
        page: int = 0,
        page_size: int = 100,
        text_search: str = "",
    ) -> IndustrialDevicePage:
        try:
            source = self.client.list_devices(page, page_size, text_search)
        except ThingsBoardError as exc:
            raise self._error(exc) from exc
        return IndustrialDevicePage(
            data=[
                IndustrialDevice(
                    id=IndustrialEntityId(
                        id=device.id.id,
                        entity_type=device.id.entity_type,
                    ),
                    name=device.name,
                    type=device.type,
                    label=device.label,
                )
                for device in source.data
            ],
            total_pages=source.total_pages,
            total_elements=source.total_elements,
            has_next=source.has_next,
        )

    def latest_telemetry(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> IndustrialTelemetryHistory:
        try:
            return self._history(self.client.latest_telemetry(device_id, keys))
        except ThingsBoardError as exc:
            raise self._error(exc) from exc

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
        if not keys:
            return IndustrialTelemetryHistory({})
        try:
            if agg == "NONE" or interval is None:
                return self._history(
                    self.client.telemetry_history(
                        device_id,
                        keys,
                        start_ts,
                        end_ts,
                        limit=limit,
                        agg=agg,
                        interval=interval,
                    )
                )
            max_intervals = 480
            chunk_span_ms = interval * (max_intervals - 1)
            merged: dict[str, dict[int, IndustrialTelemetrySample]] = {
                key: {} for key in keys
            }
            cursor = start_ts
            while cursor <= end_ts:
                chunk_end = min(end_ts, cursor + chunk_span_ms)
                chunk = self._history(
                    self.client.telemetry_history(
                        device_id,
                        keys,
                        cursor,
                        chunk_end,
                        limit=max_intervals,
                        agg=agg,
                        interval=interval,
                    )
                )
                for key in keys:
                    for sample in chunk.get(key, []):
                        merged[key][sample.ts] = sample
                cursor = chunk_end + 1
            return IndustrialTelemetryHistory.model_validate(
                {
                    key: [sample for _, sample in sorted(samples.items())]
                    for key, samples in merged.items()
                }
            )
        except ThingsBoardError as exc:
            raise self._error(exc) from exc

    def attributes(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> AttributeValues:
        try:
            return AttributeValues.model_validate(self.client.attributes(device_id, keys))
        except ThingsBoardError as exc:
            raise self._error(exc) from exc

    def list_alarms(
        self,
        device_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> IndustrialAlarmPage:
        try:
            source = self.client.list_alarms(device_id, page, page_size)
        except ThingsBoardError as exc:
            raise self._error(exc) from exc
        return IndustrialAlarmPage(
            data=[
                IndustrialAlarm(
                    id=(
                        IndustrialEntityId(
                            id=alarm.id.id,
                            entity_type=alarm.id.entity_type,
                        )
                        if alarm.id
                        else None
                    ),
                    type=alarm.type,
                    severity=alarm.severity,
                    status=alarm.status,
                    created_time=alarm.created_time,
                    details=alarm.details,
                )
                for alarm in source.data
            ],
            total_pages=source.total_pages,
            total_elements=source.total_elements,
            has_next=source.has_next,
        )
