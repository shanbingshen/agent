from arthra.agent_tools import analyze_device_context, flatten_latest_telemetry


def test_flatten_latest_telemetry_coerces_values():
    values, timestamps = flatten_latest_telemetry(
        {
            "power_kw": [{"ts": 123, "value": "80.5"}],
            "running": [{"ts": 124, "value": "true"}],
        }
    )
    assert values.model_dump() == {"power_kw": 80.5, "running": True}
    assert timestamps.model_dump() == {"power_kw": 123, "running": 124}


def test_compressor_analysis_uses_real_values_and_reports_missing_flow():
    analysis = analyze_device_context(
        "compressor",
        [
            {
                "id": "c1",
                "name": "Compressor",
                "type": "compressor",
                "telemetry": {"power_kw": 82, "pressure_bar": 8.5, "temperature_c": 68, "running": True},
            }
        ],
        "空压机系统分析",
    )
    assert analysis["data_status"] == "available"
    assert any("82.00 kW" in finding for finding in analysis["findings"])
    assert any(
        warning["metric"] == "air_comp_supply_pressure"
        for warning in analysis["warnings"]
    )
    assert any("flow_m3_min" in metric for metric in analysis["missing_metrics"])


def test_compressor_point_table_ignores_legacy_power_alias():
    analysis = analyze_device_context(
        "compressor",
        [
            {
                "id": "c1",
                "name": "Compressor",
                "type": "compressor",
                "telemetry": {
                    "air_comp_supply_pressure": 0.72,
                    "air_comp_discharge_temp": 82,
                    "air_comp_main_current_a": 120,
                    "air_comp_running_state": "running",
                    "power_kw": 999,
                },
            }
        ],
        "空压机系统分析",
    )
    assert not any("999" in finding for finding in analysis["findings"])
    assert "power_kw" not in analysis["devices"][0]["telemetry"]
    assert any("meter_TotW" in metric for metric in analysis["missing_metrics"])


def test_stopped_compressor_low_pressure_is_not_an_alarm():
    analysis = analyze_device_context(
        "compressor",
        [
            {
                "id": "c1",
                "name": "Stopped compressor",
                "type": "compressor",
                "telemetry": {
                    "air_comp_supply_pressure": 0.05,
                    "air_comp_discharge_temp": 36,
                    "air_comp_main_current_a": 0,
                    "air_comp_running_state": "stopped",
                },
            }
        ],
        "空压机系统分析",
    )
    assert not any(
        warning.get("metric") == "air_comp_supply_pressure"
        for warning in analysis["warnings"]
    )


def test_adl400_power_quality_analysis():
    analysis = analyze_device_context(
        "power",
        [
            {
                "id": "m1",
                "name": "ADL400",
                "type": "meter",
                "telemetry": {
                    "meter_TotW": 120.5,
                    "meter_LinV_phsAB": 381.0,
                    "meter_LinV_phsBC": 379.0,
                    "meter_LinV_phsCA": 380.0,
                    "meter_TotPF": 0.96,
                    "meter_Hz": 50.01,
                    "meter_ImbNgV": 0.5,
                    "meter_ImbNgA": 3.2,
                    "meter_ThdPhV_phsA": 2.1,
                    "meter_ThdPhV_phsB": 2.2,
                    "meter_ThdPhV_phsC": 2.0,
                    "meter_ThdA_phsA": 8.5,
                    "meter_ThdA_phsB": 9.0,
                    "meter_ThdA_phsC": 8.0,
                    "meter_SupWh": 286100.2,
                    "meter_MaxDmdSupW": 138.0,
                },
            }
        ],
        "电力与需量分析",
    )
    assert analysis["data_status"] == "available"
    assert any("120.50 kW" in finding for finding in analysis["findings"])
    assert any("最大电压 THD 2.200%" in finding for finding in analysis["findings"])
    assert analysis["warnings"] == []
