"""energy-data MCP 的进程内回退客户端。

迁移期间保持统一工业数据服务可用；切换 stdio/HTTP transport 时不影响领域调用方。
"""

from arthra.contracts import AttributeValues
from arthra.industrial_data import IndustrialDataService
from arthra.industrial_data.ports import Aggregation


class LocalEnergyDataClient:
    def __init__(self, service: IndustrialDataService, allowed_device_ids: set[str]):
        self._service = service
        self._allowed_device_ids = allowed_device_ids

    def _authorize(self, device_id: str) -> None:
        if device_id not in self._allowed_device_ids:
            raise PermissionError("设备不在当前授权范围内")

    def latest_telemetry(self, device_id: str, keys: list[str] | None = None):
        self._authorize(device_id)
        return self._service.latest_telemetry(device_id, keys)

    def telemetry_history(
        self, device_id: str, keys: list[str], start_ts: int, end_ts: int,
        limit: int = 1000, agg: Aggregation = "NONE", interval: int | None = None,
    ):
        self._authorize(device_id)
        return self._service.telemetry_history(device_id, keys, start_ts, end_ts, limit, agg, interval)

    def attributes(self, device_id: str, keys: list[str] | None = None) -> AttributeValues:
        self._authorize(device_id)
        return self._service.attributes(device_id, keys)
