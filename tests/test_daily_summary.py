from datetime import UTC, datetime, timedelta

from arthra.daily_summary import collect_daily_snapshot, deterministic_summary, history_statistics


class FakeThingsBoardClient:
    def list_devices(self, page=0, page_size=1000):
        return {
            "data": [
                {"id": {"id": "meter-1"}, "name": "ADL400-01", "type": "meter"}
            ]
        }

    def latest_telemetry(self, device_id):
        return {
            "meter_TotW": [{"ts": 3_600_000, "value": "120.5"}],
            "meter_SupWh": [{"ts": 3_600_000, "value": "1110"}],
            "meter_TotPF": [{"ts": 2000, "value": "0.96"}],
            "meter_LinV_phsAB": [{"ts": 2000, "value": "380"}],
            "meter_LinV_phsBC": [{"ts": 2000, "value": "381"}],
            "meter_LinV_phsCA": [{"ts": 2000, "value": "379"}],
        }

    def attributes(self, device_id):
        return {"model": "ADL400"}

    def telemetry_history(self, device_id, keys, start_ts, end_ts, **kwargs):
        return {
            "meter_TotW": [
                {"ts": 3_600_000, "value": "120"},
                {"ts": 0, "value": "100"},
            ],
            "meter_SupWh": [
                {"ts": 0, "value": "1000"},
                {"ts": 3_600_000, "value": "1110"},
            ],
        }

    def list_alarms(self, device_id):
        return {"data": []}


def test_history_statistics_sorts_and_calculates_delta():
    result = history_statistics(
        {"power": [{"ts": 20, "value": "3"}, {"ts": 10, "value": "1"}]}
    )
    assert result["power"].model_dump(exclude_none=True) == {
        "samples": 2,
        "first": 1.0,
        "latest": 3.0,
        "min": 1.0,
        "max": 3.0,
        "avg": 2.0,
        "delta": 2.0,
        "first_ts": 10,
        "latest_ts": 20,
        "observed_hours": 0.0,
    }


def test_collect_daily_snapshot_builds_reproducible_overview():
    end = datetime.now(UTC)
    snapshot = collect_daily_snapshot(
        FakeThingsBoardClient(), ["meter-1"], end - timedelta(hours=24), end
    )
    assert snapshot["overview"]["device_count"] == 1
    assert snapshot["overview"]["average_active_power_kw"] == 110.0
    assert snapshot["overview"]["energy_consumption_kwh"] == 110.0
    assert snapshot["overview"]["energy_consumption_status"] == "available"
    assert any("120.50 kW" in finding for finding in snapshot["findings"])


def test_deterministic_summary_never_requires_llm():
    end = datetime.now(UTC)
    snapshot = collect_daily_snapshot(
        FakeThingsBoardClient(), ["meter-1"], end - timedelta(hours=24), end
    )
    content = deterministic_summary("测试日报", snapshot)
    assert "查询窗口已有样本平均有功功率：110.000 kW" in content
    assert "数据覆盖率" in content
    assert "查询窗口内可用数据用电增量：110.000 kWh" in content


class InvalidCounterThingsBoardClient(FakeThingsBoardClient):
    def telemetry_history(self, device_id, keys, start_ts, end_ts, **kwargs):
        result = super().telemetry_history(device_id, keys, start_ts, end_ts, **kwargs)
        result["meter_SupWh"][-1]["value"] = "500000"
        return result


def test_collect_daily_snapshot_rejects_implausible_energy_counter_delta():
    end = datetime.now(UTC)
    snapshot = collect_daily_snapshot(
        InvalidCounterThingsBoardClient(), ["meter-1"], end - timedelta(hours=24), end
    )

    assert snapshot.overview.energy_consumption_kwh is None
    assert snapshot.overview.energy_consumption_status == "invalid"
    assert any(
        warning.code == "INVALID_ENERGY_COUNTER_DELTA"
        for warning in snapshot.warnings
    )
    assert any("功率积分估算" in item for item in snapshot.missing_metrics)
