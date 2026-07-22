from datetime import UTC, datetime, timedelta

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.capabilities import infer_capabilities
from arthra.compressor.context import CompressorContextBuilder
from arthra.compressor.schemas import CompressorAnalysisRequest, LoadUnloadRateToolInput
from arthra.compressor.tools import analyze_compressor_load_unload_rate_tool
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


class CounterFallbackRepository(FakeCompressorRepository):
    def history(self, device_id, keys, start_ts, end_ts, interval_ms):
        history = super().history(device_id, keys, start_ts, end_ts, interval_ms)
        for key in ("air_comp_running_flag", "air_comp_loaded_flag"):
            if key in history:
                history[key] = []
        return history


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
    assert compressor["start_observation_hours"] == 0.917
    assert compressor["starts_per_hour"] == 2.182
    assert result.metrics["specific_power"]["sample_pairs"] == 10
    assert result.context["data_quality"]["coverage"] == 1.0


def test_idle_warning_uses_longest_continuous_period_not_cumulative_minutes():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(
        llm_api_key="",
        compressor_idle_warning_minutes=15,
    )
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=FakeCompressorRepository(start), settings=settings
        ),
        settings=settings,
    )

    result = service.analyze(
        CompressorAnalysisRequest(
            message="idle running",
            device_scope=["compressor-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=300,
            capabilities=["idle_running"],
        )
    )

    assert result.metrics.devices["compressor-1"].idle_running_minutes == 10.0
    assert result.metrics.devices["compressor-1"].longest_idle_running_minutes == 10.0
    assert not any(
        warning.code == "EXCESSIVE_CONTINUOUS_IDLE_RUNNING"
        for warning in result.warnings
    )


def test_capability_inference_only_selects_requested_advanced_analysis():
    assert infer_capabilities("分析夜间泄漏和节能量") == ["leakage", "savings"]


def test_load_unload_rate_tool_uses_aligned_state_samples():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(
        llm_api_key="",
        compressor_min_data_coverage=0.8,
        compressor_unload_rate_warning_pct=20,
    )
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=FakeCompressorRepository(start),
            settings=settings,
        ),
        settings=settings,
    )

    result = service.analyze_load_unload_rate(
        LoadUnloadRateToolInput(
            device_scope=["compressor-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=300,
        )
    )

    assert result.capability == "load_rate"
    assert result.data_status == "available"
    assert len(result.devices) == 1
    device = result.devices[0]
    assert device.calculation_method == "aligned-state-ratio"
    assert device.load_rate_pct == 80.0
    assert device.unload_rate_pct == 20.0
    assert device.running_minutes == 50.0
    assert device.loaded_minutes == 40.0
    assert device.unloaded_minutes == 10.0
    assert device.sample_coverage == 1.0
    assert device.exceeds_unload_warning_threshold is True
    assert result.warnings[0].code == "HIGH_UNLOAD_RATE"


def test_load_rate_only_does_not_report_unrelated_operation_data_as_missing():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(llm_api_key="")
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=FakeCompressorRepository(start),
            settings=settings,
        ),
        settings=settings,
    )

    result = service.analyze(
        CompressorAnalysisRequest(
            message="只分析加载率和卸载率",
            device_scope=["compressor-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=300,
            capabilities=["load_rate"],
        )
    )

    assert result.capabilities == ["load_rate"]
    assert not any("unloaded_running_flag" in item for item in result.missing_metrics)
    assert not any("start_count" in item for item in result.missing_metrics)
    assert result.metrics.devices["compressor-1"].load_unload_method == "aligned-state-ratio"


def test_load_unload_rate_falls_back_to_cumulative_hour_deltas():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(llm_api_key="")
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=CounterFallbackRepository(start),
            settings=settings,
        ),
        settings=settings,
    )

    result = service.analyze_load_unload_rate(
        LoadUnloadRateToolInput(
            device_scope=["compressor-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=300,
        )
    )

    device = result.devices[0]
    assert result.data_status == "available"
    assert device.calculation_method == "cumulative-hours-delta"
    assert device.load_rate_pct == 72.73
    assert device.unload_rate_pct == 27.27
    assert device.running_minutes == 52.8
    assert device.loaded_minutes == 38.4


def test_load_unload_rate_tool_has_strict_json_schema():
    schema = analyze_compressor_load_unload_rate_tool.args_schema.model_json_schema()

    assert analyze_compressor_load_unload_rate_tool.name == "analyze_compressor_load_unload_rate"
    assert schema["additionalProperties"] is False
    assert "device_scope" in schema["required"]


def test_pressure_tools_keep_fluctuation_and_high_pressure_conclusions_isolated():
    start = datetime(2026, 7, 16, tzinfo=UTC)
    settings = Settings(
        llm_api_key="",
        compressor_max_pressure_mpa=0.7,
        compressor_pressure_fluctuation_warning_mpa=0.01,
    )
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=FakeCompressorRepository(start),
            settings=settings,
        ),
        settings=settings,
    )
    common = {
        "device_scope": ["compressor-1"],
        "start_at": start,
        "end_at": start + timedelta(hours=1),
        "interval_seconds": 300,
    }

    fluctuation = service.analyze(
        CompressorAnalysisRequest(
            message="只分析压力波动",
            capabilities=["pressure_fluctuation"],
            **common,
        )
    )
    high_pressure = service.analyze(
        CompressorAnalysisRequest(
            message="只分析供气压力过高",
            capabilities=["high_pressure"],
            **common,
        )
    )

    assert {warning.code for warning in fluctuation.warnings} == {"PRESSURE_FLUCTUATION"}
    assert {warning.code for warning in high_pressure.warnings} == {"HIGH_SUPPLY_PRESSURE"}
    assert fluctuation.capabilities == ["pressure_fluctuation"]
    assert high_pressure.capabilities == ["high_pressure"]
