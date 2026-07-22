import pytest
from arthra.compressor.schemas import CompressorAnalysisResult
from arthra.compressor.tools import (
    COMPRESSOR_GRAPH_TOOLS,
    COMPRESSOR_TOOLS,
    analyze_compressor_load_unload_rate_tool,
    analyze_compressor_pressure_fluctuation_tool,
    calculate_compressor_specific_power_tool,
    detect_compressor_frequent_starts_tool,
    detect_compressor_high_supply_pressure_tool,
    detect_compressor_idle_running_tool,
)

CAPABILITY_TOOLS = (
    analyze_compressor_load_unload_rate_tool,
    detect_compressor_idle_running_tool,
    detect_compressor_frequent_starts_tool,
    analyze_compressor_pressure_fluctuation_tool,
    detect_compressor_high_supply_pressure_tool,
    calculate_compressor_specific_power_tool,
)


def test_six_deterministic_tools_are_registered_with_strict_input_schemas():
    registered = {tool.name for tool in COMPRESSOR_TOOLS}
    expected = {tool.name for tool in CAPABILITY_TOOLS}

    assert expected <= registered
    assert len(expected) == 6
    for capability_tool in CAPABILITY_TOOLS:
        schema = capability_tool.args_schema.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "device_scope" in schema["required"]


def test_graph_tool_schemas_hide_injected_context_and_device_scope():
    assert len(COMPRESSOR_GRAPH_TOOLS) == 12
    for capability_tool in COMPRESSOR_GRAPH_TOOLS:
        schema = capability_tool.tool_call_schema.model_json_schema()
        assert schema.get("properties", {}) == {}
        assert "device_scope" not in schema.get("properties", {})


@pytest.mark.parametrize(
    ("capability_tool", "expected_capability"),
    [
        (detect_compressor_idle_running_tool, "idle_running"),
        (detect_compressor_frequent_starts_tool, "frequent_start"),
        (analyze_compressor_pressure_fluctuation_tool, "pressure_fluctuation"),
        (detect_compressor_high_supply_pressure_tool, "high_pressure"),
        (calculate_compressor_specific_power_tool, "specific_power"),
    ],
)
def test_tool_wrapper_activates_only_its_own_capability(
    monkeypatch,
    capability_tool,
    expected_capability,
):
    class FakeService:
        def analyze_capability(self, payload, capability, message):
            assert payload.device_scope == ["compressor-1"]
            assert message
            return CompressorAnalysisResult(
                data_status="unavailable",
                capabilities=[capability],
                missing_metrics=["test fixture"],
            )

    monkeypatch.setattr("arthra.compressor.tools.CompressorAnalysisService", FakeService)

    result = capability_tool.invoke({"device_scope": ["compressor-1"]})

    assert result.capabilities == [expected_capability]
