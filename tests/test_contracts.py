import pytest
from arthra.agent import SemanticRouteOutput
from arthra.api import sse
from arthra.compressor.schemas import CompressorAnalysisRequest
from arthra.main import app
from arthra.schemas import ChatRequest, ControlPlanCreate
from arthra.thingsboard_schemas import TelemetryHistory
from pydantic import ValidationError


def test_public_requests_forbid_unknown_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ChatRequest.model_validate(
            {
                "thread_id": "strict-test",
                "message": "分析设备",
                "device_scope": [],
                "unexpected": True,
            }
        )


def test_supervisor_output_rejects_unknown_route_and_fields():
    with pytest.raises(ValidationError):
        SemanticRouteOutput.model_validate(
            {
                "route": "invented_expert",
                "confidence": 0.99,
                "reason": "invalid",
                "capabilities": [],
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SemanticRouteOutput.model_validate(
            {
                "route": "ems",
                "confidence": 0.9,
                "reason": "valid route with invalid extra data",
                "capabilities": [],
                "raw_credentials": "must-not-pass",
            }
        )


def test_compressor_request_rejects_unknown_capability():
    with pytest.raises(ValidationError):
        CompressorAnalysisRequest(
            capabilities=["invented_capability"],
        )


def test_control_method_and_params_are_a_strict_pair():
    with pytest.raises(ValidationError):
        ControlPlanCreate(
            device_id="compressor-1",
            device_name="Compressor 1",
            device_type="compressor",
            method="start",
            params={"value": 100},
            reason="test",
        )


def test_thingsboard_telemetry_is_validated_at_adapter_boundary():
    with pytest.raises(ValidationError):
        TelemetryHistory.model_validate(
            {"pressure": [{"ts": "not-a-timestamp", "value": 0.7}]}
        )


def test_openapi_exposes_strict_response_contracts():
    paths = app.openapi()["paths"]
    compressor_schema = paths["/api/v1/compressor-analysis"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    knowledge_schema = paths["/api/v1/knowledge/search"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert compressor_schema["$ref"].endswith("/CompressorAnalysisResult")
    assert knowledge_schema["$ref"].endswith("/KnowledgeSearchResponse")


def test_sse_payload_is_validated_by_event_contract():
    event = sse("node", {"route": "compressor"}, "supervisor")
    assert '"event": "node"' in event
    with pytest.raises(ValidationError):
        sse("invented_event", {}, None)
