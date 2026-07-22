from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from arthra.agent_schemas import DeviceAnalysis, DeviceContext, ExpertAnalysis
from arthra.contracts import AnalysisWarning, AttributeValues, TelemetryValues, TimestampValues
from arthra.industrial_data import IndustrialDataError, IndustrialDataService
from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.schemas import IndustrialTelemetryHistory

TelemetryLoader = Callable[[list[str]], list[DeviceContext]]


def _coerce_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return float(value)
    except ValueError:
        return value


def flatten_latest_telemetry(
    payload: IndustrialTelemetryHistory | dict[str, Any],
) -> tuple[TelemetryValues, TimestampValues]:
    history = IndustrialTelemetryHistory.model_validate(payload)
    values: dict[str, Any] = {}
    timestamps: dict[str, int] = {}
    for key, samples in history.items():
        if not samples:
            continue
        latest = samples[0]
        values[key] = _coerce_value(latest.value)
        timestamps[key] = latest.ts
    return TelemetryValues.model_validate(values), TimestampValues.model_validate(timestamps)


def load_device_context(
    device_ids: list[str],
    service: IndustrialDataService | None = None,
) -> list[DeviceContext]:
    """Read metadata and telemetry through the unified industrial data service."""
    if not device_ids:
        return []
    data_service = service or get_industrial_data_service()
    page = data_service.list_devices(page=0, page_size=1000)
    metadata = {item.id.id: item for item in page.data}
    contexts: list[DeviceContext] = []
    for device_id in dict.fromkeys(device_ids):
        device = metadata.get(device_id)
        if device is None:
            contexts.append(DeviceContext(id=device_id, error="设备不存在或当前账号无权访问"))
            continue
        try:
            telemetry, timestamps = flatten_latest_telemetry(
                data_service.latest_telemetry(device_id)
            )
            attributes = data_service.attributes(device_id)
            contexts.append(DeviceContext(
                id=device_id,
                name=device.name,
                type=device.type,
                telemetry=telemetry,
                timestamps=timestamps,
                attributes=AttributeValues.model_validate(attributes),
            ))
        except IndustrialDataError as exc:
            contexts.append(DeviceContext(
                id=device_id,
                name=device.name,
                type=device.type,
                error=str(exc),
            ))
    return contexts


@tool("get_latest_device_telemetry")
def get_latest_device_telemetry(device_ids: list[str]) -> list[DeviceContext]:
    """Return metadata and telemetry through the configured industrial data provider."""
    return load_device_context(device_ids)


def _number(telemetry: dict[str, Any], key: str) -> float | None:
    value = telemetry.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _first_number(telemetry: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(telemetry, key)
        if value is not None:
            return value
    return None


def _analyze_compressor(device: DeviceContext) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    telemetry = device.get("telemetry", {})
    uses_point_table = "air_comp_supply_pressure" in telemetry
    findings: list[str] = []
    missing: list[str] = []
    warnings: list[dict[str, Any]] = []
    pressure_mpa = _number(telemetry, "air_comp_supply_pressure")
    pressure_bar = _number(telemetry, "pressure_bar")
    if pressure_mpa is None and pressure_bar is not None:
        pressure_mpa = pressure_bar / 10
    temperature = _first_number(
        telemetry, "air_comp_discharge_temp", "temperature_c"
    )
    current = _number(telemetry, "air_comp_main_current_a")
    power = None if uses_point_table else _number(telemetry, "power_kw")
    linked_meter_id = device.attributes.get("linkedMeterDeviceId")
    running_state = telemetry.get("air_comp_running_state")
    running = telemetry.get("running") if running_state is None else running_state == "running"
    if pressure_mpa is None:
        missing.append("air_comp_supply_pressure")
    else:
        findings.append(f"供气压力 {pressure_mpa:.3f} MPa（{pressure_mpa * 10:.2f} bar）")
        if running is not False and (pressure_mpa < 0.65 or pressure_mpa > 0.8):
            warnings.append(
                {
                    "severity": "high",
                    "metric": "air_comp_supply_pressure",
                    "value": pressure_mpa,
                    "message": "供气压力超出 0.65–0.80 MPa 演示运行区间",
                }
            )
    if current is not None:
        findings.append(f"主机 A 相电流 {current:.2f} A")
    else:
        missing.append("air_comp_main_current_a")
    if power is not None:
        findings.append(f"实时功率 {power:.2f} kW")
    elif linked_meter_id:
        findings.append(f"功率由关联电表 {linked_meter_id} 独立计量")
    else:
        missing.append("关联电表 meter_TotW（空压机点表未提供有功功率）")
    if temperature is None:
        missing.append("temperature_c")
    else:
        findings.append(f"主机温度 {temperature:.2f} °C")
        if temperature >= 105 or telemetry.get("air_comp_warning_discharge_temp_high"):
            warnings.append(
                {
                    "severity": "high",
                    "metric": "air_comp_discharge_temp",
                    "value": temperature,
                    "message": "排气温度达到高温预警区间",
                }
            )
    if running is not None:
        findings.append("设备正在运行" if running else "设备当前停止")
    if telemetry.get("air_comp_load_state") is not None:
        findings.append(
            "当前加载运行" if telemetry["air_comp_load_state"] == "loaded" else "当前卸载运行"
        )
    running_hours = _number(telemetry, "air_comp_running_hours")
    loading_hours = _number(telemetry, "air_comp_loading_hours")
    if running_hours is not None:
        findings.append(f"累计运行 {running_hours:.2f} h")
    if loading_hours is not None:
        findings.append(f"累计加载 {loading_hours:.2f} h")
    fault_names = {
        "air_comp_fault_supply_pressure_high": "供气压力高故障",
        "air_comp_fault_fan_current": "风机电流故障",
        "air_comp_fault_oil_filter_blocked": "油滤器堵塞",
        "air_comp_fault_separator_blocked": "油分器堵塞",
        "air_comp_fault_air_filter_blocked": "空滤器堵塞",
        "air_comp_fault_main_motor_current": "主电机电流故障",
        "air_comp_fault_phase_sequence": "相序错误",
        "air_comp_fault_discharge_temp_high": "排气温度高故障",
        "air_comp_fault_supply_pressure_sensor": "供气压力传感器失灵",
        "air_comp_fault_discharge_temp_sensor": "排气温度传感器失灵",
        "air_comp_fault_water_shortage": "缺水故障",
    }
    maintenance_names = {
        "air_comp_maintenance_oil_filter_due": "油滤器维护到期",
        "air_comp_maintenance_separator_due": "油分器维护到期",
        "air_comp_maintenance_air_filter_due": "空滤器维护到期",
        "air_comp_maintenance_lube_oil_due": "润滑油维护到期",
        "air_comp_maintenance_grease_due": "润滑脂维护到期",
    }
    for key, name in fault_names.items():
        if telemetry.get(key) is True:
            warnings.append(
                {"severity": "critical", "metric": key, "value": True, "message": name}
            )
    for key, name in maintenance_names.items():
        if telemetry.get(key) is True:
            warnings.append(
                {"severity": "medium", "metric": key, "value": True, "message": name}
            )
    flow = _first_number(telemetry, "air_comp_fad_flow_m3_min", "flow_m3_min")
    if flow is None:
        missing.append(
            "产气流量 air_comp_fad_flow_m3_min（计算比功率 kW/(m³/min) 所需）"
        )
    else:
        findings.append(f"实时产气流量 {flow:.3f} m³/min")
    return findings, missing, warnings


def _analyze_power(device: DeviceContext) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    telemetry = device.get("telemetry", {})
    findings: list[str] = []
    missing: list[str] = []
    warnings: list[dict[str, Any]] = []
    power = _first_number(telemetry, "meter_TotW", "active_power_kw", "power_kw")
    line_voltages = [
        value
        for value in (
            _number(telemetry, "meter_LinV_phsAB"),
            _number(telemetry, "meter_LinV_phsBC"),
            _number(telemetry, "meter_LinV_phsCA"),
        )
        if value is not None
    ]
    voltage = sum(line_voltages) / len(line_voltages) if line_voltages else _number(telemetry, "voltage_v")
    factor = _first_number(telemetry, "meter_TotPF", "power_factor")
    if power is None:
        missing.append("meter_TotW")
    else:
        findings.append(f"有功功率 {power:.2f} kW")
    if voltage is not None:
        findings.append(f"三相平均线电压 {voltage:.2f} V")
        if voltage < 361 or voltage > 399:
            warnings.append({"severity": "medium", "metric": "voltage_v", "value": voltage, "message": "电压超出 380 V ±5% 演示范围"})
    else:
        missing.append("meter_LinV_phsAB/BC/CA")
    if factor is not None:
        findings.append(f"功率因数 {factor:.3f}")
        if factor < 0.9:
            warnings.append({"severity": "medium", "metric": "power_factor", "value": factor, "message": "功率因数低于 0.90"})
    else:
        missing.append("meter_TotPF")
    frequency = _number(telemetry, "meter_Hz")
    if frequency is not None:
        findings.append(f"电网频率 {frequency:.3f} Hz")
        if frequency < 49.5 or frequency > 50.5:
            warnings.append(
                {"severity": "high", "metric": "meter_Hz", "value": frequency, "message": "频率超出 49.5–50.5 Hz 演示范围"}
            )
    voltage_imbalance = _number(telemetry, "meter_ImbNgV")
    current_imbalance = _number(telemetry, "meter_ImbNgA")
    if voltage_imbalance is not None:
        findings.append(f"电压不平衡度 {voltage_imbalance:.3f}%")
        if voltage_imbalance > 2:
            warnings.append({"severity": "medium", "metric": "meter_ImbNgV", "value": voltage_imbalance, "message": "电压不平衡度超过 2% 演示阈值"})
    if current_imbalance is not None:
        findings.append(f"电流不平衡度 {current_imbalance:.3f}%")
        if current_imbalance > 10:
            warnings.append({
                "severity": "medium",
                "metric": "meter_ImbNgA",
                "value": current_imbalance,
                "message": (
                    "电流不平衡度触发平台内部预警阈值，属于疑似异常；"
                    "需核查缺相、CT接线与倍率、点位映射和采样同步后确认"
                ),
            })
    voltage_thd = [
        value
        for key in ("meter_ThdPhV_phsA", "meter_ThdPhV_phsB", "meter_ThdPhV_phsC")
        if (value := _number(telemetry, key)) is not None
    ]
    current_thd = [
        value
        for key in ("meter_ThdA_phsA", "meter_ThdA_phsB", "meter_ThdA_phsC")
        if (value := _number(telemetry, key)) is not None
    ]
    if voltage_thd:
        findings.append(f"最大电压 THD {max(voltage_thd):.3f}%")
        if max(voltage_thd) > 5:
            warnings.append({"severity": "high", "metric": "meter_ThdPhV", "value": max(voltage_thd), "message": "电压THD触发平台内部预警阈值；是否构成标准超限需结合测点和适用判据确认"})
    if current_thd:
        findings.append(f"最大电流 THD {max(current_thd):.3f}%")
        if max(current_thd) > 15:
            warnings.append({"severity": "medium", "metric": "meter_ThdA", "value": max(current_thd), "message": "电流THD触发平台内部预警阈值；是否构成标准超限需结合PCC测点、短路容量和负荷电流确认"})
    energy = _number(telemetry, "meter_SupWh")
    if energy is not None:
        findings.append(f"正向有功总电能 {energy:.2f} kWh")
    return findings, missing, warnings


def _analyze_ems(device: DeviceContext) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    telemetry = device.get("telemetry", {})
    findings: list[str] = []
    missing: list[str] = []
    warnings: list[dict[str, Any]] = []
    power = _number(telemetry, "power_kw")
    energy = _number(telemetry, "energy_kwh")
    soc = _number(telemetry, "soc")
    if power is not None:
        findings.append(f"EMS 实时功率 {power:.2f} kW")
    else:
        missing.append("power_kw")
    if energy is not None:
        findings.append(f"累计电量 {energy:.2f} kWh")
    if soc is not None:
        findings.append(f"储能 SOC {soc:.2f}%")
        if soc < 20 or soc > 90:
            warnings.append({"severity": "medium", "metric": "soc", "value": soc, "message": "SOC 超出 20%–90% 演示运行区间"})
    return findings, missing, warnings


def _without_legacy_aliases(device: DeviceContext) -> DeviceContext:
    telemetry = device.get("telemetry", {})
    legacy_keys: set[str] = set()
    if device.get("type") == "compressor" and "air_comp_supply_pressure" in telemetry:
        legacy_keys = {"power_kw", "pressure_bar", "temperature_c", "running"}
    elif device.get("type") == "meter" and "meter_TotW" in telemetry:
        legacy_keys = {"active_power_kw", "voltage_v", "current_a", "power_factor"}
    if not legacy_keys:
        return device
    return device.model_copy(
        update={
            "telemetry": TelemetryValues({key: value for key, value in telemetry.items() if key not in legacy_keys}),
            "timestamps": TimestampValues({
            key: value
            for key, value in device.get("timestamps", {}).items()
            if key not in legacy_keys
            }),
        }
    )


def analyze_device_context(
    domain: str,
    devices: list[DeviceContext | dict[str, Any]],
    title: str,
) -> ExpertAnalysis:
    normalized_devices = [DeviceContext.model_validate(device) for device in devices]
    if not normalized_devices:
        return ExpertAnalysis.model_validate({
            "expert": domain,
            "title": title,
            "data_status": "no_scope",
            "device_count": 0,
            "devices": [],
            "findings": [],
            "missing_metrics": ["请选择至少一台设备"],
            "warnings": [],
        })
    device_results: list[DeviceAnalysis] = []
    all_findings: list[str] = []
    all_missing: list[str] = []
    all_warnings: list[dict[str, Any]] = []
    for original_device in normalized_devices:
        device = _without_legacy_aliases(original_device)
        if device.get("error"):
            result = DeviceAnalysis(
                **device.model_dump(),
                findings=[],
                missing_metrics=[],
                warnings=[AnalysisWarning(severity="high", message=device.error or "设备读取失败")],
            )
        else:
            device_type = device.get("type")
            if device_type == "compressor":
                findings, missing, warnings = _analyze_compressor(device)
            elif device_type == "meter":
                findings, missing, warnings = _analyze_power(device)
            elif domain == "compressor":
                findings, missing, warnings = _analyze_compressor(device)
            elif domain == "power":
                findings, missing, warnings = _analyze_power(device)
            else:
                findings, missing, warnings = _analyze_ems(device)
            result = DeviceAnalysis(
                **device.model_dump(),
                findings=findings,
                missing_metrics=missing,
                warnings=[AnalysisWarning.model_validate(item) for item in warnings],
            )
            all_findings.extend(f"{device.get('name')}: {item}" for item in findings)
            all_missing.extend(f"{device.get('name')}: {item}" for item in missing)
            all_warnings.extend({**warning, "device_id": device.get("id"), "device_name": device.get("name")} for warning in warnings)
        device_results.append(result)
    if domain == "forecast":
        all_missing.append("历史时序窗口（当前仅查询最新值，不能计算趋势）")
    return ExpertAnalysis.model_validate({
        "expert": domain,
        "title": title,
        "data_status": "available" if all_findings else "unavailable",
        "device_count": len(normalized_devices),
        "devices": device_results,
        "findings": all_findings,
        "missing_metrics": all_missing,
        "warnings": all_warnings,
    })
