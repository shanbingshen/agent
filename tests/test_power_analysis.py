from datetime import UTC, datetime, timedelta

import pytest
from arthra.agent import RouteDecision, build_graph
from arthra.config import Settings
from arthra.contracts import AttributeValues, TelemetryValues, TimestampValues
from arthra.industrial_data.adapters.thingsboard import (
    ThingsBoardIndustrialDataAdapter,
)
from arthra.industrial_data.schemas import IndustrialTelemetryHistory
from arthra.power.analysis import PowerAnalysisService
from arthra.power.context import PowerContextBuilder
from arthra.power.schemas import PowerAnalysisRequest
from arthra.power.tools import POWER_GRAPH_TOOLS, POWER_TOOLS
from arthra.thingsboard_schemas import DeviceCatalogItem


class FakePowerRepository:
    def __init__(self, start: datetime):
        self.timestamps = [
            int((start + timedelta(minutes=index)).timestamp() * 1000)
            for index in range(60)
        ]

    def catalog(self):
        return [
            DeviceCatalogItem(
                device_id="meter-1",
                device_name="Meter 1",
                device_type="meter",
                attributes=AttributeValues({"declaredDemandKw": 100.0}),
            )
        ]

    def latest(self, device_id, keys):
        return (
            TelemetryValues({key: 1.0 for key in keys}),
            TimestampValues({key: self.timestamps[-1] for key in keys}),
        )

    def history(self, device_id, keys, start_ts, end_ts, interval_ms):
        patterns = {
            "meter_TotW": [80.0] * 30 + [120.0] * 15 + [80.0] * 15,
            "meter_LinV_phsAB": [400.0] * 10 + [380.0] * 50,
            "meter_LinV_phsBC": [380.0] * 60,
            "meter_LinV_phsCA": [380.0] * 60,
            "meter_ImbNgV": [3.0] * 5 + [0.8] * 55,
            "meter_ImbNgA": [12.0] * 5 + [4.0] * 55,
            "meter_TotPF": [0.85] * 7 + [0.96] * 53,
            "meter_ThdPhV_phsA": [6.0] * 6 + [2.0] * 54,
            "meter_ThdPhV_phsB": [2.0] * 60,
            "meter_ThdPhV_phsC": [2.0] * 60,
            "meter_ThdA_phsA": [8.0] * 60,
            "meter_ThdA_phsB": [8.0] * 60,
            "meter_ThdA_phsC": [18.0] * 4 + [8.0] * 56,
        }
        for order, ratio in ((3, 1.8), (5, 1.2), (7, 0.6)):
            for phase in ("A", "B", "C"):
                patterns[f"meter_ThdPhV{order}_phs{phase}"] = [ratio] * 60
                patterns[f"meter_ThdA{order}_phs{phase}"] = [ratio * 4] * 60
        return IndustrialTelemetryHistory.model_validate(
            {
                key: [
                    {"ts": timestamp, "value": value}
                    for timestamp, value in zip(
                        self.timestamps,
                        patterns.get(key, [1.0] * 60),
                        strict=True,
                    )
                ]
                for key in keys
            }
        )


@pytest.fixture
def power_service():
    start = datetime.now(UTC) - timedelta(hours=1)
    settings = Settings(
        llm_api_key="",
        power_min_data_coverage=0.8,
        power_declared_demand_kw=100,
    )
    return (
        PowerAnalysisService(
            context_builder=PowerContextBuilder(
                repository=FakePowerRepository(start),
                settings=settings,
            ),
            settings=settings,
        ),
        start,
    )


def test_demand_tools_compute_rolling_peak_ratio_and_exceedance(power_service):
    service, start = power_service
    result = service.analyze(
        PowerAnalysisRequest(
            message="分析15分钟最大需量、峰值、峰均比和申报需量越限",
            device_scope=["meter-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=60,
            capabilities=[
                "demand_15m",
                "peak_detection",
                "peak_average_ratio",
                "declared_demand_exceedance",
            ],
        )
    )

    metric = result.metrics.demand["meter-1"]
    assert metric.max_demand_15m_kw == 120.0
    assert metric.average_load_kw == 90.0
    assert metric.peak_average_ratio == pytest.approx(1.3333)
    assert metric.exceedance_kw == 20.0
    assert metric.exceedance_total_minutes > 0
    assert any(warning.code == "DECLARED_DEMAND_EXCEEDED" for warning in result.warnings)


def test_power_quality_tools_use_thresholds_and_duration(power_service):
    service, start = power_service
    result = service.analyze(
        PowerAnalysisRequest(
            message="分析电压偏差、三相不平衡、功率因数、THD、谐波和异常持续时间",
            device_scope=["meter-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=60,
            capabilities=[
                "voltage_deviation",
                "phase_imbalance",
                "power_factor",
                "thd",
                "harmonics",
                "abnormal_duration",
            ],
        )
    )

    metric = result.metrics.quality["meter-1"]
    assert metric.voltage_deviation["AB"].abnormal_total_minutes == 10
    assert metric.voltage_unbalance.abnormal_total_minutes == 5
    assert metric.current_unbalance.abnormal_total_minutes == 5
    assert metric.power_factor.abnormal_total_minutes == 7
    assert metric.thdu["A"].abnormal_total_minutes == 6
    assert metric.thdi["C"].abnormal_total_minutes == 4
    assert metric.dominant_voltage_harmonic_order == 3
    assert metric.dominant_current_harmonic_order == 3
    assert any(item.code == "LOW_POWER_FACTOR" for item in metric.abnormal_durations)


def test_all_power_tools_expose_strict_schemas_and_graph_hides_context():
    assert len(POWER_TOOLS) == 13
    assert len(POWER_GRAPH_TOOLS) == 13
    for direct_tool in POWER_TOOLS:
        schema = direct_tool.args_schema.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "device_scope" in schema["required"]
    for graph_tool in POWER_GRAPH_TOOLS:
        schema = graph_tool.tool_call_schema.model_json_schema()
        assert "context" not in schema.get("properties", {})


def test_production_graph_runs_power_tool_node(monkeypatch, power_service):
    service, start = power_service
    context = service.context_builder.build(
        PowerAnalysisRequest(
            message="计算15分钟最大需量",
            device_scope=["meter-1"],
            start_at=start,
            end_at=start + timedelta(hours=1),
            interval_seconds=60,
            capabilities=["demand_15m"],
        )
    )

    class FakeBuilder:
        def __init__(self, settings=None):
            pass

        def build(self, request):
            return context

    monkeypatch.setattr("arthra.agent.PowerContextBuilder", FakeBuilder)
    monkeypatch.setattr("arthra.agent.get_settings", lambda: service.settings)
    graph = build_graph(
        route_classifier=lambda message, scope: RouteDecision(
            route="power",
            confidence=0.99,
            reason="明确询问需量",
            capabilities=["demand_15m"],
            source="qwen",
        )
    )
    result = graph.invoke(
        {"message": "计算15分钟最大需量", "device_scope": ["meter-1"]},
        {"configurable": {"thread_id": "power-tool-node-test"}},
    )

    assert result["route"] == "power"
    assert result["analysis"].method == "power-deterministic-first"
    assert result["analysis"].metrics.demand["meter-1"].max_demand_15m_kw == 120
    assert "15分钟最大需量" in result["response"]


def test_power_repository_splits_large_thingsboard_interval_queries():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def telemetry_history(
            self,
            device_id,
            keys,
            start_ts,
            end_ts,
            limit=1000,
            agg="NONE",
            interval=None,
        ):
            kwargs = {
                "device_id": device_id,
                "keys": keys,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "limit": limit,
                "agg": agg,
                "interval": interval,
            }
            self.calls.append(kwargs)
            assert (kwargs["end_ts"] - kwargs["start_ts"]) // kwargs["interval"] < 480
            return IndustrialTelemetryHistory.model_validate({
                key: [{"ts": kwargs["start_ts"], "value": 100.0}]
                for key in kwargs["keys"]
            })

    client = FakeClient()
    adapter = ThingsBoardIndustrialDataAdapter(client=client)
    history = adapter.telemetry_history(
        device_id="meter-1",
        keys=["meter_TotW"],
        start_ts=0,
        end_ts=24 * 60 * 60 * 1000,
        interval=60_000,
        agg="AVG",
    )

    assert len(client.calls) == 4
    assert len(history["meter_TotW"]) == 4
