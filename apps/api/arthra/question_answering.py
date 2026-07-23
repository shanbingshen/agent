from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from arthra.contracts import StrictModel

type QuestionRoute = Literal["power", "compressor", "ems", "conversation"]
type QuestionMode = Literal[
    "knowledge",
    "realtime_query",
    "analysis",
    "optimization",
    "control_request",
    "conversation",
    "out_of_domain",
    "clarification",
]
type BusinessDomain = Literal[
    "meter",
    "compressor",
    "ems",
    "forecast",
    "report",
    "general",
]
type QuestionIntent = Literal[
    "GREETING",
    "CAPABILITY_QUERY",
    "MODEL_IDENTITY",
    "OUT_OF_DOMAIN",
    "KNOWLEDGE_POWER_FACTOR",
    "KNOWLEDGE_POWER_ENERGY_DEMAND",
    "KNOWLEDGE_COMPRESSOR_UNLOAD",
    "KNOWLEDGE_CUMULATIVE_ENERGY",
    "KNOWLEDGE_EXPLANATION",
    "CONTROL_REQUEST",
    "REALTIME_POWER_QUERY",
    "ENERGY_PERIOD_QUERY",
    "ENERGY_PERIOD_COMPARE",
    "PEAK_LOAD_QUERY",
    "DEMAND_RISK_QUERY",
    "DEMAND_15M_ANALYSIS",
    "DEMAND_PEAK_AVERAGE_ANALYSIS",
    "PEAK_AVERAGE_ANALYSIS",
    "POWER_FACTOR_ANALYSIS",
    "CURRENT_UNBALANCE_ANALYSIS",
    "VOLTAGE_VIOLATION_ANALYSIS",
    "POWER_QUALITY_ANALYSIS",
    "COMPRESSOR_STATUS_QUERY",
    "COMPRESSOR_UNLOAD_ANALYSIS",
    "COMPRESSOR_FREQUENT_START_STOP",
    "COMPRESSOR_PRESSURE_FLUCTUATION",
    "COMPRESSOR_HIGH_PRESSURE",
    "COMPRESSOR_SPECIFIC_POWER",
    "COMPRESSOR_ENERGY_CAUSE",
    "COMPRESSOR_SAVINGS_ESTIMATE",
    "COMPRESSOR_LEAKAGE_ANALYSIS",
    "COMPRESSOR_AUXILIARY_POWER",
    "CROSS_ENERGY_CONTRIBUTION",
    "GENERAL_POWER_ANALYSIS",
    "GENERAL_COMPRESSOR_ANALYSIS",
    "GENERAL_ENERGY_ANALYSIS",
    "UNKNOWN",
]


class IntentDefinition(StrictModel):
    intent: QuestionIntent
    route: QuestionRoute
    query_mode: QuestionMode = "analysis"
    domain: BusinessDomain = "general"
    subject: str = Field(default="", max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=4)
    requires_device: bool = False
    uses_realtime: bool = False
    use_llm_explanation: bool = False
    max_tool_calls: int = Field(default=0, ge=0, le=4)


class QueryTimeRange(StrictModel):
    start_at: datetime
    end_at: datetime
    label: str
    defaulted: bool = False
    comparison_split_at: datetime | None = None


class RequestedDeviceRef(StrictModel):
    kind: Literal["meter", "compressor"]
    ordinal: int = Field(ge=1, le=9999)


INTENTS: dict[QuestionIntent, IntentDefinition] = {
    "GREETING": IntentDefinition(intent="GREETING", route="conversation"),
    "CAPABILITY_QUERY": IntentDefinition(intent="CAPABILITY_QUERY", route="conversation"),
    "MODEL_IDENTITY": IntentDefinition(intent="MODEL_IDENTITY", route="conversation"),
    "OUT_OF_DOMAIN": IntentDefinition(intent="OUT_OF_DOMAIN", route="conversation"),
    "KNOWLEDGE_POWER_FACTOR": IntentDefinition(intent="KNOWLEDGE_POWER_FACTOR", route="conversation"),
    "KNOWLEDGE_POWER_ENERGY_DEMAND": IntentDefinition(intent="KNOWLEDGE_POWER_ENERGY_DEMAND", route="conversation"),
    "KNOWLEDGE_COMPRESSOR_UNLOAD": IntentDefinition(intent="KNOWLEDGE_COMPRESSOR_UNLOAD", route="conversation"),
    "KNOWLEDGE_CUMULATIVE_ENERGY": IntentDefinition(intent="KNOWLEDGE_CUMULATIVE_ENERGY", route="conversation"),
    "KNOWLEDGE_EXPLANATION": IntentDefinition(intent="KNOWLEDGE_EXPLANATION", route="conversation"),
    "CONTROL_REQUEST": IntentDefinition(intent="CONTROL_REQUEST", route="conversation"),
    "REALTIME_POWER_QUERY": IntentDefinition(
        intent="REALTIME_POWER_QUERY", route="power", capabilities=["realtime_power"],
        requires_device=True, uses_realtime=True, max_tool_calls=1,
    ),
    "ENERGY_PERIOD_QUERY": IntentDefinition(
        intent="ENERGY_PERIOD_QUERY", route="power", capabilities=["energy_consumption"],
        requires_device=True, max_tool_calls=1,
    ),
    "ENERGY_PERIOD_COMPARE": IntentDefinition(
        intent="ENERGY_PERIOD_COMPARE", route="power", capabilities=["energy_compare"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "PEAK_LOAD_QUERY": IntentDefinition(
        intent="PEAK_LOAD_QUERY", route="power", capabilities=["peak_detection"],
        requires_device=True, max_tool_calls=1,
    ),
    "DEMAND_RISK_QUERY": IntentDefinition(
        intent="DEMAND_RISK_QUERY", route="power",
        capabilities=["demand_15m", "declared_demand_exceedance"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=2,
    ),
    "DEMAND_15M_ANALYSIS": IntentDefinition(
        intent="DEMAND_15M_ANALYSIS", route="power",
        capabilities=["demand_15m", "declared_demand_exceedance"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=2,
    ),
    "DEMAND_PEAK_AVERAGE_ANALYSIS": IntentDefinition(
        intent="DEMAND_PEAK_AVERAGE_ANALYSIS", route="power",
        capabilities=["demand_15m", "peak_average_ratio"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=2,
    ),
    "PEAK_AVERAGE_ANALYSIS": IntentDefinition(
        intent="PEAK_AVERAGE_ANALYSIS", route="power", capabilities=["peak_average_ratio"],
        requires_device=True, max_tool_calls=1,
    ),
    "POWER_FACTOR_ANALYSIS": IntentDefinition(
        intent="POWER_FACTOR_ANALYSIS", route="power", capabilities=["power_factor"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "CURRENT_UNBALANCE_ANALYSIS": IntentDefinition(
        intent="CURRENT_UNBALANCE_ANALYSIS", route="power", capabilities=["phase_imbalance"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "VOLTAGE_VIOLATION_ANALYSIS": IntentDefinition(
        intent="VOLTAGE_VIOLATION_ANALYSIS", route="power", capabilities=["voltage_deviation"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "POWER_QUALITY_ANALYSIS": IntentDefinition(
        intent="POWER_QUALITY_ANALYSIS", route="power",
        capabilities=["phase_imbalance", "power_factor", "thd", "harmonics"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=4,
    ),
    "COMPRESSOR_STATUS_QUERY": IntentDefinition(
        intent="COMPRESSOR_STATUS_QUERY", route="compressor", capabilities=["realtime_status"],
        requires_device=True, uses_realtime=True, max_tool_calls=1,
    ),
    "COMPRESSOR_UNLOAD_ANALYSIS": IntentDefinition(
        intent="COMPRESSOR_UNLOAD_ANALYSIS", route="compressor", capabilities=["load_rate", "idle_running"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=2,
    ),
    "COMPRESSOR_FREQUENT_START_STOP": IntentDefinition(
        intent="COMPRESSOR_FREQUENT_START_STOP", route="compressor", capabilities=["frequent_start"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "COMPRESSOR_PRESSURE_FLUCTUATION": IntentDefinition(
        intent="COMPRESSOR_PRESSURE_FLUCTUATION", route="compressor", capabilities=["pressure_fluctuation"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "COMPRESSOR_HIGH_PRESSURE": IntentDefinition(
        intent="COMPRESSOR_HIGH_PRESSURE", route="compressor", capabilities=["high_pressure"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "COMPRESSOR_SPECIFIC_POWER": IntentDefinition(
        intent="COMPRESSOR_SPECIFIC_POWER", route="compressor", capabilities=["specific_power"],
        requires_device=True, max_tool_calls=1,
    ),
    "COMPRESSOR_ENERGY_CAUSE": IntentDefinition(
        intent="COMPRESSOR_ENERGY_CAUSE", route="compressor",
        capabilities=["energy_consumption", "load_rate", "high_pressure"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=3,
    ),
    "COMPRESSOR_SAVINGS_ESTIMATE": IntentDefinition(
        intent="COMPRESSOR_SAVINGS_ESTIMATE", route="compressor", capabilities=["savings"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "COMPRESSOR_LEAKAGE_ANALYSIS": IntentDefinition(
        intent="COMPRESSOR_LEAKAGE_ANALYSIS", route="compressor", capabilities=["leakage"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "COMPRESSOR_AUXILIARY_POWER": IntentDefinition(
        intent="COMPRESSOR_AUXILIARY_POWER", route="compressor", capabilities=["realtime_status"],
        requires_device=True, use_llm_explanation=True, max_tool_calls=1,
    ),
    "CROSS_ENERGY_CONTRIBUTION": IntentDefinition(intent="CROSS_ENERGY_CONTRIBUTION", route="conversation"),
    "GENERAL_POWER_ANALYSIS": IntentDefinition(
        intent="GENERAL_POWER_ANALYSIS",
        route="power",
        capabilities=["realtime_power", "demand_15m", "power_factor", "phase_imbalance"],
        requires_device=True,
        use_llm_explanation=True,
        max_tool_calls=4,
    ),
    "GENERAL_COMPRESSOR_ANALYSIS": IntentDefinition(
        intent="GENERAL_COMPRESSOR_ANALYSIS",
        route="compressor",
        capabilities=["realtime_status", "energy_consumption", "load_rate", "pressure_fluctuation"],
        requires_device=True,
        use_llm_explanation=True,
        max_tool_calls=4,
    ),
    "GENERAL_ENERGY_ANALYSIS": IntentDefinition(intent="GENERAL_ENERGY_ANALYSIS", route="ems", requires_device=True),
    "UNKNOWN": IntentDefinition(
        intent="UNKNOWN", route="conversation", use_llm_explanation=True
    ),
}


_KNOWLEDGE_INTENTS: set[QuestionIntent] = {
    "KNOWLEDGE_POWER_FACTOR",
    "KNOWLEDGE_POWER_ENERGY_DEMAND",
    "KNOWLEDGE_COMPRESSOR_UNLOAD",
    "KNOWLEDGE_CUMULATIVE_ENERGY",
    "KNOWLEDGE_EXPLANATION",
}
_METER_INTENTS: set[QuestionIntent] = {
    "KNOWLEDGE_POWER_FACTOR",
    "KNOWLEDGE_POWER_ENERGY_DEMAND",
    "KNOWLEDGE_CUMULATIVE_ENERGY",
    "REALTIME_POWER_QUERY",
    "ENERGY_PERIOD_QUERY",
    "ENERGY_PERIOD_COMPARE",
    "PEAK_LOAD_QUERY",
    "DEMAND_RISK_QUERY",
    "DEMAND_15M_ANALYSIS",
    "DEMAND_PEAK_AVERAGE_ANALYSIS",
    "PEAK_AVERAGE_ANALYSIS",
    "POWER_FACTOR_ANALYSIS",
    "CURRENT_UNBALANCE_ANALYSIS",
    "VOLTAGE_VIOLATION_ANALYSIS",
    "POWER_QUALITY_ANALYSIS",
    "GENERAL_POWER_ANALYSIS",
}
_COMPRESSOR_INTENTS: set[QuestionIntent] = {
    "KNOWLEDGE_COMPRESSOR_UNLOAD",
    "COMPRESSOR_STATUS_QUERY",
    "COMPRESSOR_UNLOAD_ANALYSIS",
    "COMPRESSOR_FREQUENT_START_STOP",
    "COMPRESSOR_PRESSURE_FLUCTUATION",
    "COMPRESSOR_HIGH_PRESSURE",
    "COMPRESSOR_SPECIFIC_POWER",
    "COMPRESSOR_ENERGY_CAUSE",
    "COMPRESSOR_SAVINGS_ESTIMATE",
    "COMPRESSOR_LEAKAGE_ANALYSIS",
    "COMPRESSOR_AUXILIARY_POWER",
    "GENERAL_COMPRESSOR_ANALYSIS",
}
_REALTIME_INTENTS: set[QuestionIntent] = {
    "REALTIME_POWER_QUERY",
    "COMPRESSOR_STATUS_QUERY",
}


def _mode_for_intent(intent: QuestionIntent) -> QuestionMode:
    if intent in _KNOWLEDGE_INTENTS:
        return "knowledge"
    if intent in {"GREETING", "CAPABILITY_QUERY", "MODEL_IDENTITY"}:
        return "conversation"
    if intent == "OUT_OF_DOMAIN":
        return "out_of_domain"
    if intent == "CONTROL_REQUEST":
        return "control_request"
    if intent == "UNKNOWN":
        return "clarification"
    if intent in _REALTIME_INTENTS:
        return "realtime_query"
    if intent == "COMPRESSOR_SAVINGS_ESTIMATE":
        return "optimization"
    return "analysis"


def _domain_for_intent(intent: QuestionIntent) -> BusinessDomain:
    if intent in _METER_INTENTS:
        return "meter"
    if intent in _COMPRESSOR_INTENTS:
        return "compressor"
    if intent in {"GENERAL_ENERGY_ANALYSIS", "CROSS_ENERGY_CONTRIBUTION"}:
        return "ems"
    return "general"


INTENTS = {
    intent: definition.model_copy(
        update={
            "query_mode": _mode_for_intent(intent),
            "domain": _domain_for_intent(intent),
        }
    )
    for intent, definition in INTENTS.items()
}


_GREETING_WORDS = {"你好", "您好", "嗨", "hi", "hello", "在吗"}


def normalize_question(message: str) -> str:
    return message.strip().lower().rstrip("。！!?？")


def _has(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


_KNOWLEDGE_MARKERS = (
    "什么是",
    "是什么",
    "什么意思",
    "有什么作用",
    "作用是什么",
    "如何理解",
    "请解释",
    "解释一下",
    "介绍一下",
    "定义",
    "含义",
)
_COMPRESSOR_KNOWLEDGE_TERMS = (
    "空压机",
    "压缩空气",
    "比功率",
    "加载率",
    "卸载率",
    "空载",
    "卸载",
    "供气压力",
    "管网压力",
    "储气罐",
)
_METER_KNOWLEDGE_TERMS = (
    "电表",
    "智能电表",
    "功率因数",
    "需量",
    "有功功率",
    "无功功率",
    "累计电量",
    "电能质量",
    "三相不平衡",
    "谐波",
    "thdu",
    "thdi",
)
_EMS_KNOWLEDGE_TERMS = (
    "ems",
    "能源管理",
    "综合能源",
    "储能",
    "碳排",
    "能耗",
)


def _knowledge_subject(text: str) -> str:
    subject = text
    for marker in ("请解释一下", "请解释", "解释一下", "介绍一下", "什么是"):
        if subject.startswith(marker):
            subject = subject[len(marker):]
            break
    for marker in ("是什么", "是什么意思", "什么意思", "有什么作用", "的作用", "的定义", "的含义"):
        if subject.endswith(marker):
            subject = subject[: -len(marker)]
            break
    return subject.strip(" ，,。！？?：:")[:80] or text[:80]


def _knowledge_domain(text: str) -> BusinessDomain | None:
    if _has(text, *_COMPRESSOR_KNOWLEDGE_TERMS):
        return "compressor"
    if _has(text, *_METER_KNOWLEDGE_TERMS):
        return "meter"
    if _has(text, *_EMS_KNOWLEDGE_TERMS):
        return "ems"
    return None


def _generic_knowledge_definition(text: str) -> IntentDefinition | None:
    if not _has(text, *_KNOWLEDGE_MARKERS):
        return None
    domain = _knowledge_domain(text)
    if domain is None:
        return None
    return INTENTS["KNOWLEDGE_EXPLANATION"].model_copy(
        update={
            "domain": domain,
            "subject": _knowledge_subject(text),
        }
    )


def classify_question(message: str) -> IntentDefinition | None:
    text = normalize_question(message)
    if text in _GREETING_WORDS:
        return INTENTS["GREETING"]
    if _has(text, "你是什么模型", "什么模型", "哪个模型", "模型版本"):
        return INTENTS["MODEL_IDENTITY"]
    if _has(text, "你能做什么", "你的能力", "可以做什么", "能帮我做什么"):
        return INTENTS["CAPABILITY_QUERY"]
    if _has(text, "功率、电量和需量", "功率电量需量", "功率和电量", "电量和需量") and _has(text, "区别", "不同"):
        return INTENTS["KNOWLEDGE_POWER_ENERGY_DEMAND"]
    if "功率因数" in text and _has(text, "是什么", "什么意思", "含义"):
        return INTENTS["KNOWLEDGE_POWER_FACTOR"]
    if _has(text, "卸载了为什么", "卸载为什么", "卸载还耗电"):
        return INTENTS["KNOWLEDGE_COMPRESSOR_UNLOAD"]
    if "累计电量" in text and _has(text, "正常吗", "异常吗", "什么意思"):
        return INTENTS["KNOWLEDGE_CUMULATIVE_ENERGY"]
    generic_knowledge = _generic_knowledge_definition(text)
    if generic_knowledge is not None:
        return generic_knowledge
    if _has(text, "电影", "写诗", "天气", "股票", "旅游"):
        return INTENTS["OUT_OF_DOMAIN"]
    if _has(
        text,
        "帮我启动",
        "帮我停止",
        "立即启动",
        "立即停止",
        "直接启动",
        "直接停止",
        "设置为",
        "设为",
        "调到",
        "下发控制",
        "执行控制",
    ):
        control_domain = _knowledge_domain(text)
        if control_domain is not None:
            return INTENTS["CONTROL_REQUEST"].model_copy(
                update={
                    "domain": control_domain,
                    "subject": text[:80],
                }
            )
    if _has(text, "全厂用电", "工厂用电") and "空压" in text and _has(text, "造成", "贡献", "是不是"):
        return INTENTS["CROSS_ENERGY_CONTRIBUTION"]
    if "空压" in text and _has(text, "停机", "停止") and _has(text, "电表", "功率"):
        return INTENTS["COMPRESSOR_AUXILIARY_POWER"]
    if "空压" in text and _has(text, "浪费", "省多少", "节约", "节能量", "电费"):
        return INTENTS["COMPRESSOR_SAVINGS_ESTIMATE"]
    if "空压" in text and _has(text, "漏气", "泄漏"):
        return INTENTS["COMPRESSOR_LEAKAGE_ANALYSIS"]
    if "空压" in text and _has(
        text,
        "耗电高",
        "耗电这么高",
        "为什么耗电",
        "有没有耗电",
        "耗电吗",
    ):
        return INTENTS["COMPRESSOR_ENERGY_CAUSE"]
    if "空压" in text and _has(text, "比功率", "单位产气", "能效"):
        return INTENTS["COMPRESSOR_SPECIFIC_POWER"]
    if "空压" in text and _has(text, "压力是不是", "压力过高", "设置得太高", "供气压力过高"):
        return INTENTS["COMPRESSOR_HIGH_PRESSURE"]
    if _has(text, "管网压力", "空压管网压力", "压力稳定", "压力波动"):
        return INTENTS["COMPRESSOR_PRESSURE_FLUCTUATION"]
    if "空压" in text and _has(text, "启停", "启动次数", "频繁启动"):
        return INTENTS["COMPRESSOR_FREQUENT_START_STOP"]
    if "空压" in text and _has(text, "卸载", "加载率", "卸载率", "空载"):
        return INTENTS["COMPRESSOR_UNLOAD_ANALYSIS"]
    if "空压" in text and _has(
        text,
        "正常吗",
        "运行状态",
        "运行状况",
        "运行情况",
        "当前状态",
        "现在运行",
    ):
        return INTENTS["COMPRESSOR_STATUS_QUERY"]
    if _has(text, "三相不平衡", "电流不平衡", "电压不平衡"):
        return INTENTS["CURRENT_UNBALANCE_ANALYSIS"]
    if "功率因数" in text:
        return INTENTS["POWER_FACTOR_ANALYSIS"]
    if _has(text, "电压异常", "电压偏差", "电压越限", "电压偏低", "电压偏高") or (
        "电压" in text and "越限" in text
    ):
        return INTENTS["VOLTAGE_VIOLATION_ANALYSIS"]
    if _has(text, "thdu", "thdi", "谐波", "电能质量"):
        return INTENTS["POWER_QUALITY_ANALYSIS"]
    if _has(text, "峰均比") and _has(
        text,
        "15分钟最大需量",
        "十五分钟最大需量",
        "15 分钟最大需量",
    ):
        return INTENTS["DEMAND_PEAK_AVERAGE_ANALYSIS"]
    if _has(text, "峰均比"):
        return INTENTS["PEAK_AVERAGE_ANALYSIS"]
    if _has(text, "什么时候") and _has(text, "负荷最高", "功率最高", "峰值"):
        return INTENTS["PEAK_LOAD_QUERY"]
    if _has(text, "最大负荷", "负荷峰值", "峰值负荷"):
        return INTENTS["PEAK_LOAD_QUERY"]
    if "需量" in text and _has(text, "会不会", "风险", "预警", "超", "越限"):
        return INTENTS["DEMAND_RISK_QUERY"]
    if _has(text, "15分钟最大需量", "十五分钟最大需量", "15 分钟最大需量"):
        return INTENTS["DEMAND_15M_ANALYSIS"]
    if _has(text, "比前", "环比", "同比", "增加了多少", "减少了多少") and _has(text, "电", "用电量"):
        return INTENTS["ENERGY_PERIOD_COMPARE"]
    if _has(text, "用了多少电", "用电量", "耗电量", "累计用电"):
        return INTENTS["ENERGY_PERIOD_QUERY"]
    if _has(text, "当前全厂", "现在全厂", "实时") and _has(text, "功率", "用电"):
        return INTENTS["REALTIME_POWER_QUERY"]
    if _has(text, "电表", "用电", "电力", "负荷", "需量"):
        return INTENTS["GENERAL_POWER_ANALYSIS"]
    if _has(text, "空压", "压缩空气"):
        return INTENTS["GENERAL_COMPRESSOR_ANALYSIS"]
    if _has(text, "能源", "能耗", "ems"):
        return INTENTS["GENERAL_ENERGY_ANALYSIS"]
    return None


def resolve_time_range(
    message: str,
    *,
    timezone_name: str,
    now: datetime | None = None,
    realtime: bool = False,
    compare: bool = False,
) -> QueryTimeRange:
    timezone = ZoneInfo(timezone_name)
    current = (now or datetime.now(UTC)).astimezone(timezone)
    today_start = datetime.combine(current.date(), time.min, tzinfo=timezone)
    text = normalize_question(message)

    if realtime:
        return QueryTimeRange(
            start_at=(current - timedelta(minutes=15)).astimezone(UTC),
            end_at=current.astimezone(UTC),
            label="当前实时值",
        )
    if compare and _has(text, "昨天", "前一天", "比前天"):
        split = today_start - timedelta(days=1)
        return QueryTimeRange(
            start_at=(split - timedelta(days=1)).astimezone(UTC),
            end_at=today_start.astimezone(UTC),
            comparison_split_at=split.astimezone(UTC),
            label="前日与昨日",
        )
    if "昨天" in text:
        start = today_start - timedelta(days=1)
        return QueryTimeRange(
            start_at=start.astimezone(UTC),
            end_at=today_start.astimezone(UTC),
            label="昨日00:00—24:00",
        )
    if "前天" in text:
        end = today_start - timedelta(days=1)
        return QueryTimeRange(
            start_at=(end - timedelta(days=1)).astimezone(UTC),
            end_at=end.astimezone(UTC),
            label="前日00:00—24:00",
        )
    if "今天" in text or "今日" in text:
        return QueryTimeRange(
            start_at=today_start.astimezone(UTC),
            end_at=current.astimezone(UTC),
            label="今日00:00至当前",
        )
    if _has(text, "最近7天", "近7天", "过去7天"):
        return QueryTimeRange(
            start_at=(current - timedelta(days=7)).astimezone(UTC),
            end_at=current.astimezone(UTC),
            label="最近7天",
        )
    if "本月" in text:
        start = today_start.replace(day=1)
        return QueryTimeRange(
            start_at=start.astimezone(UTC),
            end_at=current.astimezone(UTC),
            label="本月截至当前",
        )
    if _has(text, "最近24小时", "近24小时", "过去24小时", "最近 24 小时", "过去 24 小时"):
        return QueryTimeRange(
            start_at=(current - timedelta(hours=24)).astimezone(UTC),
            end_at=current.astimezone(UTC),
            label="最近24小时",
        )
    if compare:
        split = current - timedelta(hours=24)
        return QueryTimeRange(
            start_at=(current - timedelta(hours=48)).astimezone(UTC),
            end_at=current.astimezone(UTC),
            comparison_split_at=split.astimezone(UTC),
            label="最近两个24小时周期（默认）",
            defaulted=True,
        )
    return QueryTimeRange(
        start_at=(current - timedelta(hours=24)).astimezone(UTC),
        end_at=current.astimezone(UTC),
        label="最近24小时（默认）",
        defaulted=True,
    )


def extract_device_reference(message: str) -> RequestedDeviceRef | None:
    match = re.search(r"(\d+)\s*号\s*(空压机|电表)", message)
    if not match:
        return None
    return RequestedDeviceRef(
        kind="compressor" if match.group(2) == "空压机" else "meter",
        ordinal=int(match.group(1)),
    )


def device_name_matches_ordinal(name: str, ordinal: int) -> bool:
    return any(int(value) == ordinal for value in re.findall(r"\d+", name))
