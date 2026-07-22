from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from arthra.contracts import AttributeValues
from arthra.industrial_data.ports import Aggregation
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)
from arthra.industrial_data.service import IndustrialDataError

ModelT = TypeVar("ModelT", bound=BaseModel)


class TimeSeriesApiIndustrialDataAdapter:
    """Adapter for an HTTP API implementing Arthra's unified industrial contract."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = 15,
        client: httpx.Client | None = None,
    ):
        if not base_url:
            raise IndustrialDataError("时序 API 数据源需要配置 TIMESERIES_API_URL")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    @property
    def provider_name(self) -> str:
        return "timeseries_api"

    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
    ):
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", "unavailable")
            raise IndustrialDataError(f"统一时序 API 请求失败（status={status}）") from exc

    @staticmethod
    def _validate(model: type[ModelT], payload: object) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise IndustrialDataError("统一时序 API 响应不符合工业数据协议") from exc

    def list_devices(
        self,
        page: int = 0,
        page_size: int = 100,
        text_search: str = "",
    ) -> IndustrialDevicePage:
        return self._validate(
            IndustrialDevicePage,
            self._get(
                "/devices",
                {"page": page, "page_size": page_size, "text_search": text_search},
            )
        )

    def latest_telemetry(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> IndustrialTelemetryHistory:
        params = {"keys": ",".join(keys)} if keys else None
        return self._validate(
            IndustrialTelemetryHistory,
            self._get(f"/devices/{device_id}/telemetry/latest", params)
        )

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
        params: dict[str, str | int] = {
            "keys": ",".join(keys),
            "start_ts": start_ts,
            "end_ts": end_ts,
            "limit": limit,
            "agg": agg,
        }
        if interval is not None:
            params["interval"] = interval
        return self._validate(
            IndustrialTelemetryHistory,
            self._get(f"/devices/{device_id}/telemetry/history", params)
        )

    def attributes(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> AttributeValues:
        params = {"keys": ",".join(keys)} if keys else None
        return self._validate(
            AttributeValues,
            self._get(f"/devices/{device_id}/attributes", params)
        )

    def list_alarms(
        self,
        device_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> IndustrialAlarmPage:
        return self._validate(
            IndustrialAlarmPage,
            self._get(
                f"/devices/{device_id}/alarms",
                {"page": page, "page_size": page_size},
            )
        )
