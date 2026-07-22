from datetime import UTC, datetime, timedelta

import httpx
import pytest
from arthra.agent_tools import load_device_context
from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.context import CompressorContextBuilder
from arthra.compressor.repository import CompressorRepository
from arthra.compressor.schemas import CompressorAnalysisRequest
from arthra.config import Settings
from arthra.industrial_data.adapters.mock_file import MockFileIndustrialDataAdapter
from arthra.industrial_data.adapters.timeseries_api import (
    TimeSeriesApiIndustrialDataAdapter,
)
from arthra.industrial_data.factory import build_industrial_data_service
from arthra.industrial_data.schemas import IndustrialTelemetryHistory
from arthra.industrial_data.service import IndustrialDataError, IndustrialDataService
from arthra.power.analysis import PowerAnalysisService
from arthra.power.context import PowerContextBuilder
from arthra.power.repository import PowerRepository
from arthra.power.schemas import PowerAnalysisRequest


@pytest.fixture(scope="module")
def mock_service() -> IndustrialDataService:
    return IndustrialDataService(MockFileIndustrialDataAdapter())


def test_mock_provider_implements_unified_device_and_telemetry_contract(mock_service):
    page = mock_service.list_devices(page_size=10)
    assert mock_service.provider_name == "mock"
    assert {device.type for device in page.data} == {"ems", "meter", "compressor"}

    latest = mock_service.latest_telemetry(
        "mock-meter-01",
        ["meter_TotW", "meter_TotPF"],
    )
    assert set(latest) == {"meter_TotW", "meter_TotPF"}
    assert len(latest["meter_TotW"]) == 1
    assert mock_service.attributes("mock-meter-01")["declaredDemandKw"] == 100


def test_same_power_capability_runs_over_mock_provider(mock_service):
    settings = Settings(
        industrial_data_provider="mock",
        llm_api_key="",
        power_history_interval_seconds=60,
    )
    service = PowerAnalysisService(
        context_builder=PowerContextBuilder(
            repository=PowerRepository(service=mock_service),
            settings=settings,
        ),
        settings=settings,
    )
    end_at = datetime.now(UTC)
    result = service.analyze(
        PowerAnalysisRequest(
            message="分析15分钟最大需量和峰均比",
            device_scope=["mock-meter-01"],
            start_at=end_at - timedelta(hours=24),
            end_at=end_at,
            interval_seconds=60,
            capabilities=["demand_15m", "peak_average_ratio"],
        )
    )

    metric = result.metrics.demand["mock-meter-01"]
    assert result.data_status == "available"
    assert result.context.data_quality.coverage >= 0.99
    assert metric.max_demand_15m_kw is not None
    assert metric.peak_average_ratio is not None


def test_same_compressor_capabilities_run_over_mock_provider(mock_service):
    settings = Settings(
        industrial_data_provider="mock",
        llm_api_key="",
        compressor_history_interval_seconds=180,
    )
    service = CompressorAnalysisService(
        context_builder=CompressorContextBuilder(
            repository=CompressorRepository(service=mock_service),
            settings=settings,
        ),
        settings=settings,
    )
    end_at = datetime.now(UTC)
    result = service.analyze(
        CompressorAnalysisRequest(
            message="分析加载率、空载、启停、压力和比功率",
            device_scope=["mock-compressor-01"],
            start_at=end_at - timedelta(hours=24),
            end_at=end_at,
            interval_seconds=180,
            capabilities=[
                "load_rate",
                "idle_running",
                "frequent_start",
                "pressure_fluctuation",
                "high_pressure",
                "specific_power",
            ],
        )
    )

    metric = result.metrics.devices["mock-compressor-01"]
    assert result.data_status == "available"
    assert metric.load_rate_pct is not None
    assert result.metrics.specific_power.average_kw_per_m3_min is not None


def test_generic_agent_loader_only_depends_on_industrial_service(mock_service):
    contexts = load_device_context(["mock-compressor-01"], service=mock_service)

    assert contexts[0].name == "Mock-Compressor-01"
    assert contexts[0].type == "compressor"
    assert "air_comp_supply_pressure" in contexts[0].telemetry


def test_timeseries_api_adapter_validates_unified_protocol_and_auth_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path == "/devices":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": {"id": "meter-1", "entity_type": "DEVICE"},
                            "name": "Meter 1",
                            "type": "meter",
                            "label": None,
                        }
                    ],
                    "total_pages": 1,
                    "total_elements": 1,
                    "has_next": False,
                },
            )
        if request.url.path == "/devices/meter-1/telemetry/latest":
            return httpx.Response(
                200,
                json={"meter_TotW": [{"ts": 1000, "value": 95.5}]},
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = httpx.Client(
        base_url="http://timeseries.test",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    )
    adapter = TimeSeriesApiIndustrialDataAdapter(
        base_url="http://timeseries.test",
        token="test-token",
        client=client,
    )

    assert adapter.list_devices().data[0].id.id == "meter-1"
    latest = adapter.latest_telemetry("meter-1", ["meter_TotW"])
    assert isinstance(latest, IndustrialTelemetryHistory)
    assert latest["meter_TotW"][0].value == 95.5


def test_timeseries_api_adapter_rejects_payload_outside_protocol():
    client = httpx.Client(
        base_url="http://timeseries.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": True})
        ),
    )
    adapter = TimeSeriesApiIndustrialDataAdapter(
        base_url="http://timeseries.test",
        client=client,
    )

    with pytest.raises(IndustrialDataError, match="不符合工业数据协议"):
        adapter.list_devices()


def test_factory_selects_mock_without_thingsboard_credentials():
    service = build_industrial_data_service(
        Settings(
            industrial_data_provider="mock",
            industrial_data_mock_file="",
            thingsboard_username="",
            thingsboard_password="",
        )
    )

    assert service.provider_name == "mock"
    assert service.list_devices().total_elements == 3
