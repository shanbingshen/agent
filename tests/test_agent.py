from arthra.agent import (
    AgentState,
    RouteDecision,
    build_graph,
    classify_route,
    route_message,
    synthesize,
)
from arthra.compressor.schemas import (
    CompressorAnalysisResult,
    CompressorDeviceMetrics,
    CompressorMetrics,
    CompressorSystemContext,
    DataQuality,
    SavingsMetrics,
)
from arthra.config import Settings
from arthra.contracts import AnalysisWarning
from arthra.power.schemas import (
    DemandMetrics,
    PowerAnalysisResult,
    PowerContextMeterSummary,
    PowerContextSummary,
    PowerDataQuality,
    PowerMetrics,
)
from langchain_core.messages import ToolMessage


def test_routes_all_experts():
    assert route_message("生成本周报告") == "report"
    assert route_message("预测明天的负荷趋势") == "forecast"
    assert route_message("空压机压力异常") == "compressor"
    assert route_message("分析电表功率") == "power"
    assert route_message("EMS 储能状态") == "ems"
    assert route_message("你好") == "conversation"
    assert route_message("帮我写一首诗") == "conversation"


def test_greeting_uses_conversation_without_calling_model(monkeypatch):
    class UnexpectedModel:
        def __init__(self, **kwargs):
            raise AssertionError("问候不应调用模型")

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(llm_api_key="test-key", supervisor_semantic_routing_enabled=True),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", UnexpectedModel)

    decision = classify_route("你好", ["device-1"])

    assert decision.route == "conversation"
    assert decision.source == "keyword"


def test_semantic_route_sends_unrelated_question_to_conversation(monkeypatch):
    class FakeResponse:
        content = (
            '{"route":"conversation","confidence":0.98,'
            '"reason":"问题与工业能源无关","capabilities":[]}'
        )

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

    decision = classify_route("帮我推荐一部电影", ["device-1"])

    assert decision.route == "conversation"
    assert decision.source == "keyword"
    assert decision.intent == "OUT_OF_DOMAIN"


def test_conversation_graph_does_not_read_devices_or_run_expert_tools(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))

    def unexpected_loader(device_ids):
        raise AssertionError("闲聊与越界问题不应读取工业数据")

    graph = build_graph(telemetry_loader=unexpected_loader)
    result = graph.invoke(
        {"message": "今天天气怎么样", "device_scope": ["device-1"]},
        {"configurable": {"thread_id": "conversation-boundary-test"}},
    )

    assert result["route"] == "conversation"
    assert result["analysis"] is None
    assert result["warnings"] == []
    assert "不属于当前工业能源分析范围" in result["response"]


def test_model_identity_uses_product_identity_without_exposing_base_model(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(telemetry_loader=lambda ids: [])

    result = graph.invoke(
        {"message": "你是什么模型", "device_scope": []},
        {"configurable": {"thread_id": "product-identity-test"}},
    )

    assert result["route"] == "conversation"
    assert "AethraVista" in result["response"]
    assert "基础模型版本由系统管理员配置" in result["response"]


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


def test_registered_question_skips_semantic_model_even_when_it_would_return_invalid_route(
    monkeypatch,
):
    class FakeResponse:
        content = '{"route":"invented_expert","confidence":0.99,"reason":"invalid"}'

    class FakeModel:
        def __init__(self, **kwargs):
            raise AssertionError("已登记问法不应再调用语义模型")

        def invoke(self, prompt):
            raise AssertionError("已登记问法不应再调用语义模型")

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(llm_api_key="test-key", supervisor_semantic_routing_enabled=True),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FakeModel)

    decision = classify_route("分析电表功率", ["device-1"])

    assert decision.route == "power"
    assert decision.source == "keyword"
    assert decision.intent == "GENERAL_POWER_ANALYSIS"


def test_semantic_route_applies_deterministic_domain_guard(monkeypatch):
    class FakeResponse:
        content = '{"route":"ems","confidence":0.96,"reason":"general energy request","capabilities":[]}'

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

    decision = classify_route("analyze compressor load rate", ["compressor-1"])

    assert decision.route == "compressor"
    assert decision.source == "hybrid_guard"
    assert decision.confidence == 0.96


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


def test_production_compressor_branch_executes_selected_tools_through_tool_node(monkeypatch):
    context_requests = []

    class FakeContextBuilder:
        def __init__(self, **kwargs):
            pass

        def build(self, request):
            context_requests.append(request)
            return CompressorSystemContext(
                air_system_id="AIR-SYS-TEST",
                start_ts=int(request.start_at.timestamp() * 1000),
                end_ts=int(request.end_at.timestamp() * 1000),
                interval_seconds=request.interval_seconds,
                capabilities=request.capabilities,
                requested_device_scope=request.device_scope,
                devices=[],
                data_quality=DataQuality(coverage=1),
            )

    monkeypatch.setattr("arthra.agent.CompressorContextBuilder", FakeContextBuilder)
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    graph = build_graph(
        route_classifier=lambda message, scope: RouteDecision(
            route="compressor",
            confidence=0.99,
            reason="test",
            capabilities=["load_rate"],
        )
    )

    result = graph.invoke(
        {
            "message": "分析加载率和压力波动",
            "device_scope": ["compressor-1"],
        },
        {"configurable": {"thread_id": "tool-node-test"}},
    )

    assert result["compressor_execution"] == "tools"
    assert result["selected_capabilities"] == ["load_rate", "pressure_fluctuation"]
    assert len(context_requests) == 1
    assert context_requests[0].device_scope == ["compressor-1"]
    assert context_requests[0].capabilities == ["load_rate", "pressure_fluctuation"]
    assert result["analysis"].capabilities == ["load_rate", "pressure_fluctuation"]
    assert result["tool_results"] == []
    assert [message for message in result["messages"] if isinstance(message, ToolMessage)] == []


def test_compressor_expert_uses_configured_qwen_after_deterministic_analysis(monkeypatch):
    calls = []

    class FakeResponse:
        content = "优先核查卸载时段，并在证据充分后创建待审批计划。"

    class FakeModel:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def invoke(self, messages):
            calls.append(("invoke", messages))
            return FakeResponse()

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(
            llm_api_key="test-key",
            llm_model="qwen-default",
            compressor_expert_llm_model="qwen-compressor",
        ),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FakeModel)
    state = AgentState(
        message="分析空压机加载率",
        device_scope=["compressor-1"],
        analysis=CompressorAnalysisResult(
            data_status="available",
            capabilities=["load_rate"],
            findings=["运行期间加载率 80.00%，卸载率 20.00%。"],
            confidence=1,
        ),
    )

    response = synthesize(state)["response"]

    assert "运行期间加载率 80.00%" in response
    assert "> 专家补充：" in response
    assert "qwen-compressor" not in response
    assert "优先核查卸载时段" in response
    assert calls[0][1]["model"] == "qwen-compressor"
    prompt = str(calls[1][1])
    assert "customer_report" in prompt
    assert "不能重新计算" in prompt


def test_compressor_savings_question_does_not_invent_electricity_cost(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    state = AgentState(
        message="空压异常造成多少电费浪费？",
        device_scope=["compressor-1"],
        route="compressor",
        route_decision=RouteDecision(
            route="compressor",
            intent="COMPRESSOR_SAVINGS_ESTIMATE",
            confidence=1,
            reason="已登记问答意图",
            capabilities=["savings"],
            source="keyword",
        ),
        analysis=CompressorAnalysisResult(
            data_status="available",
            query="空压异常造成多少电费浪费？",
            capabilities=["savings"],
            metrics=CompressorMetrics(
                savings_screening=SavingsMetrics(
                    screening_savings_kwh=50,
                    unloaded_energy_kwh=100,
                    assumed_reducible_fraction=0.5,
                    method="unloaded-energy-screening",
                )
            ),
            confidence=1,
        ),
    )

    response = synthesize(state)["response"]

    assert "预计可优化约 50.00 kWh" in response
    assert "未配置分时电价或综合电价" in response
    assert "不能换算为电费金额" in response


def test_power_expert_uses_configured_qwen_after_deterministic_analysis(monkeypatch):
    models = []

    class FakeResponse:
        content = "需量仍在确定性阈值内，继续监测即可。"

    class FakeModel:
        def __init__(self, **kwargs):
            models.append(kwargs["model"])

        def invoke(self, messages):
            return FakeResponse()

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(
            llm_api_key="test-key",
            llm_model="qwen-default",
            power_expert_llm_model="qwen-power",
        ),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FakeModel)
    state = AgentState(
        message="分析15分钟最大需量",
        device_scope=["meter-1"],
        analysis=PowerAnalysisResult(
            data_status="available",
            capabilities=["demand_15m"],
            findings=["15分钟最大需量为 95.15 kW。"],
            confidence=1,
        ),
    )

    response = synthesize(state)["response"]

    assert "15分钟最大需量为 95.15 kW" in response
    assert "> 专家补充：" in response
    assert "qwen-power" not in response
    assert "需量仍在确定性阈值内" in response
    assert models == ["qwen-power"]


def test_specialist_model_failure_keeps_deterministic_response(monkeypatch):
    class FailingModel:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "arthra.agent.get_settings",
        lambda: Settings(llm_api_key="test-key", llm_model="qwen-test"),
    )
    monkeypatch.setattr("arthra.agent.ChatOpenAI", FailingModel)
    state = AgentState(
        message="分析功率因数",
        device_scope=["meter-1"],
        analysis=PowerAnalysisResult(
            data_status="available",
            capabilities=["power_factor"],
            findings=["功率因数 0.955。"],
            confidence=1,
        ),
    )

    response = synthesize(state)["response"]

    assert "功率因数 0.955" in response
    assert "千问专家解读" not in response


def test_customer_power_report_uses_rolling_demand_and_hides_internal_details(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    device_id = "758c0910-80df-11f1-923e-079ec8900b28"
    context = PowerContextSummary(
        start_ts=1_752_988_800_000,
        end_ts=1_753_075_200_000,
        interval_seconds=60,
        meters=[
            PowerContextMeterSummary(
                device_id=device_id,
                device_name="Arthra-Meter-01",
                declared_demand_kw=100,
            )
        ],
        data_quality=PowerDataQuality(coverage=1, expected_series=1, available_series=1),
    )
    analysis = PowerAnalysisResult(
        data_status="available",
        capabilities=["demand_15m", "peak_average_ratio", "phase_imbalance"],
        context=context,
        metrics=PowerMetrics(
            demand={
                device_id: DemandMetrics(
                    average_load_kw=88.91,
                    max_demand_15m_kw=95.65,
                    instantaneous_peak_kw=105.066,
                    peak_average_ratio=1.1817,
                    declared_demand_kw=100,
                )
            }
        ),
        warnings=[
            AnalysisWarning(
                severity="medium",
                code="CURRENT_UNBALANCE",
                metric="meter_ImbNgA",
                value=87.727,
                device_id=device_id,
                device_name="Arthra-Meter-01",
                message="电流不平衡度触发平台内部预警阈值，疑似异常，需现场核验",
            )
        ],
        confidence=1,
    )

    response = synthesize(
        AgentState(
            message="分析用电负荷和需量",
            device_scope=[device_id],
            presentation_mode="customer",
            analysis=analysis,
        )
    )["response"]

    assert "当前未发生15分钟需量越限" in response
    assert "需量利用率：95.65%" in response
    assert "剩余安全余量：4.35 kW" in response
    assert "最高60秒平均功率：105.07 kW" in response
    assert "不等于计费需量越限" in response
    assert "疑似异常" in response
    assert "结论可信度：中高" in response
    assert device_id not in response
    assert "CURRENT_UNBALANCE" not in response
    assert "meter_ImbNgA" not in response
    assert "qwen" not in response.lower()


def test_debug_power_report_exposes_technical_details_for_admin_view(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))
    device_id = "meter-debug-id"
    analysis = PowerAnalysisResult(
        data_status="available",
        capabilities=["demand_15m"],
        metrics=PowerMetrics(demand={device_id: DemandMetrics(declared_demand_kw=100)}),
        warnings=[AnalysisWarning(severity="medium", code="DEBUG_RULE", message="调试告警")],
    )

    response = synthesize(
        AgentState(
            message="调试需量",
            device_scope=[device_id],
            presentation_mode="debug",
            analysis=analysis,
        )
    )["response"]

    assert "管理员技术详情" in response
    assert "DEBUG_RULE" in response
    assert device_id in response
