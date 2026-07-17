import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from arthra.contracts import AnalysisWarning, JsonObject, OrmReadModel, StrictModel
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
    email: str
    role: Role


class UserCreate(StrictModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.analyst


class ChatRequest(StrictModel):
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=10_000)
    device_scope: list[str] = Field(default_factory=list)


class DailySummaryCreate(StrictModel):
    device_scope: list[str] = Field(default_factory=list, max_length=100)


class DailySummaryRead(OrmReadModel):
    id: uuid.UUID
    summary_date: date
    period_start: datetime
    period_end: datetime
    title: str
    content: str
    device_scope: list[str]
    statistics: DailySnapshot
    warnings: list[AnalysisWarning]
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
    content: str
    score: float = Field(ge=-1, le=1)


class KnowledgeSearchResponse(StrictModel):
    query: str
    results: list[KnowledgeSearchResult]


class AuditEventRead(OrmReadModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str
    details: JsonObject
    created_at: datetime


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    time: datetime
