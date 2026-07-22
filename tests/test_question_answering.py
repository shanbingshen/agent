from datetime import UTC, datetime, timedelta

import pytest
from arthra.agent import (
    AgentState,
    RouteDecision,
    plan_compressor_tools,
    plan_power_tools,
)
from arthra.question_answering import (
    INTENTS,
    classify_question,
    device_name_matches_ordinal,
    extract_device_reference,
    resolve_time_range,
)


@pytest.mark.parametrize(
    ("question", "intent", "route", "capabilities"),
    [
        ("当前全厂有功功率是多少？", "REALTIME_POWER_QUERY", "power", ["realtime_power"]),
        ("昨天用了多少电？", "ENERGY_PERIOD_QUERY", "power", ["energy_consumption"]),
        ("昨天比前天多用了多少电？", "ENERGY_PERIOD_COMPARE", "power", ["energy_compare"]),
        ("昨天什么时候用电负荷最高？", "PEAK_LOAD_QUERY", "power", ["peak_detection"]),
        (
            "今天会不会超过申报需量？",
            "DEMAND_RISK_QUERY",
            "power",
            ["demand_15m", "declared_demand_exceedance"],
        ),
        (
            "分析这台电表过去24小时的15分钟最大需量和峰均比",
            "DEMAND_PEAK_AVERAGE_ANALYSIS",
            "power",
            ["demand_15m", "peak_average_ratio"],
        ),
        ("3号电表三相电流不平衡吗？", "CURRENT_UNBALANCE_ANALYSIS", "power", ["phase_imbalance"]),
        ("昨天电压有没有越限？", "VOLTAGE_VIOLATION_ANALYSIS", "power", ["voltage_deviation"]),
        ("1号空压机现在运行正常吗？", "COMPRESSOR_STATUS_QUERY", "compressor", ["realtime_status"]),
        ("1号空压机昨天卸载严重吗？", "COMPRESSOR_UNLOAD_ANALYSIS", "compressor", ["load_rate"]),
        (
            "2号空压机最近是否频繁启停？",
            "COMPRESSOR_FREQUENT_START_STOP",
            "compressor",
            ["frequent_start"],
        ),
        (
            "昨天管网压力波动大吗？",
            "COMPRESSOR_PRESSURE_FLUCTUATION",
            "compressor",
            ["pressure_fluctuation"],
        ),
        ("空压机比功率是多少？", "COMPRESSOR_SPECIFIC_POWER", "compressor", ["specific_power"]),
        ("你好", "GREETING", "conversation", []),
        ("帮我推荐一部电影", "OUT_OF_DOMAIN", "conversation", []),
    ],
)
def test_registered_questions_have_exact_routes_and_tool_whitelists(
    question,
    intent,
    route,
    capabilities,
):
    definition = classify_question(question)

    assert definition is not None
    assert definition.intent == intent
    assert definition.route == route
    assert definition.capabilities == capabilities
    assert definition.max_tool_calls == len(capabilities)
    assert definition.max_tool_calls <= 4


def test_peak_question_plans_only_peak_detection_tool():
    state = AgentState(
        message="昨天什么时候用电负荷最高？",
        device_scope=["meter-1"],
        route="power",
        route_decision=RouteDecision(
            route="power",
            intent="PEAK_LOAD_QUERY",
            confidence=1,
            reason="已登记问答意图",
            capabilities=["peak_detection"],
            source="keyword",
        ),
    )

    planned = plan_power_tools(state)

    assert planned["power_execution"] == "tools"
    assert planned["selected_power_capabilities"] == ["peak_detection"]
    assert planned["query_time_range"].label == "昨日00:00—24:00"


def test_compressor_unload_question_plans_only_load_rate_tool():
    state = AgentState(
        message="1号空压机昨天卸载严重吗？",
        device_scope=["compressor-1"],
        route="compressor",
        route_decision=RouteDecision(
            route="compressor",
            intent="COMPRESSOR_UNLOAD_ANALYSIS",
            confidence=1,
            reason="已登记问答意图",
            capabilities=["load_rate"],
            source="keyword",
        ),
    )

    planned = plan_compressor_tools(state)

    assert planned["compressor_execution"] == "tools"
    assert planned["selected_capabilities"] == ["load_rate"]
    assert planned["query_time_range"].label == "昨日00:00—24:00"


def test_yesterday_time_range_uses_complete_local_calendar_day():
    now = datetime(2026, 7, 20, 2, 30, tzinfo=UTC)

    result = resolve_time_range("昨天用了多少电", timezone_name="Asia/Shanghai", now=now)

    assert result.start_at == datetime(2026, 7, 18, 16, 0, tzinfo=UTC)
    assert result.end_at == datetime(2026, 7, 19, 16, 0, tzinfo=UTC)
    assert result.end_at - result.start_at == timedelta(hours=24)
    assert result.defaulted is False


def test_missing_time_range_is_explicitly_marked_as_default():
    result = resolve_time_range(
        "分析1号空压机卸载情况",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 20, 2, 30, tzinfo=UTC),
    )

    assert result.label == "最近24小时（默认）"
    assert result.defaulted is True


def test_explicit_device_ordinal_is_parsed_without_guessing_nearest_device():
    reference = extract_device_reference("分析3号电表昨天的三相不平衡")

    assert reference is not None
    assert reference.kind == "meter"
    assert reference.ordinal == 3
    assert device_name_matches_ordinal("Arthra-Meter-03", 3)
    assert not device_name_matches_ordinal("Arthra-Meter-01", 3)


def test_all_registered_intents_obey_tool_call_limit():
    for definition in INTENTS.values():
        assert definition.max_tool_calls == len(definition.capabilities)
        assert definition.max_tool_calls <= 4
