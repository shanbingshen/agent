from datetime import UTC, datetime

import pytest
from arthra.demand_forecast import DemandForecastError, DemandForecastService
from arthra.industrial_data.adapters.mock_file import MockFileIndustrialDataAdapter
from arthra.industrial_data.schemas import (
    IndustrialDevice,
    IndustrialEntityId,
    IndustrialTelemetryHistory,
    IndustrialTelemetrySample,
    MockIndustrialDataSet,
)
from arthra.industrial_data.service import IndustrialDataService


def _forecast_service(sample_count: int = 576) -> tuple[DemandForecastService, datetime]:
    end = datetime(2026, 7, 24, 12, 45, tzinfo=UTC)
    start_ms = int(end.timestamp() * 1000) - (sample_count - 1) * 300_000
    samples = []
    for index in range(sample_count):
        slot = (index // 3) % 96
        hour = slot / 4
        production = 24.0 if 7 <= hour <= 21 else 6.0
        afternoon = 10.0 * max(0.0, 1 - abs(hour - 15) / 5)
        samples.append(
            IndustrialTelemetrySample(
                ts=start_ms + index * 300_000,
                value=64.0 + production + afternoon,
            )
        )
    dataset = MockIndustrialDataSet(
        devices=[
            IndustrialDevice(
                id=IndustrialEntityId(id="meter-forecast", entity_type="DEVICE"),
                name="Forecast Meter",
                type="meter",
            )
        ],
        telemetry={
            "meter-forecast": IndustrialTelemetryHistory(
                {"meter_TotW": samples}
            )
        },
    )
    service = IndustrialDataService(MockFileIndustrialDataAdapter(dataset=dataset))
    return DemandForecastService(service), end


def test_demand_forecast_is_deterministic_and_returns_96_interactive_points():
    service, now = _forecast_service()

    first = service.forecast("meter-forecast", now=now)
    second = service.forecast("meter-forecast", now=now)

    assert len(first.points) == 96
    assert first.model_dump() == second.model_dump()
    assert first.source == "hybrid_ml"
    assert first.current_demand_kw > 0
    assert first.peak_prediction_kw > 0
    assert first.training_samples > 5_000
    assert all(
        point.lower_kw <= point.prediction_kw <= point.upper_kw
        for point in first.points
    )
    assert all(point.baseline_kw > 0 for point in first.points)
    assert any(point.actual_kw is None for point in first.points)
    assert any(point.actual_kw is not None for point in first.points)


def test_demand_forecast_rejects_insufficient_history():
    service, now = _forecast_service(sample_count=6)

    with pytest.raises(DemandForecastError, match="至少需要12个"):
        service.forecast("meter-forecast", now=now)
