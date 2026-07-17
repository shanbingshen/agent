from profiles import (
    compressor_attributes,
    compressor_telemetry,
    meter_attributes,
    meter_telemetry,
)


def test_compressor_profile_matches_point_table():
    payload = compressor_telemetry(0)
    required = {
        "air_comp_supply_pressure",
        "air_comp_discharge_temp",
        "air_comp_running_hours",
        "air_comp_main_current_a",
        "air_comp_running_state",
        "air_comp_load_state",
        "air_comp_alarm_summary",
        "air_comp_oil_filter_used_hours",
    }
    assert required <= payload.keys()
    assert compressor_attributes()["pointTableVersion"] == "开山空压机点表v1.0"
    assert compressor_attributes()["airSystemId"] == "AIR-SYS-01"
    assert {
        "air_comp_running_flag",
        "air_comp_loaded_flag",
        "air_comp_start_count",
        "air_comp_fad_flow_m3_min",
        "air_system_header_pressure_mpa",
    } <= payload.keys()
    assert compressor_telemetry(300)["air_comp_running_hours"] > compressor_telemetry(240)["air_comp_running_hours"]
    assert compressor_telemetry(300)["air_comp_loading_hours"] > compressor_telemetry(240)["air_comp_loading_hours"]


def test_meter_profile_matches_adl400_point_table():
    payload = meter_telemetry(0)
    required = {
        "meter_PhV_phsA",
        "meter_LinV_phsAB",
        "meter_A_phsA",
        "meter_TotW",
        "meter_TotPF",
        "meter_Hz",
        "meter_ImbNgV",
        "meter_SupWh",
        "meter_MaxDmdSupW",
        "meter_ThdPhV_phsA",
        "meter_ThdA_phsA",
        "meter_ThdPhV3_phsA",
        "meter_ThdA7_phsC",
    }
    assert required <= payload.keys()
    assert meter_attributes()["dev_model"] == "ADL400"
    assert meter_attributes()["airSystemId"] == "AIR-SYS-01"
    assert meter_telemetry(0)["meter_TotW"] > meter_telemetry(220)["meter_TotW"]
