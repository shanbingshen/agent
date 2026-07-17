from datetime import UTC, datetime, timedelta

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.capabilities import infer_capabilities
from arthra.compressor.context import CompressorContextBuilder
from arthra.compressor.schemas import CompressorAnalysisRequest
from arthra.config import Settings


class FakeCompressorRepository:
    def __init__(self, start: datetime, interval_seconds: int = 300):
        self.timestamps = [
            int((start + timedelta(seconds=index * interval_seconds)).timestamp() * 1000)
            for index in range(12)
        ]

    def catalog(self):
        return [
            {
                "device_id": "compressor-1",
                "device_name": "Compressor 1",
                "device_type": "compressor",
                "attributes": {
                    "airSystemId": "AIR-SYS-01",
                    "linkedMeterDeviceId": "meter-1",
                },
            },
            {
                "device_id": "meter-1",
                "device_name": "Meter 1",
                "device_type": "meter",
                "attributes": {"airSystemId": "AIR-SYS-01"},
            },
        ]

    def latest(self, device_id, keys):
        values = {key: 1 for key in keys}
        timestamps = {key: self.timestamps[-1] for key in keys}
        return values, timestamps

    def history(self, device_id, keys, start_ts, end_ts, interval_ms):
        patterns = {
            "air_comp_running_flag": [1] * 10 + [0, 0],
            "air_comp_loaded_flag": [1] * 8 + [0, 0, 0, 0],
            "air_comp_unloaded_running_flag": [0] * 8 + [1, 1, 0, 0],
            "air_comp_running_hours": [100 + index * 0.08 for index in range(12)],
            "air_comp_loading_hours": [80 + min(index, 8) * 0.08 for index in range(12)],
            "air_comp_start_count": [315] * 4 + [316] * 4 + [317] * 4,
            "air_comp_supply_pressure": [0.69, 0.7, 0.71, 0.72, 0.73, 0.74, 0.72, 0.7, 0.68, 0.69, 0.05, 0.05],
            "air_system_header_pressure_mpa": [0.66, 0.67, 0.68, 0.69, 0.7, 0.71, 0.69, 0.67, 0.65, 0.66, 0.05, 0.05],
            "air_comp_main_current_a": [120] * 8 + [40, 40, 0, 0],
            "air_comp_fad_flow_m3_min": [18] * 8 + [1, 1, 0, 0],
            "meter_TotW": [100] * 8 + [35, 35, 3, 3],
            "meter_SupWh": [1000 + index * 8 for index in range(12)],
        }
        return {
            key: [
                {"ts": timestamp, "value": value}
                for timestamp, value in zip(self.timestamps, patterns.get(key, [1] * 12), strict=True)
            ]
            for key in keys
        }

    def alarms(self, device_id):
        return []


def test_context_layer_links_meter_and_computes_core_capabilities():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(
        llm_api_key="",
        compressor_min_data_coverage=0.8,
        compressor_idle_warning_minutes=5,
    )
    builder = CompressorContextBuilder(
        repository=FakeCompressorRepository(start), settings=settings
    )
    service = CompressorAnalysisService(context_builder=builder, settings=settings)
    request = CompressorAnalysisRequest(
        message="综合分析空压机加载率、空载、启停、压力波动和比功率",
        device_scope=["compressor-1"],
        start_at=start,
        end_at=start + timedelta(hours=1),
        interval_seconds=300,
    )
    result = service.analyze(request)

    assert result.data_status == "available"
    assert result.context["air_system_id"] == "AIR-SYS-01"
    assert len(result.context["devices"]) == 2
    compressor = result.metrics["devices"]["compressor-1"]
    assert compressor["load_rate_pct"] == 80.0
    assert compressor["unload_rate_pct"] == 20.0
    assert compressor["idle_running_minutes"] == 10.0
    assert compressor["longest_idle_running_minutes"] == 10.0
    assert compressor["start_count"] == 2
    assert result.metrics["specific_power"]["sample_pairs"] == 10
    assert result.context["data_quality"]["coverage"] == 1.0


def test_capability_inference_only_selects_requested_advanced_analysis():
    assert infer_capabilities("分析夜间泄漏和节能量") == ["leakage", "savings"]
