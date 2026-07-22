from collections.abc import Iterable

CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "realtime_status": ("当前状态", "现在运行", "运行正常", "实时状态", "realtime status"),
    "energy_consumption": ("耗电量", "用了多少电", "用电量", "energy consumption"),
    "load_rate": ("加载率", "卸载率", "加载", "卸载", "load rate"),
    "idle_running": ("空载", "空转", "卸载运行", "idle"),
    "frequent_start": ("频繁启停", "启停", "启动次数", "start"),
    "pressure_fluctuation": ("压力波动", "压差", "稳定", "fluctuation"),
    "high_pressure": ("压力过高", "高压", "设定压力", "high pressure"),
    "specific_power": ("比功率", "能效", "specific power"),
    "group_control": ("群控", "多机", "联控", "group control"),
    "leakage": ("泄漏", "漏气", "夜间", "非生产", "leak"),
    "savings": ("节能量", "节能", "省电", "savings"),
    "verification": ("优化前后", "效果验证", "基线", "verification"),
}

DEFAULT_CAPABILITIES = ["realtime_status"]

CAPABILITY_KEYS: dict[str, dict[str, set[str]]] = {
    "realtime_status": {
        "compressor": {
            "air_comp_running_flag",
            "air_comp_loaded_flag",
            "air_comp_supply_pressure",
            "air_comp_discharge_temp",
        },
        "meter": {"meter_TotW"},
    },
    "energy_consumption": {
        "meter": {"meter_SupWh"},
    },
    "load_rate": {
        "compressor": {
            "air_comp_running_flag",
            "air_comp_loaded_flag",
            "air_comp_running_hours",
            "air_comp_loading_hours",
        }
    },
    "idle_running": {
        "compressor": {
            "air_comp_running_flag",
            "air_comp_loaded_flag",
            "air_comp_unloaded_running_flag",
            "air_comp_main_current_a",
        },
        "meter": {"meter_TotW"},
    },
    "frequent_start": {"compressor": {"air_comp_start_count"}},
    "pressure_fluctuation": {
        "compressor": {
            "air_comp_supply_pressure",
            "air_system_header_pressure_mpa",
            "air_comp_running_flag",
        }
    },
    "high_pressure": {
        "compressor": {
            "air_comp_supply_pressure",
            "air_system_header_pressure_mpa",
            "air_comp_running_flag",
        }
    },
    "specific_power": {
        "compressor": {"air_comp_fad_flow_m3_min", "air_comp_running_flag"},
        "meter": {"meter_TotW"},
    },
    "group_control": {
        "compressor": {
            "air_comp_fad_flow_m3_min",
            "air_comp_running_flag",
            "air_comp_loaded_flag",
        },
        "meter": {"meter_TotW"},
    },
    "leakage": {
        "compressor": {
            "air_comp_fad_flow_m3_min",
            "air_comp_running_flag",
        },
        "meter": {"meter_TotW"},
    },
    "savings": {
        "compressor": {
            "air_comp_unloaded_running_flag",
            "air_comp_fad_flow_m3_min",
        },
        "meter": {"meter_TotW", "meter_SupWh"},
    },
    "verification": {
        "compressor": {"air_comp_fad_flow_m3_min"},
        "meter": {"meter_TotW", "meter_SupWh"},
    },
}

UNITS = {
    "air_comp_supply_pressure": "MPa",
    "air_system_header_pressure_mpa": "MPa",
    "air_comp_main_current_a": "A",
    "air_comp_discharge_temp": "°C",
    "air_comp_running_hours": "h",
    "air_comp_loading_hours": "h",
    "air_comp_start_count": "count",
    "air_comp_fad_flow_m3_min": "m³/min",
    "meter_TotW": "kW",
    "meter_SupWh": "kWh",
}


def infer_capabilities(message: str, explicit: Iterable[str] = ()) -> list[str]:
    requested = [item for item in explicit if item in CAPABILITY_KEYS]
    if requested:
        return list(dict.fromkeys(requested))
    inferred = match_capabilities(message)
    return inferred or DEFAULT_CAPABILITIES.copy()


def match_capabilities(message: str) -> list[str]:
    lowered = message.lower()
    return [
        capability
        for capability, keywords in CAPABILITY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]


def keys_for_device_type(capabilities: Iterable[str], device_type: str) -> list[str]:
    keys: set[str] = set()
    for capability in capabilities:
        keys.update(CAPABILITY_KEYS.get(capability, {}).get(device_type, set()))
    return sorted(keys)
