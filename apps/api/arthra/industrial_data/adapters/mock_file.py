import json
import math
import time
from pathlib import Path

from arthra.contracts import AttributeValues
from arthra.industrial_data.ports import Aggregation
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevice,
    IndustrialDevicePage,
    IndustrialEntityId,
    IndustrialTelemetryHistory,
    IndustrialTelemetrySample,
    MockIndustrialDataSet,
)
from arthra.industrial_data.service import IndustrialDataError


def _demo_dataset() -> MockIndustrialDataSet:
    now_ms = int(time.time() // 60 * 60_000)
    timestamps = [now_ms - (1_439 - index) * 60_000 for index in range(1_440)]

    meter_values: dict[str, list[dict[str, float | int]]] = {}
    compressor_values: dict[str, list[dict[str, float | int]]] = {}
    ems_values: dict[str, list[dict[str, float | int]]] = {}

    for index, ts in enumerate(timestamps):
        wave = math.sin(index / 14)
        loaded = index % 60 < 48
        running = index % 240 < 220
        power = 104 + wave if loaded else (36 + wave if running else 3)
        meter_sample = {
            "meter_TotW": power,
            "meter_LinV_phsAB": 380 + wave * 2,
            "meter_LinV_phsBC": 381 - wave * 1.5,
            "meter_LinV_phsCA": 379 + wave,
            "meter_ImbNgV": 0.8 + abs(wave) * 0.2,
            "meter_ImbNgA": 4 + abs(wave) * 2,
            "meter_TotPF": 0.955,
        }
        for phase_offset, phase in enumerate(("A", "B", "C")):
            thdu = 2.1 + abs(math.sin(index / 14 + phase_offset)) * 0.35
            thdi = 8.2 + abs(math.sin(index / 14 + phase_offset)) * 2.1
            meter_sample[f"meter_ThdPhV_phs{phase}"] = thdu
            meter_sample[f"meter_ThdA_phs{phase}"] = thdi
            for order, ratio in ((3, 0.42), (5, 0.31), (7, 0.18)):
                meter_sample[f"meter_ThdPhV{order}_phs{phase}"] = thdu * ratio
                meter_sample[f"meter_ThdA{order}_phs{phase}"] = thdi * ratio
        for key, value in meter_sample.items():
            meter_values.setdefault(key, []).append({"ts": ts, "value": value})

        running_flag = 1 if running else 0
        loaded_flag = 1 if running and loaded else 0
        compressor_sample = {
            "air_comp_running_flag": running_flag,
            "air_comp_loaded_flag": loaded_flag,
            "air_comp_unloaded_running_flag": 1 if running and not loaded else 0,
            "air_comp_running_hours": 12_840 + index / 60 * (220 / 240),
            "air_comp_loading_hours": 9_730 + index / 60 * (176 / 240),
            "air_comp_start_count": 315 + index // 240,
            "air_comp_supply_pressure": 0.72 + wave * 0.025 if running else 0.05,
            "air_system_header_pressure_mpa": 0.685 + wave * 0.025 if running else 0.02,
            "air_comp_main_current_a": 126 + wave * 14 if loaded_flag else (42 if running else 0),
            "air_comp_fad_flow_m3_min": 18.2 + wave if loaded_flag else (1.1 if running else 0),
        }
        for key, value in compressor_sample.items():
            compressor_values.setdefault(key, []).append({"ts": ts, "value": value})

        ems_sample = {
            "power_kw": 180 + wave * 35,
            "energy_kwh": 24_000 + index * 3,
            "soc": 70 - wave * 8,
        }
        for key, value in ems_sample.items():
            ems_values.setdefault(key, []).append({"ts": ts, "value": value})

    devices = [
        IndustrialDevice(
            id=IndustrialEntityId(id="mock-ems-01", entity_type="DEVICE"),
            name="Mock-EMS-01",
            type="ems",
        ),
        IndustrialDevice(
            id=IndustrialEntityId(id="mock-meter-01", entity_type="DEVICE"),
            name="Mock-Meter-01",
            type="meter",
        ),
        IndustrialDevice(
            id=IndustrialEntityId(id="mock-compressor-01", entity_type="DEVICE"),
            name="Mock-Compressor-01",
            type="compressor",
        ),
    ]
    return MockIndustrialDataSet(
        devices=devices,
        telemetry={
            "mock-ems-01": IndustrialTelemetryHistory.model_validate(ems_values),
            "mock-meter-01": IndustrialTelemetryHistory.model_validate(meter_values),
            "mock-compressor-01": IndustrialTelemetryHistory.model_validate(
                compressor_values
            ),
        },
        attributes={
            "mock-ems-01": AttributeValues({"siteId": "mock-site"}),
            "mock-meter-01": AttributeValues(
                {
                    "siteId": "mock-site",
                    "airSystemId": "AIR-SYS-MOCK",
                    "declaredDemandKw": 100,
                }
            ),
            "mock-compressor-01": AttributeValues(
                {
                    "siteId": "mock-site",
                    "airSystemId": "AIR-SYS-MOCK",
                    "linkedMeterDeviceId": "mock-meter-01",
                }
            ),
        },
    )


class MockFileIndustrialDataAdapter:
    def __init__(
        self,
        file_path: str | Path | None = None,
        dataset: MockIndustrialDataSet | None = None,
    ):
        if dataset is not None:
            self.dataset = dataset
            return
        if not file_path:
            self.dataset = _demo_dataset()
            return
        path = Path(file_path)
        try:
            self.dataset = MockIndustrialDataSet.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as exc:
            raise IndustrialDataError(f"无法加载 Mock 工业数据文件：{path}") from exc

    @property
    def provider_name(self) -> str:
        return "mock"

    def _ensure_device(self, device_id: str) -> None:
        if not any(device.id.id == device_id for device in self.dataset.devices):
            raise IndustrialDataError(f"设备不存在：{device_id}")

    def list_devices(
        self,
        page: int = 0,
        page_size: int = 100,
        text_search: str = "",
    ) -> IndustrialDevicePage:
        query = text_search.lower().strip()
        devices = [
            device
            for device in self.dataset.devices
            if not query or query in device.name.lower()
        ]
        start = page * page_size
        selected = devices[start : start + page_size]
        total_pages = (len(devices) + page_size - 1) // page_size if devices else 0
        return IndustrialDevicePage(
            data=selected,
            total_pages=total_pages,
            total_elements=len(devices),
            has_next=page + 1 < total_pages,
        )

    def latest_telemetry(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> IndustrialTelemetryHistory:
        self._ensure_device(device_id)
        history = self.dataset.telemetry.get(device_id, IndustrialTelemetryHistory({}))
        selected_keys = keys or list(history)
        return IndustrialTelemetryHistory.model_validate(
            {
                key: [max(history.get(key, []), key=lambda sample: sample.ts)]
                if history.get(key, [])
                else []
                for key in selected_keys
            }
        )

    @staticmethod
    def _aggregate(
        samples: list[IndustrialTelemetrySample],
        start_ts: int,
        interval: int,
        agg: Aggregation,
    ) -> list[IndustrialTelemetrySample]:
        buckets: dict[int, list[float]] = {}
        for sample in samples:
            if isinstance(sample.value, bool) or not isinstance(sample.value, (int, float)):
                continue
            bucket = start_ts + ((sample.ts - start_ts) // interval) * interval
            buckets.setdefault(bucket, []).append(float(sample.value))
        reducers = {
            "AVG": lambda values: sum(values) / len(values),
            "MIN": min,
            "MAX": max,
            "SUM": sum,
            "COUNT": lambda values: float(len(values)),
        }
        reducer = reducers[agg]
        return [
            IndustrialTelemetrySample(ts=ts, value=reducer(values))
            for ts, values in sorted(buckets.items())
        ]

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
        self._ensure_device(device_id)
        source = self.dataset.telemetry.get(device_id, IndustrialTelemetryHistory({}))
        result: dict[str, list[IndustrialTelemetrySample]] = {}
        for key in keys:
            samples = [
                sample
                for sample in source.get(key, [])
                if start_ts <= sample.ts <= end_ts
            ]
            samples.sort(key=lambda sample: sample.ts)
            if agg != "NONE" and interval:
                samples = self._aggregate(samples, start_ts, interval, agg)
            result[key] = samples[:limit]
        return IndustrialTelemetryHistory.model_validate(result)

    def attributes(
        self,
        device_id: str,
        keys: list[str] | None = None,
    ) -> AttributeValues:
        self._ensure_device(device_id)
        values = self.dataset.attributes.get(device_id, AttributeValues({}))
        if not keys:
            return values
        return AttributeValues.model_validate(
            {key: values[key] for key in keys if key in values}
        )

    def list_alarms(
        self,
        device_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> IndustrialAlarmPage:
        self._ensure_device(device_id)
        alarms = self.dataset.alarms.get(device_id, [])
        start = page * page_size
        total_pages = (len(alarms) + page_size - 1) // page_size if alarms else 0
        return IndustrialAlarmPage(
            data=alarms[start : start + page_size],
            total_pages=total_pages,
            total_elements=len(alarms),
            has_next=page + 1 < total_pages,
        )
