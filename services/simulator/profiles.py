import math
import random

from schemas import JsonValue, TelemetryScalar


def compressor_attributes() -> dict[str, JsonValue]:
    return {
        "airSystemId": "AIR-SYS-01",
        "tenantId": "arthra-demo",
        "projectId": "arthra-energy-demo",
        "siteId": "site-001",
        "gatewayId": "gateway-modbus-01",
        "assetId": "asset-aircomp-001",
        "deviceType": "aircomp",
        "manufacturer": "开山",
        "dev_model": "KS-DEMO",
        "protocolType": "modbus RTU",
        "commAddr": 1,
        "comm_BPS": 9600,
        "comm_Parity": "E",
        "dev_install_location": "空压站 1 号机位",
        "pointTableVersion": "开山空压机点表v1.0",
        "ratedPowerKw": 110.0,
        "ratedFadM3Min": 20.8,
        "ratedPressureMpa": 0.8,
        "minimumPressureMpa": 0.65,
        "maximumPressureMpa": 0.8,
        "controlType": "vfd",
    }


def meter_attributes() -> dict[str, JsonValue]:
    return {
        "airSystemId": "AIR-SYS-01",
        "measurementRole": "compressor_system_power",
        "tenantId": "arthra-demo",
        "projectId": "arthra-energy-demo",
        "siteId": "site-001",
        "gatewayId": "gateway-modbus-01",
        "assetId": "asset-meter-001",
        "deviceType": "meter",
        "manufacturer": "安科瑞",
        "dev_model": "ADL400",
        "protocolType": "modbus RTU",
        "commAddr": 2,
        "comm_BPS": 9600,
        "comm_Parity": "E",
        "meter_PT": 1,
        "merter_CT": 200,
        "meter_RtgU": 380.0,
        "meter_RtgA": 200.0,
        "meter_WiringMode": "3P4L",
        "dev_InstallLocation": "低压配电室进线柜",
        "pointTableVersion": "ADL400 V3.1",
    }


def compressor_telemetry(tick: int) -> dict[str, TelemetryScalar]:
    wave = math.sin(tick / 12)
    running = tick % 240 < 220
    loaded = running and tick % 60 < 48
    supply_pressure = 0.72 + wave * 0.025 if running else 0.05
    discharge_temp = 82 + wave * 5 if running else 36
    current = 126 + wave * 14 if loaded else (42 if running else 0)
    running_hours = 12_840 + tick * 5 / 3600 * (220 / 240)
    loading_hours = 9_730 + tick * 5 / 3600 * (184 / 240)
    flow = 18.2 + wave * 1.4 if loaded else (1.1 if running else 0)
    header_pressure = max(0, supply_pressure - (0.035 if running else 0))
    warning_temp = discharge_temp >= 105
    fault_pressure = supply_pressure >= 0.95
    air_filter_due = True
    telemetry: dict[str, TelemetryScalar] = {
        "air_comp_supply_pressure": round(supply_pressure, 3),
        "air_comp_discharge_temp": round(discharge_temp, 2),
        "air_comp_running_hours": round(running_hours, 2),
        "air_comp_loading_hours": round(loading_hours, 2),
        "air_comp_main_current_a": round(current, 2),
        "air_comp_running_flag": 1 if running else 0,
        "air_comp_loaded_flag": 1 if loaded else 0,
        "air_comp_unloaded_running_flag": 1 if running and not loaded else 0,
        "air_comp_start_count": 315 + tick // 240,
        "air_comp_fad_flow_m3_min": round(flow, 3),
        "air_system_header_pressure_mpa": round(header_pressure, 3),
        "air_comp_vfd_speed_pct": round(72 + wave * 8, 2) if running else 0,
        "air_comp_long_idle_stop": running and not loaded,
        "air_comp_fault_supply_pressure_high": fault_pressure,
        "air_comp_fault_fan_current": False,
        "air_comp_fault_oil_filter_blocked": False,
        "air_comp_fault_separator_blocked": False,
        "air_comp_fault_air_filter_blocked": False,
        "air_comp_fault_main_motor_current": current > 190,
        "air_comp_fault_phase_sequence": False,
        "air_comp_fault_discharge_temp_high": discharge_temp >= 115,
        "air_comp_running_state": "running" if running else "stopped",
        "air_comp_load_state": "loaded" if loaded else "unloaded",
        "air_comp_fault_supply_pressure_sensor": False,
        "air_comp_fault_discharge_temp_sensor": False,
        "air_comp_fault_water_shortage": False,
        "air_comp_warning_discharge_temp_high": warning_temp,
        "air_comp_maintenance_oil_filter_due": False,
        "air_comp_maintenance_separator_due": False,
        "air_comp_maintenance_air_filter_due": air_filter_due,
        "air_comp_maintenance_lube_oil_due": False,
        "air_comp_maintenance_grease_due": False,
        "air_comp_warning_summary": warning_temp or air_filter_due,
        "air_comp_alarm_summary": fault_pressure or discharge_temp >= 115,
    }
    if tick % 180 == 0:
        telemetry.update(
            {
                "air_comp_oil_filter_used_hours": 2_860 + tick * 5 / 3600,
                "air_comp_separator_used_hours": 6_420 + tick * 5 / 3600,
                "air_comp_air_filter_used_hours": 3_980 + tick * 5 / 3600,
                "air_comp_lube_oil_used_hours": 2_240 + tick * 5 / 3600,
                "air_comp_grease_used_hours": 1_180 + tick * 5 / 3600,
            }
        )
    return telemetry


def _harmonic_points(voltage_thd: list[float], current_thd: list[float]) -> dict[str, float]:
    data: dict[str, float] = {}
    phases = ("A", "B", "C")
    ratios = {3: 0.42, 5: 0.31, 7: 0.18}
    for index, phase in enumerate(phases):
        data[f"meter_ThdPhV_phs{phase}"] = round(voltage_thd[index], 3)
        data[f"meter_ThdA_phs{phase}"] = round(current_thd[index], 3)
        for order, ratio in ratios.items():
            data[f"meter_ThdPhV{order}_phs{phase}"] = round(voltage_thd[index] * ratio, 3)
            data[f"meter_ThdA{order}_phs{phase}"] = round(current_thd[index] * ratio, 3)
    return data


def meter_telemetry(tick: int) -> dict[str, TelemetryScalar]:
    wave = math.sin(tick / 14)
    phase_wave = (wave, math.sin(tick / 14 + 2.1), math.sin(tick / 14 + 4.2))
    phase_voltage = [220 + value * 2.3 + random.uniform(-0.35, 0.35) for value in phase_wave]
    line_voltage = [value * math.sqrt(3) for value in phase_voltage]
    running = tick % 240 < 220
    loaded = running and tick % 60 < 48
    base_current = 166 if loaded else (58 if running else 5)
    phase_current = [
        max(0.5, base_current + value * (12 if loaded else 2) + offset)
        for value, offset in zip(phase_wave, (0, 3, -2), strict=True)
    ]
    pf = [0.955, 0.948, 0.962]
    phase_power = [phase_voltage[i] * phase_current[i] * pf[i] / 1000 for i in range(3)]
    phase_va = [phase_voltage[i] * phase_current[i] / 1000 for i in range(3)]
    phase_var = [math.sqrt(max(phase_va[i] ** 2 - phase_power[i] ** 2, 0)) for i in range(3)]
    total_power = sum(phase_power)
    total_va = sum(phase_va)
    total_var = sum(phase_var)
    total_pf = total_power / total_va
    voltage_avg = sum(phase_voltage) / 3
    current_avg = sum(phase_current) / 3
    voltage_imbalance = max(abs(value - voltage_avg) for value in phase_voltage) / voltage_avg * 100
    current_imbalance = max(abs(value - current_avg) for value in phase_current) / current_avg * 100
    elapsed_hours = tick * 5 / 3600
    data: dict[str, TelemetryScalar] = {
        "meter_PhV_phsA": round(phase_voltage[0], 2),
        "meter_PhV_phsB": round(phase_voltage[1], 2),
        "meter_PhV_phsC": round(phase_voltage[2], 2),
        "meter_LinV_phsAB": round(line_voltage[0], 2),
        "meter_LinV_phsBC": round(line_voltage[1], 2),
        "meter_LinV_phsCA": round(line_voltage[2], 2),
        "meter_A_phsA": round(phase_current[0], 2),
        "meter_A_phsB": round(phase_current[1], 2),
        "meter_A_phsC": round(phase_current[2], 2),
        "meter_SeqA_c0": round(abs(sum(phase_current) - current_avg * 3) * 0.02, 3),
        "meter_PhW_phsA": round(phase_power[0], 3),
        "meter_PhW_phsB": round(phase_power[1], 3),
        "meter_PhW_phsC": round(phase_power[2], 3),
        "meter_TotW": round(total_power, 3),
        "meter_PhVar_phsA": round(phase_var[0], 3),
        "meter_PhVar_phsB": round(phase_var[1], 3),
        "meter_PhVar_phsC": round(phase_var[2], 3),
        "meter_TotVar": round(total_var, 3),
        "meter_PhVA_phsA": round(phase_va[0], 3),
        "meter_PhVA_phsB": round(phase_va[1], 3),
        "meter_PhVA_phsC": round(phase_va[2], 3),
        "meter_TotVA": round(total_va, 3),
        "meter_PhPF_phsA": pf[0],
        "meter_PhPF_phsB": pf[1],
        "meter_PhPF_phsC": pf[2],
        "meter_TotPF": round(total_pf, 4),
        "meter_Hz": round(50 + wave * 0.025, 3),
        "meter_ImbNgV": round(voltage_imbalance, 3),
        "meter_ImbNgA": round(current_imbalance, 3),
        "meter_CombWh": round(286_400 + 90 * elapsed_hours, 2),
        "meter_SupWh": round(286_100 + 90 * elapsed_hours, 2),
        "meter_RevWh": 300.0,
        "meter_SupVarh": round(51_900 + total_var * elapsed_hours, 2),
        "meter_ExtFwdVarh": round(51_600 + total_var * elapsed_hours, 2),
        "meter_RevVarh": 300.0,
        "meter_MaxDmdSupW": round(max(138.0, total_power), 3),
        "meter_MaxDmdSupW_mh": 1430,
        "meter_MaxDmdSupW_dm": 1607,
        "meter_MaxDmdRevW": 0.0,
        "meter_MaxDmdRevW_mh": 0,
        "meter_MaxDmdRevW_dm": 0,
        "meter_MaxDmdSupVar": round(max(43.0, total_var), 3),
        "meter_MaxDmdSupVar_mh": 1430,
        "meter_MaxDmdSupVar_dm": 1607,
        "meter_MaxDmdRevVar": 0.0,
        "meter_MaxDmdRevVar_mh": 0,
        "meter_MaxDmdRevVar_dm": 0,
    }
    voltage_thd = [2.1 + abs(value) * 0.35 for value in phase_wave]
    current_thd = [8.2 + abs(value) * 2.1 for value in phase_wave]
    data.update(_harmonic_points(voltage_thd, current_thd))
    for index, phase in enumerate(("A", "B", "C")):
        data[f"meter_HphV1_phs{phase}"] = round(phase_voltage[index] * 0.999, 2)
        data[f"meter_ExtHphVTot_phs{phase}"] = round(phase_voltage[index] * voltage_thd[index] / 100, 3)
        data[f"meter_HA1_phs{phase}"] = round(phase_current[index] * 0.995, 2)
        data[f"meter_ExtHATot_phs{phase}"] = round(phase_current[index] * current_thd[index] / 100, 3)
        data[f"meter_ExtHphW1_phs{phase}"] = round(phase_power[index] * 0.994, 3)
        data[f"meter_HphVar1_phs{phase}"] = round(phase_var[index] * 0.992, 3)
        data[f"meter_ExtHphWTot_phs{phase}"] = round(phase_power[index] * 0.006, 3)
        data[f"meter_ExtHphVarTot_phs{phase}"] = round(phase_var[index] * 0.008, 3)
    data.update(
        {
            "meter_ExtHphW1_Tot": round(total_power * 0.994, 3),
            "meter_ExtHphVar1_Tot": round(total_var * 0.992, 3),
            "meter_ExtHphWTot": round(total_power * 0.006, 3),
            "meter_ExtHphVarTot": round(total_var * 0.008, 3),
        }
    )
    return data


def ems_telemetry(tick: int) -> dict[str, TelemetryScalar]:
    wave = math.sin(tick / 10)
    return {
        "power_kw": round(180 + wave * 35, 2),
        "energy_kwh": round(24_000 + tick * 0.25, 3),
        "soc": round(70 - wave * 8, 2),
        "mode": "auto",
    }
