from collections.abc import Iterable

from arthra.power.schemas import PowerCapability

POWER_CAPABILITY_KEYWORDS: dict[PowerCapability, tuple[str, ...]] = {
    "realtime_power": ("实时功率", "当前功率", "现在功率", "全厂功率", "realtime power"),
    "energy_consumption": ("用了多少电", "用电量", "耗电量", "energy consumption"),
    "energy_compare": ("用电量比", "环比", "同比", "增加了多少", "energy comparison"),
    "demand_15m": ("15分钟", "十五分钟", "最大需量", "滚动需量", "15-minute demand"),
    "peak_detection": ("峰值识别", "负荷峰值", "峰值", "peak detection"),
    "peak_average_ratio": ("峰均比", "peak average"),
    "declared_demand_exceedance": ("申报需量", "需量越限", "合同需量", "declared demand"),
    "voltage_deviation": ("电压偏差", "电压越限", "voltage deviation"),
    "phase_imbalance": ("三相不平衡", "不平衡度", "phase imbalance"),
    "power_factor": ("功率因数", "power factor"),
    "thd": ("thdu", "thdi", "总谐波", "谐波畸变率"),
    "harmonics": ("3/5/7", "3次谐波", "5次谐波", "7次谐波", "谐波特征", "harmonic"),
    "abnormal_duration": ("异常持续", "持续时间", "越限时长", "abnormal duration"),
}

DEFAULT_POWER_CAPABILITIES: list[PowerCapability] = ["realtime_power"]

POWER_CAPABILITY_KEYS: dict[PowerCapability, set[str]] = {
    "realtime_power": {"meter_TotW"},
    "energy_consumption": {"meter_SupWh"},
    "energy_compare": {"meter_SupWh"},
    "demand_15m": {"meter_TotW"},
    "peak_detection": {"meter_TotW"},
    "peak_average_ratio": {"meter_TotW"},
    "declared_demand_exceedance": {"meter_TotW"},
    "voltage_deviation": {"meter_LinV_phsAB", "meter_LinV_phsBC", "meter_LinV_phsCA"},
    "phase_imbalance": {
        "meter_ImbNgV", "meter_ImbNgA",
        "meter_A_phsA", "meter_A_phsB", "meter_A_phsC",
    },
    "power_factor": {"meter_TotPF"},
    "thd": {
        "meter_ThdPhV_phsA", "meter_ThdPhV_phsB", "meter_ThdPhV_phsC",
        "meter_ThdA_phsA", "meter_ThdA_phsB", "meter_ThdA_phsC",
    },
    "harmonics": {
        f"meter_{prefix}{order}_phs{phase}"
        for prefix in ("ThdPhV", "ThdA")
        for order in (3, 5, 7)
        for phase in ("A", "B", "C")
    },
    "abnormal_duration": {
        "meter_LinV_phsAB", "meter_LinV_phsBC", "meter_LinV_phsCA",
        "meter_ImbNgV", "meter_ImbNgA", "meter_TotPF",
        "meter_ThdPhV_phsA", "meter_ThdPhV_phsB", "meter_ThdPhV_phsC",
        "meter_ThdA_phsA", "meter_ThdA_phsB", "meter_ThdA_phsC",
    },
}

POWER_UNITS = {
    "meter_TotW": "kW",
    "meter_SupWh": "kWh",
    "meter_A_phsA": "A",
    "meter_A_phsB": "A",
    "meter_A_phsC": "A",
    "meter_LinV_phsAB": "V",
    "meter_LinV_phsBC": "V",
    "meter_LinV_phsCA": "V",
    "meter_ImbNgV": "%",
    "meter_ImbNgA": "%",
    "meter_TotPF": "",
}


def match_power_capabilities(message: str) -> list[PowerCapability]:
    lowered = message.lower()
    return [
        capability
        for capability, keywords in POWER_CAPABILITY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]


def infer_power_capabilities(
    message: str,
    explicit: Iterable[PowerCapability] = (),
) -> list[PowerCapability]:
    selected = list(dict.fromkeys(explicit))
    return selected or match_power_capabilities(message) or DEFAULT_POWER_CAPABILITIES.copy()


def power_keys(capabilities: Iterable[PowerCapability]) -> list[str]:
    keys: set[str] = set()
    for capability in capabilities:
        keys.update(POWER_CAPABILITY_KEYS[capability])
    return sorted(keys)
