from arthra.config import Settings
from arthra.daily_insight import run_daily_insight_graph
from arthra.daily_schemas import (
    DailyDeviceStatistics,
    DailyOverview,
    DailySnapshot,
    HistoryMetric,
)


def _snapshot() -> DailySnapshot:
    return DailySnapshot(
        overview=DailyOverview(
            device_count=2,
            available_device_count=2,
            warning_count=0,
            alarm_count=0,
            average_active_power_kw=90,
            active_power_data_coverage=1,
            energy_consumption_kwh=1200,
            energy_consumption_status="available",
        ),
        devices=[
            DailyDeviceStatistics(
                device_id="meter-1",
                device_name="Meter 1",
                device_type="meter",
                alarm_count=0,
                metrics={
                    "meter_TotW": HistoryMetric(
                        samples=2,
                        first=80,
                        latest=100,
                        min=80,
                        max=100,
                        avg=90,
                        delta=20,
                    )
                },
            ),
            DailyDeviceStatistics(
                device_id="compressor-1",
                device_name="Compressor 1",
                device_type="compressor",
                alarm_count=0,
                metrics={},
            ),
        ],
        findings=["Meter 1 当前功率 100 kW"],
        missing_metrics=[],
        warnings=[],
        thingsboard_alarms=[],
    )


def test_daily_insight_graph_routes_deterministic_experts():
    result = run_daily_insight_graph(
        "测试日报",
        _snapshot(),
        Settings(llm_api_key=""),
        renderer=lambda title, snapshot: f"# {title}\n设备 {snapshot.overview.device_count} 台",
    )

    assert result.generation_status == "deterministic"
    assert result.experts == ["operations", "power", "compressor", "carbon"]
    assert {section.section_id for section in result.sections} == {
        "operations-overview",
        "power-insight",
        "compressor-insight",
        "carbon-readiness",
    }
    assert len(result.deterministic_hash) == 64


def test_daily_insight_llm_only_narrates_deterministic_result():
    result = run_daily_insight_graph(
        "测试日报",
        _snapshot(),
        Settings(llm_api_key="test-key", llm_model="test-model"),
        renderer=lambda title, snapshot: "确定性正文",
        narrator=lambda title, snapshot, settings: "模型解释",
    )

    assert result.content == "模型解释"
    assert result.generation_status == "generated"
    assert result.model_name == "test-model"
    assert result.sections[0].metrics[0].value == 2
