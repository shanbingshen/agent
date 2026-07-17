from typing import Any

import httpx

from arthra.config import Settings, get_settings
from arthra.contracts import AttributeValues, JsonObject
from arthra.thingsboard_schemas import (
    AlarmPage,
    DevicePage,
    RpcResponse,
    TelemetryHistory,
    ThingsBoardLogin,
)


class ThingsBoardError(RuntimeError):
    pass


class ThingsBoardClient:
    """Narrow ThingsBoard adapter. Credentials never leave this boundary."""

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(
            base_url=self.settings.thingsboard_url.rstrip("/"),
            timeout=self.settings.thingsboard_request_timeout,
        )
        self._token: str | None = None

    def _login(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={
                "username": self.settings.thingsboard_username,
                "password": self.settings.thingsboard_password,
            },
        )
        self._raise(response)
        self._token = ThingsBoardLogin.model_validate(response.json()).token

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._token:
            self._login()
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Authorization"] = f"Bearer {self._token}"
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401:
            self._token = None
            self._login()
            headers["X-Authorization"] = f"Bearer {self._token}"
            response = self.client.request(method, path, headers=headers, **kwargs)
        self._raise(response)
        return response

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:500]
            raise ThingsBoardError(f"ThingsBoard {response.status_code}: {body}") from exc

    def list_devices(self, page: int = 0, page_size: int = 100, text_search: str = "") -> DevicePage:
        payload = self._request(
            "GET",
            "/api/tenant/devices",
            params={"page": page, "pageSize": page_size, "textSearch": text_search},
        ).json()
        return DevicePage.model_validate(payload)

    def latest_telemetry(self, device_id: str, keys: list[str] | None = None) -> TelemetryHistory:
        params = {"keys": ",".join(keys)} if keys else {}
        payload = self._request(
            "GET", f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries", params=params
        ).json()
        return TelemetryHistory.model_validate(payload)

    def telemetry_history(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 1000,
        agg: str = "NONE",
        interval: int | None = None,
    ) -> TelemetryHistory:
        params: dict[str, str | int] = {
            "keys": ",".join(keys),
            "startTs": start_ts,
            "endTs": end_ts,
            "limit": limit,
            "agg": agg,
        }
        if interval is not None:
            params["interval"] = interval
        payload = self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params=params,
        ).json()
        return TelemetryHistory.model_validate(payload)

    def attributes(self, device_id: str, keys: list[str] | None = None) -> AttributeValues:
        params = {"keys": ",".join(keys)} if keys else {}
        rows = self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/attributes",
            params=params,
        ).json()
        return AttributeValues.model_validate({row["key"]: row.get("value") for row in rows})

    def list_alarms(self, device_id: str, page: int = 0, page_size: int = 50) -> AlarmPage:
        payload = self._request(
            "GET",
            "/api/alarm/DEVICE/" + device_id,
            params={"page": page, "pageSize": page_size, "sortProperty": "createdTime", "sortOrder": "DESC"},
        ).json()
        return AlarmPage.model_validate(payload)

    def send_rpc(self, device_id: str, method: str, params: JsonObject) -> RpcResponse:
        response = self._request(
            "POST",
            f"/api/plugins/rpc/twoway/{device_id}",
            json={"method": method, "params": params.model_dump(), "timeout": 10_000},
        )
        if not response.content:
            return RpcResponse(accepted=True)
        payload = response.json()
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return RpcResponse(accepted=True, payload=JsonObject.model_validate(payload))
