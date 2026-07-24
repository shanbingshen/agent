import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Literal

from arthra_rag import retrieve_citations
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import ToolMessage
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.context import CompressorContextError
from arthra.compressor.schemas import CompressorAnalysisRequest, CompressorAnalysisResult
from arthra.config import get_settings
from arthra.contracts import Citation, JsonObject
from arthra.control import ControlService
from arthra.daily_summary import DailySummaryError, generate_daily_summary
from arthra.db import get_db
from arthra.demand_forecast import DemandForecastError, DemandForecastService
from arthra.industrial_data import IndustrialDataError
from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)
from arthra.knowledge import (
    chunk_text,
    delete_knowledge_vectors,
    embed_texts,
    search_knowledge,
    upsert_knowledge_vectors,
)
from arthra.models import (
    AgentTrace,
    AuditEvent,
    ControlPlan,
    DailySummary,
    Factory,
    FactoryDevice,
    KnowledgeChunk,
    KnowledgeDocument,
    Role,
    Tenant,
    User,
    UserFactoryAccess,
)
from arthra.observability import METRICS, current_trace_id, persist_agent_trace
from arthra.power.analysis import PowerAnalysisService
from arthra.power.context import PowerContextError
from arthra.power.schemas import PowerAnalysisRequest, PowerAnalysisResult
from arthra.schemas import (
    AgentTraceRead,
    AssistantAnswerAuditDetails,
    AuditEventRead,
    ChatFeedbackAuditDetails,
    ChatFeedbackCreate,
    ChatFeedbackRead,
    ChatRequest,
    ControlPlanCreate,
    ControlPlanRead,
    CustomerAnalysisView,
    CustomerAnswerEvidence,
    CustomerAnswerMeta,
    CustomerWarningView,
    DailySummaryCreate,
    DailySummaryRead,
    DemandForecastResponse,
    FactoryAccessGrant,
    FactoryCreate,
    FactoryDeviceCreate,
    FactoryDeviceRead,
    FactoryRead,
    HealthResponse,
    KnowledgeDocumentRead,
    KnowledgeSearchResponse,
    KnowledgeUploadResponse,
    LoadForecastMockResponse,
    LoadForecastPoint,
    LoginRequest,
    NodeProgressView,
    RejectRequest,
    SSEEvent,
    TenantRead,
    TokenResponse,
    UserCreate,
    UserRead,
)
from arthra.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from arthra.tenancy import (
    AgentThreadOwnershipError,
    TenantAccessError,
    accessible_device_ids,
    assert_agent_thread_owner,
    authorize_device_scope,
    claim_agent_thread,
    factory_ids_for_user,
    filter_device_page,
    resolve_factory_id,
    sync_factory_devices,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def _factory_scope(
    db: Session,
    user: User,
    requested_factory_id: uuid.UUID | str | None,
) -> uuid.UUID:
    try:
        return resolve_factory_id(db, user, requested_factory_id)
    except TenantAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _authorized_scope(
    db: Session,
    user: User,
    factory_id: uuid.UUID,
    device_ids: list[str],
) -> list[str]:
    try:
        return authorize_device_scope(db, user, factory_id, device_ids)
    except TenantAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _quality_labels(analysis: object) -> tuple[str, str]:
    context = getattr(analysis, "context", None)
    quality = getattr(context, "data_quality", None)
    coverage = getattr(quality, "coverage", None)
    stale = bool(getattr(quality, "stale_keys", []))
    invalid = bool(getattr(quality, "invalid_keys", []))
    if not isinstance(coverage, (int, float)):
        return "未知", "未知"
    data_quality = "高" if coverage >= 0.98 and not stale and not invalid else "中" if coverage >= 0.8 else "低"
    confidence = "高" if coverage >= 0.98 and not stale and not invalid else "中高" if coverage >= 0.9 else "中" if coverage >= 0.8 else "低"
    warnings = getattr(analysis, "warnings", [])
    if any("不平衡" in getattr(item, "message", "") for item in warnings) and confidence == "高":
        confidence = "中高"
    return data_quality, confidence


def _customer_analysis_view(analysis: object | None) -> CustomerAnalysisView | None:
    if analysis is None:
        return None
    data_quality, confidence = _quality_labels(analysis)
    warnings = [
        CustomerWarningView(
            severity=getattr(item, "severity", "unknown"),
            message=getattr(item, "message", "需要关注"),
            device_name=getattr(item, "device_name", None),
        )
        for item in getattr(analysis, "warnings", [])
    ]
    return CustomerAnalysisView(
        expert=getattr(analysis, "expert", "unknown"),
        title=getattr(analysis, "title", "专家分析"),
        data_status=getattr(analysis, "data_status", "unavailable"),
        findings=list(getattr(analysis, "findings", [])),
        warnings=warnings,
        data_quality=data_quality,
        confidence=confidence,
    )


def _answer_device_names(analysis: object | None) -> list[str]:
    if analysis is None:
        return []
    context = getattr(analysis, "context", None)
    metrics = getattr(analysis, "metrics", None)
    metric_device_ids: set[str] = set()
    for field_name in ("devices", "realtime", "energy", "demand", "quality", "pressure"):
        field_value = getattr(metrics, field_name, None)
        if isinstance(field_value, dict):
            metric_device_ids.update(str(item) for item in field_value)
    candidates = (
        getattr(context, "devices", None)
        or getattr(context, "meters", None)
        or getattr(analysis, "devices", None)
        or []
    )
    names: list[str] = []
    for item in candidates:
        device_id = getattr(item, "device_id", None) or getattr(item, "id", None)
        if metric_device_ids and device_id not in metric_device_ids:
            continue
        name = getattr(item, "device_name", None) or getattr(item, "name", None)
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _answer_metric_basis(intent: str | None) -> str:
    return {
        "KNOWLEDGE_EXPLANATION": "工业能源概念解释，不读取当前设备数据",
        "KNOWLEDGE_POWER_FACTOR": "功率因数通用概念解释，不读取当前设备数据",
        "KNOWLEDGE_POWER_ENERGY_DEMAND": "功率、电量和需量通用计量口径解释",
        "KNOWLEDGE_COMPRESSOR_UNLOAD": "空压机加载与卸载通用运行原理解释",
        "KNOWLEDGE_CUMULATIVE_ENERGY": "累计电量通用计量口径解释",
        "REALTIME_POWER_QUERY": "统一工业数据接口的最新有效有功功率读数",
        "ENERGY_PERIOD_QUERY": "累计正向有功电量期末值减期初值",
        "ENERGY_PERIOD_COMPARE": "两个同口径统计周期的累计电量差值比较",
        "DEMAND_RISK_QUERY": "15分钟滚动平均需量与需量控制目标比较",
        "DEMAND_15M_ANALYSIS": "15分钟滚动平均需量确定性计算",
        "PEAK_LOAD_QUERY": "统计周期内60秒平均功率峰值",
        "PEAK_AVERAGE_ANALYSIS": "60秒峰值与统计周期平均负荷的比值",
        "DEMAND_PEAK_AVERAGE_ANALYSIS": "15分钟滚动需量、60秒峰值与周期平均负荷",
        "COMPRESSOR_STATUS_QUERY": "最新运行、加载、压力、温度及活动告警读数",
        "COMPRESSOR_UNLOAD_ANALYSIS": "运行与加载状态按采样时间桶加权统计",
        "COMPRESSOR_FREQUENT_START_STOP": "启动累计计数差值除以有效观察时长",
        "COMPRESSOR_PRESSURE_FLUCTUATION": "供气压力时序的均值、极差及P95-P5波动",
        "COMPRESSOR_HIGH_PRESSURE": "供气压力与配置阈值比较；末端工艺压力不足时不作最终诊断",
        "POWER_QUALITY_ANALYSIS": "三相电压、电流、功率因数、THDu/THDi及谐波确定性规则",
        "CURRENT_UNBALANCE_ANALYSIS": "三相电流与平台内部不平衡管理阈值比较",
        "VOLTAGE_VIOLATION_ANALYSIS": "三相线电压相对额定电压的偏差与持续时间",
        "POWER_FACTOR_ANALYSIS": "功率因数时序与平台内部管理阈值比较",
    }.get(intent or "", "基于当前设备范围的统一工业数据与确定性分析结果")


def _customer_answer_meta(
    final_state: dict,
    payload: ChatRequest,
    snapshot_at: datetime,
) -> CustomerAnswerMeta:
    analysis = final_state.get("analysis")
    route = final_state.get("route")
    route_decision = final_state.get("route_decision")
    intent = (
        route_decision.get("intent")
        if isinstance(route_decision, dict)
        else getattr(route_decision, "intent", None)
    )
    query_mode = (
        route_decision.get("query_mode")
        if isinstance(route_decision, dict)
        else getattr(route_decision, "query_mode", None)
    )
    data_status = getattr(analysis, "data_status", None)
    context = getattr(analysis, "context", None)
    query_time_range = final_state.get("query_time_range")
    start_at = getattr(query_time_range, "start_at", None)
    end_at = getattr(query_time_range, "end_at", None)
    period_label = getattr(query_time_range, "label", None) or "当前会话"
    if query_mode == "knowledge":
        period_label = "不适用（概念解释）"
    if context is not None:
        start_ts = getattr(context, "start_ts", None)
        end_ts = getattr(context, "end_ts", None)
        if isinstance(start_ts, int):
            start_at = datetime.fromtimestamp(start_ts / 1000, tz=UTC)
        if isinstance(end_ts, int):
            end_at = datetime.fromtimestamp(end_ts / 1000, tz=UTC)
    cutoff_at = end_at
    updating = bool(cutoff_at and cutoff_at >= snapshot_at - timedelta(minutes=10))
    if data_status in {"no_scope", "unavailable"}:
        result_kind = "data_insufficient"
        capability_state = "data_insufficient"
    elif route == "forecast":
        result_kind = "prediction"
        capability_state = "not_configured"
    elif query_mode == "knowledge":
        result_kind = "fact"
        capability_state = "reference_only"
    elif route == "conversation":
        result_kind = "fact"
        capability_state = "reference_only"
    elif intent and ("REALTIME" in intent or intent == "COMPRESSOR_STATUS_QUERY"):
        result_kind = "fact"
        capability_state = "configured"
    else:
        result_kind = "historical_statistic"
        capability_state = "data_insufficient" if data_status == "partial" else "configured"
    public_analysis = _customer_analysis_view(analysis)
    data_quality = public_analysis.data_quality if public_analysis else "未知"
    device_names = _answer_device_names(analysis)
    evidence_values = [
        CustomerAnswerEvidence(
            label="回答时间" if query_mode == "knowledge" else "数据快照",
            value=snapshot_at.isoformat(timespec="seconds"),
        ),
        CustomerAnswerEvidence(
            label="分析周期",
            value=period_label,
        ),
        CustomerAnswerEvidence(
            label="对象范围",
            value=(
                "通用工业知识"
                if query_mode == "knowledge"
                else "、".join(device_names) if device_names else "当前页面授权范围"
            ),
        ),
        CustomerAnswerEvidence(
            label="指标口径",
            value=_answer_metric_basis(intent),
        ),
        CustomerAnswerEvidence(
            label="数据状态",
            value=(
                "未读取当前设备数据"
                if query_mode == "knowledge"
                else "仍在更新" if updating else "已完成快照"
            ),
        ),
    ]
    return CustomerAnswerMeta(
        result_kind=result_kind,
        capability_state=capability_state,
        data_snapshot_at=snapshot_at,
        data_cutoff_at=cutoff_at,
        period_start=start_at,
        period_end=end_at,
        period_label=period_label,
        updating=updating,
        metric_basis=_answer_metric_basis(intent),
        device_names=device_names,
        workspace=payload.page_context.workspace if payload.page_context else None,
        data_quality=data_quality,
        expert_supplement_status=final_state.get(
            "expert_supplement_status", "not_applicable"
        ),
        evidence=evidence_values,
    )


def sse(event: str, content: object, node: str | None = None) -> str:
    encoded_content = jsonable_encoder(content)
    event_model = SSEEvent(
        event=event,
        node=node,
        content=(
            JsonObject.model_validate(encoded_content)
            if isinstance(encoded_content, dict)
            else encoded_content
        ),
    )
    payload = json.dumps(event_model.model_dump(mode="json"), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def tool_event_content(message: ToolMessage) -> dict[str, object]:
    parsed: dict = {}
    if isinstance(message.content, str):
        try:
            candidate = json.loads(message.content)
            if isinstance(candidate, dict):
                parsed = candidate
        except json.JSONDecodeError:
            parsed = {}
    capabilities = parsed.get("capabilities", [])
    warnings = parsed.get("warnings", [])
    missing_metrics = parsed.get("missing_metrics", [])
    return {
        "tool_call_id": message.tool_call_id,
        "tool_name": message.name or "unknown",
        "status": message.status,
        "capabilities": capabilities if isinstance(capabilities, list) else [],
        "data_status": parsed.get("data_status"),
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "missing_metric_count": len(missing_metrics) if isinstance(missing_metrics, list) else 0,
    }


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    return TokenResponse(access_token=create_access_token(user))


@router.get("/auth/me", response_model=UserRead, tags=["auth"])
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/auth/users", response_model=UserRead, tags=["auth"])
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(Role.admin)),
) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="用户已存在")
    user = User(
        tenant_id=actor.tenant_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()
    allowed_factories = set(factory_ids_for_user(db, actor))
    for factory_id in payload.factory_ids:
        if factory_id not in allowed_factories:
            raise HTTPException(status_code=403, detail="无权分配指定工厂")
        db.add(
            UserFactoryAccess(
                user_id=user.id,
                factory_id=factory_id,
                can_manage_devices=False,
            )
        )
    db.commit()
    db.refresh(user)
    return user


@router.get("/tenant", response_model=TenantRead, tags=["tenancy"])
def current_tenant(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Tenant:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=404, detail="租户不存在或已停用")
    return tenant


@router.get("/factories", response_model=list[FactoryRead], tags=["tenancy"])
def list_factories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Factory]:
    allowed = factory_ids_for_user(db, user)
    if not allowed:
        return []
    return list(
        db.scalars(
            select(Factory)
            .where(Factory.id.in_(allowed), Factory.is_active.is_(True))
            .order_by(Factory.code)
        ).all()
    )


@router.post("/factories", response_model=FactoryRead, tags=["tenancy"])
def create_factory(
    payload: FactoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin)),
) -> Factory:
    existing = db.scalar(
        select(Factory).where(
            Factory.tenant_id == user.tenant_id,
            Factory.code == payload.code,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="工厂编码已存在")
    factory = Factory(tenant_id=user.tenant_id, code=payload.code, name=payload.name)
    db.add(factory)
    db.flush()
    db.add(
        UserFactoryAccess(
            user_id=user.id,
            factory_id=factory.id,
            can_manage_devices=True,
        )
    )
    db.commit()
    db.refresh(factory)
    return factory


@router.post(
    "/factories/{factory_id}/grants",
    response_model=FactoryRead,
    tags=["tenancy"],
)
def grant_factory_access(
    factory_id: uuid.UUID,
    payload: FactoryAccessGrant,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(Role.admin)),
):
    factory_id = _factory_scope(db, actor, factory_id)
    target = db.get(User, payload.user_id)
    if target is None or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    grant = db.get(UserFactoryAccess, (target.id, factory_id))
    if grant is None:
        grant = UserFactoryAccess(
            user_id=target.id,
            factory_id=factory_id,
            can_manage_devices=payload.can_manage_devices,
        )
        db.add(grant)
    else:
        grant.can_manage_devices = payload.can_manage_devices
    db.commit()
    return db.get(Factory, factory_id)


@router.post(
    "/factories/{factory_id}/devices",
    response_model=FactoryDeviceRead,
    tags=["tenancy"],
)
def register_factory_device(
    factory_id: uuid.UUID,
    payload: FactoryDeviceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin)),
) -> FactoryDevice:
    factory_id = _factory_scope(db, user, factory_id)
    existing = db.get(FactoryDevice, payload.device_id)
    if existing is not None and existing.factory_id != factory_id:
        raise HTTPException(status_code=409, detail="设备已归属其他工厂")
    if existing is None:
        existing = FactoryDevice(factory_id=factory_id, **payload.model_dump())
        db.add(existing)
    else:
        existing.device_name = payload.device_name
        existing.device_type = payload.device_type
        existing.is_active = True
    db.commit()
    db.refresh(existing)
    return existing


@router.get(
    "/factories/{factory_id}/devices",
    response_model=list[FactoryDeviceRead],
    tags=["tenancy"],
)
def list_factory_devices(
    factory_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FactoryDevice]:
    factory_id = _factory_scope(db, user, factory_id)
    return list(
        db.scalars(
            select(FactoryDevice)
            .where(
                FactoryDevice.factory_id == factory_id,
                FactoryDevice.is_active.is_(True),
            )
            .order_by(FactoryDevice.device_name)
        ).all()
    )


@router.post(
    "/factories/{factory_id}/devices/sync",
    response_model=list[FactoryDeviceRead],
    tags=["tenancy"],
)
def sync_factory_device_catalog(
    factory_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin)),
) -> list[FactoryDevice]:
    factory_id = _factory_scope(db, user, factory_id)
    service = get_industrial_data_service()
    page_number = 0
    try:
        while page_number < 100:
            page = service.list_devices(page=page_number, page_size=1000)
            sync_factory_devices(db, factory_id, page.data)
            if not page.has_next:
                break
            page_number += 1
    except IndustrialDataError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    return list(
        db.scalars(
            select(FactoryDevice)
            .where(
                FactoryDevice.factory_id == factory_id,
                FactoryDevice.is_active.is_(True),
            )
            .order_by(FactoryDevice.device_name)
        ).all()
    )


@router.get("/devices", response_model=IndustrialDevicePage, tags=["industrial-data"])
def devices(
    page: int = 0,
    page_size: int = Query(100, ge=1, le=1000),
    text_search: str = "",
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    try:
        result = get_industrial_data_service().list_devices(page, page_size, text_search)
        if user.role == Role.admin:
            registered_count = (
                db.scalar(
                    select(func.count())
                    .select_from(FactoryDevice)
                    .join(Factory, Factory.id == FactoryDevice.factory_id)
                    .where(Factory.tenant_id == user.tenant_id)
                )
                or 0
            )
            if registered_count == 0:
                sync_factory_devices(db, resolved_factory_id, result.data)
                db.commit()
        allowed = accessible_device_ids(db, user, resolved_factory_id)
        return filter_device_page(result, allowed)
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/devices/{device_id}/telemetry",
    response_model=IndustrialTelemetryHistory,
    tags=["industrial-data"],
)
def telemetry(
    device_id: str,
    keys: str = "",
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = Query(1000, ge=1, le=10_000),
    agg: Literal["AVG", "MIN", "MAX", "SUM", "COUNT", "NONE"] = "NONE",
    interval_ms: int | None = Query(default=None, ge=1_000),
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    _authorized_scope(db, user, resolved_factory_id, [device_id])
    service = get_industrial_data_service()
    parsed_keys = [key.strip() for key in keys.split(",") if key.strip()]
    try:
        if start_ts is not None and end_ts is not None:
            return service.telemetry_history(
                device_id,
                parsed_keys,
                start_ts,
                end_ts,
                limit=limit,
                agg=agg,
                interval=interval_ms,
            )
        return service.latest_telemetry(device_id, parsed_keys or None)
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/devices/{device_id}/alarms",
    response_model=IndustrialAlarmPage,
    tags=["industrial-data"],
)
def alarms(
    device_id: str,
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    _authorized_scope(db, user, resolved_factory_id, [device_id])
    try:
        return get_industrial_data_service().list_alarms(device_id)
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/chat", tags=["agent"])
def chat(
    payload: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    if payload.debug and user.role != Role.admin:
        raise HTTPException(status_code=403, detail="只有管理员可以启用调试模式")
    settings = get_settings()
    requested_factory_id = payload.page_context.factory_id if payload.page_context else None
    factory_id = _factory_scope(db, user, requested_factory_id)
    device_scope = _authorized_scope(
        db,
        user,
        factory_id,
        payload.effective_device_scope,
    )
    try:
        owned_thread = claim_agent_thread(
            db,
            user,
            factory_id,
            settings.langgraph_checkpoint_namespace,
            payload.thread_id,
        )
        db.commit()
    except AgentThreadOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    graph = request.app.state.graph
    knowledge_citations: list[Citation] = []
    if settings.rag_retrieval_enabled:
        try:
            knowledge_citations = retrieve_citations(
                db,
                payload.message,
                limit=settings.rag_top_k,
                min_score=settings.rag_min_score,
                tenant_id=user.tenant_id,
                factory_id=factory_id,
            )
        except Exception:
            logger.exception("Knowledge retrieval failed; continuing without RAG context")
    graph_payload = {
        "message": payload.message,
        "device_scope": device_scope,
        "presentation_mode": "debug" if payload.debug else "customer",
        "page_workspace": payload.page_context.workspace if payload.page_context else None,
        "page_time_scope": payload.page_context.time_scope if payload.page_context else None,
        "citations": knowledge_citations,
    }
    request_id = payload.request_id or str(uuid.uuid4())
    trace_id = current_trace_id()

    def generate() -> Iterator[str]:
        started = perf_counter()
        previous_event_at = started
        node_timings: dict[str, float] = {}
        tool_names: list[str] = []
        final_state: dict = {}
        try:
            snapshot_at = datetime.now(UTC)
            config = {
                "configurable": {
                    "thread_id": owned_thread.checkpoint_thread_id,
                    "checkpoint_ns": settings.langgraph_checkpoint_namespace,
                }
            }
            for update in graph.stream(
                graph_payload,
                config=config,
                stream_mode="updates",
                durability="exit",
            ):
                node, content = next(iter(update.items()))
                now = perf_counter()
                node_timings[node] = node_timings.get(node, 0) + (now - previous_event_at) * 1000
                previous_event_at = now
                final_state.update(content)
                if node in {"compressor_tools", "power_tools"}:
                    for message in content.get("messages", []):
                        if isinstance(message, ToolMessage):
                            tool_event = tool_event_content(message)
                            tool_names.append(str(tool_event["tool_name"]))
                            METRICS.increment(
                                "agent_tool_calls_total",
                                labels={"tool": str(tool_event["tool_name"])},
                            )
                            yield sse("tool", tool_event, node)
                else:
                    yield sse("node", content if payload.debug else NodeProgressView(), node)
            analysis = final_state.get("analysis")
            public_analysis = analysis if payload.debug else _customer_analysis_view(analysis)
            public_warnings = final_state.get("warnings", []) if payload.debug else (
                public_analysis.warnings if public_analysis else []
            )
            route_decision = final_state.get("route_decision")
            debug_intent = (
                route_decision.get("intent")
                if isinstance(route_decision, dict)
                else getattr(route_decision, "intent", None)
            )
            debug_query_mode = (
                route_decision.get("query_mode")
                if isinstance(route_decision, dict)
                else getattr(route_decision, "query_mode", None)
            )
            debug_domain = (
                route_decision.get("domain")
                if isinstance(route_decision, dict)
                else getattr(route_decision, "domain", None)
            )
            debug_subject = (
                route_decision.get("subject")
                if isinstance(route_decision, dict)
                else getattr(route_decision, "subject", None)
            )
            answer_meta = _customer_answer_meta(final_state, payload, snapshot_at)
            yield sse("message", {
                "request_id": request_id,
                "thread_id": payload.thread_id,
                "message": final_state.get("response", ""),
                "analysis": public_analysis,
                "warnings": public_warnings,
                "citations": final_state.get("citations", []),
                "answer_meta": answer_meta,
                "presentation_mode": "debug" if payload.debug else "customer",
                **(
                    {
                        "intent": (
                            debug_intent
                        ),
                        "query_mode": debug_query_mode,
                        "domain": debug_domain,
                        "subject": debug_subject,
                        "selected_capabilities": (
                            final_state.get("selected_power_capabilities")
                            or final_state.get("selected_capabilities")
                            or []
                        ),
                    }
                    if payload.debug
                    else {}
                ),
            }, "synthesize")
            try:
                selected_capabilities = (
                    final_state.get("selected_power_capabilities")
                    or final_state.get("selected_capabilities")
                    or []
                )
                db.add(
                    AuditEvent(
                        tenant_id=user.tenant_id,
                        factory_id=factory_id,
                        actor_id=user.id,
                        action="assistant.answer.generated",
                        resource_type="assistant_answer",
                        resource_id=request_id,
                        details=AssistantAnswerAuditDetails(
                            thread_id=payload.thread_id,
                            route=final_state.get("route"),
                            query_mode=debug_query_mode,
                            domain=debug_domain,
                            intent=debug_intent,
                            subject=debug_subject,
                            capabilities=list(selected_capabilities),
                            data_snapshot_at=snapshot_at,
                            data_cutoff_at=answer_meta.data_cutoff_at,
                            metric_version="industrial-metrics-v1",
                            rule_version="deterministic-rules-v1",
                            analysis_method=getattr(analysis, "method", None),
                            expert_supplement_status=answer_meta.expert_supplement_status,
                        ).model_dump(mode="json"),
                    )
                )
                duration_ms = (perf_counter() - started) * 1000
                persist_agent_trace(
                    db,
                    trace_id=trace_id,
                    request_id=request_id,
                    tenant_id=user.tenant_id,
                    factory_id=factory_id,
                    user_id=user.id,
                    thread_id=payload.thread_id,
                    operation="agent_chat",
                    status="completed",
                    duration_ms=duration_ms,
                    route=final_state.get("route"),
                    intent=debug_intent,
                    node_timings=node_timings,
                    tool_names=tool_names,
                )
                db.commit()
                METRICS.increment(
                    "agent_runs_total",
                    labels={"status": "completed", "route": str(final_state.get("route") or "unknown")},
                )
                METRICS.observe("agent_run_duration_ms", duration_ms)
            except Exception:
                db.rollback()
                logger.exception("Unable to persist assistant answer audit event")
            yield sse("done", {"thread_id": payload.thread_id})
        except ValidationError:
            logger.exception("Agent state validation failed")
            METRICS.increment("agent_runs_total", labels={"status": "state_error"})
            db.rollback()
            try:
                persist_agent_trace(
                    db,
                    trace_id=trace_id,
                    request_id=request_id,
                    tenant_id=user.tenant_id,
                    factory_id=factory_id,
                    user_id=user.id,
                    thread_id=payload.thread_id,
                    operation="agent_chat",
                    status="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                    node_timings=node_timings,
                    tool_names=tool_names,
                    error_code="AGENT_STATE_VERSION_MISMATCH",
                )
                db.commit()
            except Exception:
                db.rollback()
            yield sse(
                "error",
                {
                    "code": "AGENT_STATE_VERSION_MISMATCH",
                    "message": "当前会话状态版本不兼容，请刷新页面创建新会话后重试。",
                },
            )
        except Exception:
            logger.exception("Agent stream failed")
            METRICS.increment("agent_runs_total", labels={"status": "execution_error"})
            db.rollback()
            try:
                persist_agent_trace(
                    db,
                    trace_id=trace_id,
                    request_id=request_id,
                    tenant_id=user.tenant_id,
                    factory_id=factory_id,
                    user_id=user.id,
                    thread_id=payload.thread_id,
                    operation="agent_chat",
                    status="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                    route=final_state.get("route"),
                    node_timings=node_timings,
                    tool_names=tool_names,
                    error_code="AGENT_EXECUTION_ERROR",
                )
                db.commit()
            except Exception:
                db.rollback()
            yield sse(
                "error",
                {
                    "code": "AGENT_EXECUTION_ERROR",
                    "message": "分析执行失败，请稍后重试；若持续出现请查看 API 日志。",
                },
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Trace-ID": trace_id},
    )


@router.post(
    "/chat/feedback",
    response_model=ChatFeedbackRead,
    tags=["agent"],
)
def chat_feedback(
    payload: ChatFeedbackCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatFeedbackRead:
    try:
        thread = assert_agent_thread_owner(
            db,
            user,
            get_settings().langgraph_checkpoint_namespace,
            payload.thread_id,
        )
    except AgentThreadOwnershipError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    event = AuditEvent(
        tenant_id=user.tenant_id,
        factory_id=thread.factory_id,
        actor_id=user.id,
        action="assistant.answer.feedback",
        resource_type="assistant_answer",
        resource_id=payload.request_id,
        details=ChatFeedbackAuditDetails(
            thread_id=payload.thread_id,
            message_id=payload.message_id,
            rating=payload.rating,
            reasons=payload.reasons,
            comment=payload.comment,
        ).model_dump(mode="json"),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return ChatFeedbackRead(feedback_id=event.id)


@router.post(
    "/compressor-analysis",
    response_model=CompressorAnalysisResult,
    tags=["compressor"],
)
def compressor_analysis(
    payload: CompressorAnalysisRequest,
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    authorized = _authorized_scope(db, user, resolved_factory_id, payload.device_scope)
    try:
        return CompressorAnalysisService().analyze(
            payload.model_copy(update={"device_scope": authorized})
        )
    except CompressorContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/power-analysis",
    response_model=PowerAnalysisResult,
    tags=["power"],
)
def power_analysis(
    payload: PowerAnalysisRequest,
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    authorized = _authorized_scope(db, user, resolved_factory_id, payload.device_scope)
    try:
        return PowerAnalysisService().analyze(
            payload.model_copy(update={"device_scope": authorized})
        )
    except PowerContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/daily-summaries/generate", response_model=DailySummaryRead, tags=["daily-summary"])
def create_daily_summary(
    payload: DailySummaryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.analyst)),
) -> DailySummary:
    factory_id = _factory_scope(db, user, payload.factory_id)
    requested_scope = payload.device_scope or sorted(
        accessible_device_ids(db, user, factory_id)
    )
    authorized_scope = _authorized_scope(db, user, factory_id, requested_scope)
    try:
        return generate_daily_summary(
            db,
            device_scope=authorized_scope,
            generated_by=user.id,
            trigger="manual",
            tenant_id=user.tenant_id,
            factory_id=factory_id,
        )
    except DailySummaryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/daily-summaries", response_model=list[DailySummaryRead], tags=["daily-summary"])
def list_daily_summaries(
    limit: int = Query(30, ge=1, le=100),
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DailySummary]:
    resolved_factory_id = _factory_scope(db, user, factory_id)
    return list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.tenant_id == user.tenant_id,
                DailySummary.factory_id == resolved_factory_id,
            )
            .order_by(DailySummary.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.post("/knowledge/documents", response_model=KnowledgeUploadResponse, tags=["knowledge"])
def upload_document(
    file: UploadFile = File(...),
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.analyst)),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    raw = file.file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="文件不能超过 5 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="MVP 仅支持 UTF-8 文本、Markdown 和 CSV") from exc
    parts = chunk_text(text)
    document = KnowledgeDocument(
        tenant_id=user.tenant_id,
        factory_id=resolved_factory_id,
        filename=file.filename or "untitled.txt",
        media_type=file.content_type or "text/plain",
        created_by=user.id,
        status="processing",
    )
    db.add(document)
    db.flush()
    vectors = embed_texts(parts)
    chunks: list[KnowledgeChunk] = []
    for position, part in enumerate(parts):
        chunk = KnowledgeChunk(document_id=document.id, position=position, content=part)
        db.add(chunk)
        chunks.append(chunk)
    db.flush()
    try:
        upsert_knowledge_vectors(document=document, chunks=chunks, embeddings=vectors)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    document.status = "ready"
    db.commit()
    return KnowledgeUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunks=len(parts),
    )


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentRead], tags=["knowledge"])
def list_documents(
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    return db.scalars(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.tenant_id == user.tenant_id,
            KnowledgeDocument.factory_id == resolved_factory_id,
        )
        .order_by(KnowledgeDocument.created_at.desc())
    ).all()


@router.delete("/knowledge/documents/{document_id}", status_code=204, tags=["knowledge"])
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.analyst)),
):
    document = db.get(KnowledgeDocument, document_id)
    if document is None or document.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    _factory_scope(db, user, document.factory_id)
    try:
        delete_knowledge_vectors(document.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.delete(document)
    db.commit()


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse, tags=["knowledge"])
def knowledge_search(
    q: str,
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    try:
        results = search_knowledge(
            db,
            q,
            tenant_id=user.tenant_id,
            factory_id=resolved_factory_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return KnowledgeSearchResponse(query=q, results=results)


@router.post("/control-plans", response_model=ControlPlanRead, tags=["control"])
def propose_control(payload: ControlPlanCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.analyst))):
    factory_id = _factory_scope(db, user, payload.factory_id)
    _authorized_scope(db, user, factory_id, [payload.device_id])
    return ControlService(db).propose(
        payload.model_copy(update={"factory_id": factory_id}),
        user,
    )


@router.get("/control-plans", response_model=list[ControlPlanRead], tags=["control"])
def list_control_plans(
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_factory_id = _factory_scope(db, user, factory_id)
    return db.scalars(
        select(ControlPlan)
        .where(
            ControlPlan.tenant_id == user.tenant_id,
            ControlPlan.factory_id == resolved_factory_id,
        )
        .order_by(ControlPlan.created_at.desc())
    ).all()


@router.post("/control-plans/{plan_id}/approve", response_model=ControlPlanRead, tags=["control"])
def approve_control(plan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.approver))):
    plan = db.get(ControlPlan, plan_id)
    if plan is None or plan.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="控制计划不存在")
    _factory_scope(db, user, plan.factory_id)
    return ControlService(db).approve_and_execute(plan, user)


@router.post("/control-plans/{plan_id}/reject", response_model=ControlPlanRead, tags=["control"])
def reject_control(plan_id: uuid.UUID, payload: RejectRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.approver))):
    plan = db.get(ControlPlan, plan_id)
    if plan is None or plan.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="控制计划不存在")
    _factory_scope(db, user, plan.factory_id)
    return ControlService(db).reject(plan, user, payload.reason)


@router.get("/audit-events", response_model=list[AuditEventRead], tags=["audit"])
def audit_events(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.approver)),
):
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == user.tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()


@router.get("/agent/traces", response_model=list[AgentTraceRead], tags=["observability"])
def agent_traces(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin)),
) -> list[AgentTrace]:
    return list(
        db.scalars(
            select(AgentTrace)
            .where(AgentTrace.tenant_id == user.tenant_id)
            .order_by(AgentTrace.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.get("/metrics", include_in_schema=False, tags=["observability"])
def metrics(_: User = Depends(require_roles(Role.admin))) -> Response:
    return Response(METRICS.render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/load-forecast/mock", response_model=LoadForecastMockResponse, tags=["forecast"])
def mock_load_forecast() -> LoadForecastMockResponse:
    points = [
        LoadForecastPoint(label="00:00", actual_mw=2.1, ai_prediction_mw=2.0, baseline_mw=2.3, limit_mw=8.6),
        LoadForecastPoint(label="04:00", actual_mw=2.4, ai_prediction_mw=2.7, baseline_mw=2.5, limit_mw=8.6),
        LoadForecastPoint(label="08:00", actual_mw=4.8, ai_prediction_mw=5.1, baseline_mw=4.2, limit_mw=8.6),
        LoadForecastPoint(label="12:00", actual_mw=6.2, ai_prediction_mw=6.8, baseline_mw=5.5, limit_mw=8.6),
        LoadForecastPoint(label="14:00", actual_mw=7.9, ai_prediction_mw=8.7, baseline_mw=7.2, limit_mw=8.6),
        LoadForecastPoint(label="16:00", actual_mw=None, ai_prediction_mw=8.92, baseline_mw=7.8, limit_mw=8.6),
        LoadForecastPoint(label="18:00", actual_mw=None, ai_prediction_mw=7.1, baseline_mw=6.2, limit_mw=8.6),
        LoadForecastPoint(label="20:00", actual_mw=None, ai_prediction_mw=4.4, baseline_mw=3.8, limit_mw=8.6),
        LoadForecastPoint(label="24:00", actual_mw=None, ai_prediction_mw=1.6, baseline_mw=1.9, limit_mw=8.6),
    ]
    return LoadForecastMockResponse(
        confidence=0.92,
        peak_prediction_mw=8.92,
        risk_window="14:30-16:00",
        points=points,
    )


@router.get("/demand-forecast", response_model=DemandForecastResponse, tags=["forecast"])
def demand_forecast(
    device_id: str = Query(min_length=1, max_length=128),
    factory_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DemandForecastResponse:
    resolved_factory_id = _factory_scope(db, user, factory_id)
    _authorized_scope(db, user, resolved_factory_id, [device_id])
    try:
        return DemandForecastService().forecast(device_id)
    except DemandForecastError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/health", include_in_schema=False)
def health() -> HealthResponse:
    return HealthResponse(
        time=datetime.now(UTC),
        industrial_data_provider=get_settings().industrial_data_provider,
    )
