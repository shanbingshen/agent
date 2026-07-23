import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from arthra.contracts import AnalysisWarning, JsonObject, OrmReadModel, StrictModel
from arthra.conversation_schemas import ContextTimeScope, PageWorkspace
from arthra.daily_schemas import DailySnapshot
from arthra.models import ControlStatus, RiskLevel, Role


class TokenResponse(StrictModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(StrictModel):
    email: str
    password: str


class UserRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: Role


class UserCreate(StrictModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.analyst
    factory_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class TenantRead(OrmReadModel):
    id: uuid.UUID
    slug: str
    name: str
    is_active: bool


class FactoryCreate(StrictModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)


class FactoryRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    is_active: bool


class FactoryDeviceCreate(StrictModel):
    device_id: str = Field(min_length=1, max_length=128)
    device_name: str = Field(min_length=1, max_length=255)
    device_type: str = Field(min_length=1, max_length=64)


class FactoryDeviceRead(OrmReadModel):
    device_id: str
    factory_id: uuid.UUID
    device_name: str
    device_type: str
    is_active: bool


class FactoryAccessGrant(StrictModel):
    user_id: uuid.UUID
    can_manage_devices: bool = False


class ChatPageContext(StrictModel):
    factory_id: uuid.UUID | None = None
    selected_device_ids: list[str] = Field(default_factory=list, max_length=100)
    workspace: PageWorkspace | None = None
    time_scope: ContextTimeScope | None = None


class ChatRequest(StrictModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=10_000)
    device_scope: list[str] = Field(default_factory=list)
    page_context: ChatPageContext | None = None
    debug: bool = False

    @property
    def effective_device_scope(self) -> list[str]:
        contextual = self.page_context.selected_device_ids if self.page_context else []
        return list(dict.fromkeys([*self.device_scope, *contextual]))


class CustomerWarningView(StrictModel):
    severity: str
    message: str
    device_name: str | None = None


class CustomerAnalysisView(StrictModel):
    expert: str
    title: str
    data_status: str
    findings: list[str] = Field(default_factory=list)
    warnings: list[CustomerWarningView] = Field(default_factory=list)
    data_quality: Literal["高", "中", "低", "未知"] = "未知"
    confidence: Literal["高", "中高", "中", "低", "未知"] = "未知"


type AnswerResultKind = Literal[
    "fact",
    "historical_statistic",
    "prediction",
    "inference",
    "recommendation",
    "mixed",
    "data_insufficient",
]
type CapabilityState = Literal[
    "configured",
    "not_configured",
    "data_insufficient",
    "model_unavailable",
    "reference_only",
]
type ExpertSupplementState = Literal[
    "provided",
    "empty",
    "unavailable",
    "not_configured",
    "not_applicable",
]


class CustomerAnswerEvidence(StrictModel):
    label: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=500)


class CustomerAnswerMeta(StrictModel):
    result_kind: AnswerResultKind
    capability_state: CapabilityState
    data_snapshot_at: datetime
    data_cutoff_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_label: str = Field(default="未指定", max_length=100)
    updating: bool = False
    metric_basis: str = Field(min_length=1, max_length=500)
    device_names: list[str] = Field(default_factory=list, max_length=100)
    workspace: PageWorkspace | None = None
    data_quality: Literal["高", "中", "低", "未知"] = "未知"
    expert_supplement_status: ExpertSupplementState = "not_applicable"
    evidence: list[CustomerAnswerEvidence] = Field(default_factory=list, max_length=20)


type ChatFeedbackRating = Literal["helpful", "needs_improvement"]
type ChatFeedbackReason = Literal[
    "inaccurate_data",
    "not_answered",
    "missing_evidence",
    "wrong_context",
    "unclear_expression",
    "other",
]


class ChatFeedbackCreate(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    rating: ChatFeedbackRating
    reasons: list[ChatFeedbackReason] = Field(default_factory=list, max_length=6)
    comment: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_improvement_reason(self) -> "ChatFeedbackCreate":
        if self.rating == "needs_improvement" and not self.reasons:
            raise ValueError("选择需改进时至少提供一个原因")
        if self.rating == "helpful" and self.reasons:
            raise ValueError("有帮助反馈不能携带改进原因")
        return self


class ChatFeedbackRead(StrictModel):
    accepted: Literal[True] = True
    feedback_id: uuid.UUID


class AssistantAnswerAuditDetails(StrictModel):
    thread_id: str = Field(min_length=1, max_length=128)
    route: str | None = Field(default=None, max_length=64)
    query_mode: str | None = Field(default=None, max_length=64)
    domain: str | None = Field(default=None, max_length=64)
    intent: str | None = Field(default=None, max_length=128)
    subject: str | None = Field(default=None, max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    data_snapshot_at: datetime
    data_cutoff_at: datetime | None = None
    metric_version: str = Field(min_length=1, max_length=64)
    rule_version: str = Field(min_length=1, max_length=64)
    analysis_method: str | None = Field(default=None, max_length=128)
    expert_supplement_status: ExpertSupplementState


class ChatFeedbackAuditDetails(StrictModel):
    thread_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    rating: ChatFeedbackRating
    reasons: list[ChatFeedbackReason] = Field(default_factory=list, max_length=6)
    comment: str = Field(default="", max_length=500)


class NodeProgressView(StrictModel):
    status: Literal["completed"] = "completed"


class DailySummaryCreate(StrictModel):
    device_scope: list[str] = Field(default_factory=list, max_length=100)
    factory_id: uuid.UUID | None = None


class DailySummaryRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    factory_id: uuid.UUID
    summary_date: date
    period_start: datetime
    period_end: datetime
    title: str
    content: str
    device_scope: list[str]
    statistics: DailySnapshot
    warnings: list[AnalysisWarning]
    insight_payload: JsonObject
    model_name: str
    status: str
    trigger: str
    generated_by: uuid.UUID | None
    created_at: datetime


class SetPowerLimitParams(StrictModel):
    value: float = Field(ge=0)


class SetModeParams(StrictModel):
    mode: Literal["auto", "manual", "eco", "standby"]


class EmptyControlParams(StrictModel):
    pass


type ControlParams = SetPowerLimitParams | SetModeParams | EmptyControlParams
type ControlMethod = Literal["setPowerLimit", "setMode", "start", "stop"]
type ControllableDeviceType = Literal["ems", "meter", "compressor"]


class ControlPlanCreate(StrictModel):
    factory_id: uuid.UUID | None = None
    device_id: str
    device_name: str
    device_type: ControllableDeviceType
    method: ControlMethod
    params: ControlParams = Field(default_factory=EmptyControlParams)
    reason: str
    risk_level: RiskLevel = RiskLevel.medium

    @model_validator(mode="after")
    def validate_method_params(self) -> "ControlPlanCreate":
        expected = {
            "setPowerLimit": SetPowerLimitParams,
            "setMode": SetModeParams,
            "start": EmptyControlParams,
            "stop": EmptyControlParams,
        }[self.method]
        if not isinstance(self.params, expected):
            raise ValueError(f"控制方法 {self.method} 的参数结构不正确")
        return self


class ControlExecutionResult(StrictModel):
    accepted: bool | None = None
    payload: JsonObject | None = None
    error: str | None = None
    success: bool | None = None
    method: ControlMethod | None = None


class ControlPlanRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    factory_id: uuid.UUID
    device_id: str
    device_name: str
    device_type: ControllableDeviceType
    method: ControlMethod
    params: ControlParams
    reason: str
    risk_level: RiskLevel
    status: ControlStatus
    created_by: uuid.UUID
    approved_by: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    execution_result: ControlExecutionResult | None


class RejectRequest(StrictModel):
    reason: str = Field(min_length=2, max_length=1000)


class SSEEvent(StrictModel):
    event: Literal["node", "tool", "message", "error", "done"]
    node: str | None = None
    content: JsonObject | str | None = None


class KnowledgeDocumentRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    factory_id: uuid.UUID
    filename: str
    media_type: str
    status: str
    created_by: uuid.UUID
    created_at: datetime


class KnowledgeUploadResponse(StrictModel):
    id: uuid.UUID
    filename: str
    status: str
    chunks: int = Field(ge=0)


class KnowledgeSearchResult(StrictModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    score: float = Field(ge=-1, le=1)


class KnowledgeSearchResponse(StrictModel):
    query: str
    results: list[KnowledgeSearchResult]


class AuditEventRead(OrmReadModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    factory_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str
    details: JsonObject
    created_at: datetime


class AgentTraceRead(OrmReadModel):
    id: uuid.UUID
    trace_id: str
    request_id: str
    tenant_id: uuid.UUID
    factory_id: uuid.UUID
    user_id: uuid.UUID | None
    thread_id: str | None
    operation: str
    route: str | None
    intent: str | None
    status: str
    duration_ms: float
    node_timings: JsonObject
    tool_names: list[str]
    error_code: str | None
    created_at: datetime


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    time: datetime
    industrial_data_provider: Literal["thingsboard", "mock", "timeseries_api"]
