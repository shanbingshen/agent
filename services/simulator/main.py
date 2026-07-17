import json
import os
import time

import httpx
import paho.mqtt.client as mqtt
from profiles import (
    compressor_attributes,
    compressor_telemetry,
    ems_telemetry,
    meter_attributes,
    meter_telemetry,
)
from schemas import (
    AttributePayload,
    DeviceCredentials,
    DeviceEntity,
    DevicePage,
    HistoryRow,
    JsonValue,
    LoginResponse,
    RpcRequest,
    RpcResponse,
    SimulatorDevice,
    TelemetryPayload,
)

DEVICES = [
    SimulatorDevice(name="Arthra-EMS-01", device_type="ems"),
    SimulatorDevice(name="Arthra-Meter-01", device_type="meter"),
    SimulatorDevice(name="Arthra-Compressor-01", device_type="compressor"),
]
TB_URL = os.getenv("THINGSBOARD_URL", "http://thingsboard:9090").rstrip("/")
TB_USER = os.getenv("THINGSBOARD_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("THINGSBOARD_PASSWORD", "tenant")
MQTT_HOST = os.getenv("THINGSBOARD_MQTT_HOST", "thingsboard")
SIMULATION_EPOCH_SECONDS = 1_767_225_600  # 2026-01-01T00:00:00Z
HISTORY_INTERVAL_SECONDS = 60
HISTORY_WINDOW_HOURS = 24
COMPRESSOR_CONTEXT_KEYS = {
    "air_comp_running_flag",
    "air_comp_loaded_flag",
    "air_comp_unloaded_running_flag",
    "air_comp_running_hours",
    "air_comp_loading_hours",
    "air_comp_start_count",
    "air_comp_supply_pressure",
    "air_system_header_pressure_mpa",
    "air_comp_main_current_a",
    "air_comp_fad_flow_m3_min",
}
METER_CONTEXT_KEYS = {"meter_TotW", "meter_SupWh"}


def simulation_tick(timestamp: float | None = None) -> int:
    value = timestamp if timestamp is not None else time.time()
    return max(0, int((value - SIMULATION_EPOCH_SECONDS) / 5))


def wait_for_token(client: httpx.Client) -> str:
    while True:
        try:
            response = client.post("/api/auth/login", json={"username": TB_USER, "password": TB_PASSWORD})
            response.raise_for_status()
            return LoginResponse.model_validate(response.json()).token
        except Exception as exc:
            print(f"Waiting for ThingsBoard: {exc}", flush=True)
            time.sleep(10)


def ensure_devices(client: httpx.Client, jwt_token: str) -> None:
    headers = {"X-Authorization": f"Bearer {jwt_token}"}
    page = DevicePage.model_validate(
        client.get(
            "/api/tenant/devices",
            headers=headers,
            params={"page": 0, "pageSize": 100},
        ).json()
    )
    existing = {item.name: item for item in page.data}
    for device in DEVICES:
        entity = existing.get(device.name)
        if entity is None:
            response = client.post("/api/device", headers=headers, json={"name": device.name, "type": device.device_type})
            response.raise_for_status()
            entity = DeviceEntity.model_validate(response.json())
        device.entity_id = entity.id.id
        credentials = client.get(f"/api/device/{entity.id.id}/credentials", headers=headers)
        credentials.raise_for_status()
        device.token = DeviceCredentials.model_validate(credentials.json()).credentialsId

    by_type = {device.device_type: device for device in DEVICES}
    for device in DEVICES:
        attributes: dict[str, JsonValue] = {}
        if device.device_type == "compressor":
            attributes = compressor_attributes()
            attributes["linkedMeterDeviceId"] = by_type["meter"].entity_id
        elif device.device_type == "meter":
            attributes = meter_attributes()
            attributes["monitoredCompressorDeviceId"] = by_type["compressor"].entity_id
        if attributes:
            attributes["deviceId"] = device.entity_id
            payload = AttributePayload.model_validate(attributes)
            client.post(
                f"/api/v1/{device.token}/attributes",
                json=payload.model_dump(mode="json"),
            ).raise_for_status()


def seed_context_history(client: httpx.Client) -> None:
    now = time.time()
    sample_count = HISTORY_WINDOW_HOURS * 3600 // HISTORY_INTERVAL_SECONDS
    for device in DEVICES:
        if device.device_type not in {"compressor", "meter"}:
            continue
        rows = []
        for index in range(sample_count, 0, -1):
            timestamp = now - index * HISTORY_INTERVAL_SECONDS
            tick = simulation_tick(timestamp)
            values = telemetry(device, tick)
            allowed = (
                COMPRESSOR_CONTEXT_KEYS
                if device.device_type == "compressor"
                else METER_CONTEXT_KEYS
            )
            rows.append(HistoryRow(
                ts=int(timestamp * 1000),
                values=TelemetryPayload({
                    key: value for key, value in values.items() if key in allowed
                }),
            ))
        for start in range(0, len(rows), 48):
            client.post(
                f"/api/v1/{device.token}/telemetry",
                json=[row.model_dump(mode="json") for row in rows[start : start + 48]],
            ).raise_for_status()


def telemetry(device: SimulatorDevice, tick: int) -> TelemetryPayload:
    if device.device_type == "ems":
        raw = ems_telemetry(tick)
    elif device.device_type == "meter":
        raw = meter_telemetry(tick) if tick % 2 == 0 else {}
    else:
        raw = compressor_telemetry(tick)
    return TelemetryPayload.model_validate(raw)


def start_rpc_listener(device: SimulatorDevice) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{device.name}")
    client.username_pw_set(device.token)

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe("v1/devices/me/rpc/request/+")

    def on_message(client, userdata, msg):
        request_id = msg.topic.rsplit("/", 1)[-1]
        request = RpcRequest.model_validate(json.loads(msg.payload))
        print(f"RPC {device.name}: {request}", flush=True)
        response = RpcResponse(success=True, method=request.method)
        client.publish(
            f"v1/devices/me/rpc/response/{request_id}",
            response.model_dump_json(),
        )

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883, 60)
    client.loop_start()
    return client


def main() -> None:
    with httpx.Client(base_url=TB_URL, timeout=20) as client:
        token = wait_for_token(client)
        ensure_devices(client, token)
        seed_context_history(client)
        listeners = [start_rpc_listener(device) for device in DEVICES]
        tick = simulation_tick()
        while True:
            for device in DEVICES:
                try:
                    payload = telemetry(device, tick)
                    if len(payload):
                        client.post(
                            f"/api/v1/{device.token}/telemetry",
                            json=payload.model_dump(mode="json"),
                        ).raise_for_status()
                except Exception as exc:
                    print(f"Telemetry failed for {device.name}: {exc}", flush=True)
            tick += 1
            time.sleep(5)
        for listener in listeners:
            listener.loop_stop()


if __name__ == "__main__":
    main()
