from arthra.agent import AgentState, RouteDecision, build_graph, classify_route, route_message
from arthra.compressor.schemas import (
    CompressorAnalysisResult,
    CompressorDeviceMetrics,
    CompressorMetrics,
)
from arthra.config import Settings


def test_routes_all_experts():
    assert route_message("生成本周报告") == "report"
    assert route_message("预测明天的负荷趋势") == "forecast"
    assert route_message("空压机压力异常") == "compressor"
    assert route_message("分析电表功率") == "power"
    assert route_message("EMS 储能状态") == "ems"


def test_semantic_route_uses_validated_qwen_decision(monkeypatch):
    class FakeResponse:
        content = """```json
        {"route":"compressor","confidence":0.94,"reason":"涉及卸载和供气","capabilities":["idle_running"]}
        ```"""

    class FakeModel:
        def __init__(self, **kwargs):
            assert kwargs["temperature"] == 0

        def invoke(self, prompt):
            assert "JSON Schema" in str(prompt)
            return FakeResponse()

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(llm_api_key="test-key", supervisor_semantic_routing_enabled=True),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FakeModel)

    decision = classify_route("1号机最近一直卸载，帮我看看供气情况", ["device-1"])

    assert decision.route == "compressor"
    assert decision.source == "qwen"
    assert decision.capabilities == ["idle_running"]


def test_semantic_route_falls_back_when_model_returns_invalid_route(monkeypatch):
    class FakeResponse:
        content = '{"route":"invented_expert","confidence":0.99,"reason":"invalid"}'

    class FakeModel:
        def __init__(self, **kwargs):
            pass

        def invoke(self, prompt):
            return FakeResponse()

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(llm_api_key="test-key", supervisor_semantic_routing_enabled=True),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FakeModel)

    decision = classify_route("分析电表功率", ["device-1"])

    assert decision.route == "power"
    assert decision.source == "keyword_fallback"
    assert "ValidationError" in decision.reason


def test_graph_accepts_injected_semantic_classifier(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        telemetry_loader=lambda ids: [],
        route_classifier=lambda message, ids: RouteDecision(
            route="compressor",
            confidence=0.92,
            reason="语义识别为空压系统",
            source="qwen",
        ),
    )

    result = graph.invoke(
        {"message": "帮我看看这台机器为什么一直卸载", "device_scope": []},
        {"configurable": {"thread_id": "semantic-router-test"}},
    )

    assert result["route"] == "compressor"
    assert result["route_decision"]["source"] == "qwen"


def test_graph_runs_without_model_key(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        telemetry_loader=lambda ids: [
            {
                "id": "compressor-1",
                "name": "Compressor 1",
                "type": "compressor",
                "telemetry": {
                    "power_kw": 80.0,
                    "pressure_bar": 7.2,
                    "temperature_c": 65.0,
                    "running": True,
                },
                "timestamps": {},
            }
        ] if ids else []
    )
    result = graph.invoke({"message": "空压机分析", "device_scope": []}, {"configurable": {"thread_id": "test"}})
    assert result["route"] == "compressor"
    assert "选择至少一台设备" in result["response"]


def test_graph_uses_selected_device_telemetry(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        telemetry_loader=lambda ids: [
            {
                "id": ids[0],
                "name": "Arthra-Compressor-01",
                "type": "compressor",
                "telemetry": {"power_kw": 81.5, "pressure_bar": 7.4, "temperature_c": 66.0, "running": True},
                "timestamps": {},
            }
        ]
    )
    result = graph.invoke(
        {"message": "分析空压机", "device_scope": ["compressor-1"]},
        {"configurable": {"thread_id": "telemetry-test"}},
    )
    assert result["analysis"]["data_status"] == "available"
    assert any("7.40 bar" in finding for finding in result["analysis"]["findings"])
    assert "81.50 kW" in result["response"]


def test_graph_can_use_compressor_context_analyzer(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        telemetry_loader=lambda ids: [],
        compressor_analyzer=lambda message, ids: CompressorAnalysisResult(
            data_status="available",
            capabilities=["load_rate"],
            findings=["运行期间加载率 80.00%"],
            metrics=CompressorMetrics(
                devices={
                    "compressor-1": CompressorDeviceMetrics(
                        device_name="Compressor 1",
                        load_rate_pct=80,
                        unload_rate_pct=20,
                    )
                }
            ),
        ),
    )
    result = graph.invoke(
        {"message": "分析空压机加载率", "device_scope": ["compressor-1"]},
        {"configurable": {"thread_id": "context-layer-test"}},
    )
    assert result["analysis"].metrics.devices["compressor-1"].load_rate_pct == 80
    assert "加载率 80.00%" in result["response"]


def test_agent_state_discriminates_compressor_analysis_by_method():
    state = AgentState.model_validate(
        {
            "message": "分析加载率",
            "analysis": {
                "expert": "compressor",
                "title": "空压机系统分析",
                "data_status": "available",
                "method": "context-deterministic-first",
                "query": "分析加载率",
                "capabilities": ["load_rate"],
                "metrics": {
                    "devices": {
                        "compressor-1": {
                            "device_name": "Compressor 1",
                            "load_rate_pct": 80,
                            "unload_rate_pct": 20,
                        }
                    }
                },
                "findings": [],
                "warnings": [],
                "missing_metrics": [],
                "recommendations": [],
                "assumptions": [],
                "confidence": 1,
            },
        }
    )

    assert isinstance(state.analysis, CompressorAnalysisResult)
    assert state.analysis.query == "分析加载率"
    assert state.schema_version == "2.0"


def test_same_thread_can_run_twice_with_pydantic_state(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        telemetry_loader=lambda ids: [
            {
                "id": ids[0],
                "name": "Arthra-Meter-01",
                "type": "meter",
                "telemetry": {"meter_TotW": 100.0},
            }
        ]
    )
    config = {
        "configurable": {
            "thread_id": "pydantic-multi-turn",
            "checkpoint_ns": "arthra-agent-v2",
        }
    }

    first = graph.invoke(
        {"message": "分析电表功率", "device_scope": ["meter-1"]},
        config,
    )
    second = graph.invoke(
        {"message": "继续分析当前电力状态", "device_scope": ["meter-1"]},
        config,
    )

    assert first["route"] == "power"
    assert second["route"] == "power"
    assert second["analysis"].method == "deterministic-first"
