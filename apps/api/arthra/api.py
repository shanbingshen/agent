import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langchain_core.messages import ToolMessage
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.context import CompressorContextError
from arthra.compressor.schemas import CompressorAnalysisRequest, CompressorAnalysisResult
from arthra.config import get_settings
from arthra.contracts import JsonObject
from arthra.control import ControlService
from arthra.daily_summary import DailySummaryError, generate_daily_summary
from arthra.db import get_db
from arthra.industrial_data import IndustrialDataError
from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.schemas import (
    IndustrialAlarmPage,
    IndustrialDevicePage,
    IndustrialTelemetryHistory,
)
from arthra.knowledge import chunk_text, embed_texts, search_knowledge
from arthra.models import (
    AuditEvent,
    ControlPlan,
    DailySummary,
    KnowledgeChunk,
    KnowledgeDocument,
    Role,
    User,
)
from arthra.power.analysis import PowerAnalysisService
from arthra.power.context import PowerContextError
from arthra.power.schemas import PowerAnalysisRequest, PowerAnalysisResult
from arthra.schemas import (
    AuditEventRead,
    ChatRequest,
    ControlPlanCreate,
    ControlPlanRead,
    CustomerAnalysisView,
    CustomerWarningView,
    DailySummaryCreate,
    DailySummaryRead,
    HealthResponse,
    KnowledgeDocumentRead,
    KnowledgeSearchResponse,
    KnowledgeUploadResponse,
    LoginRequest,
    NodeProgressView,
    RejectRequest,
    SSEEvent,
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

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


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
    _: User = Depends(require_roles(Role.admin)),
) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="用户已存在")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/devices", response_model=IndustrialDevicePage, tags=["industrial-data"])
def devices(page: int = 0, page_size: int = Query(100, ge=1, le=1000), text_search: str = "", _: User = Depends(get_current_user)):
    try:
        return get_industrial_data_service().list_devices(page, page_size, text_search)
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
    _: User = Depends(get_current_user),
):
    service = get_industrial_data_service()
    parsed_keys = [key.strip() for key in keys.split(",") if key.strip()]
    try:
        if start_ts is not None and end_ts is not None:
            return service.telemetry_history(device_id, parsed_keys, start_ts, end_ts)
        return service.latest_telemetry(device_id, parsed_keys or None)
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/devices/{device_id}/alarms",
    response_model=IndustrialAlarmPage,
    tags=["industrial-data"],
)
def alarms(device_id: str, _: User = Depends(get_current_user)):
    try:
        return get_industrial_data_service().list_alarms(device_id)
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/chat", tags=["agent"])
def chat(payload: ChatRequest, request: Request, user: User = Depends(get_current_user)) -> StreamingResponse:
    if payload.debug and user.role != Role.admin:
        raise HTTPException(status_code=403, detail="只有管理员可以启用调试模式")
    graph = request.app.state.graph
    graph_payload = {
        "message": payload.message,
        "device_scope": payload.effective_device_scope,
        "presentation_mode": "debug" if payload.debug else "customer",
    }

    def generate() -> Iterator[str]:
        try:
            config = {
                "configurable": {
                    "thread_id": payload.thread_id,
                    "checkpoint_ns": get_settings().langgraph_checkpoint_namespace,
                }
            }
            final_state: dict = {}
            for update in graph.stream(
                graph_payload,
                config=config,
                stream_mode="updates",
                durability="exit",
            ):
                node, content = next(iter(update.items()))
                final_state.update(content)
                if node in {"compressor_tools", "power_tools"}:
                    for message in content.get("messages", []):
                        if isinstance(message, ToolMessage):
                            yield sse("tool", tool_event_content(message), node)
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
            yield sse("message", {
                "request_id": payload.request_id,
                "thread_id": payload.thread_id,
                "message": final_state.get("response", ""),
                "analysis": public_analysis,
                "warnings": public_warnings,
                "citations": final_state.get("citations", []),
                "presentation_mode": "debug" if payload.debug else "customer",
                **(
                    {
                        "intent": (
                            debug_intent
                        ),
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
            yield sse("done", {"thread_id": payload.thread_id})
        except ValidationError:
            logger.exception("Agent state validation failed")
            yield sse(
                "error",
                {
                    "code": "AGENT_STATE_VERSION_MISMATCH",
                    "message": "当前会话状态版本不兼容，请刷新页面创建新会话后重试。",
                },
            )
        except Exception:
            logger.exception("Agent stream failed")
            yield sse(
                "error",
                {
                    "code": "AGENT_EXECUTION_ERROR",
                    "message": "分析执行失败，请稍后重试；若持续出现请查看 API 日志。",
                },
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post(
    "/compressor-analysis",
    response_model=CompressorAnalysisResult,
    tags=["compressor"],
)
def compressor_analysis(
    payload: CompressorAnalysisRequest,
    _: User = Depends(get_current_user),
):
    try:
        return CompressorAnalysisService().analyze(payload)
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
    _: User = Depends(get_current_user),
):
    try:
        return PowerAnalysisService().analyze(payload)
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
    try:
        return generate_daily_summary(
            db,
            device_scope=payload.device_scope,
            generated_by=user.id,
            trigger="manual",
        )
    except DailySummaryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndustrialDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/daily-summaries", response_model=list[DailySummaryRead], tags=["daily-summary"])
def list_daily_summaries(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DailySummary]:
    return list(
        db.scalars(
            select(DailySummary)
            .order_by(DailySummary.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.post("/knowledge/documents", response_model=KnowledgeUploadResponse, tags=["knowledge"])
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.analyst)),
):
    raw = file.file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="文件不能超过 5 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="MVP 仅支持 UTF-8 文本、Markdown 和 CSV") from exc
    parts = chunk_text(text)
    document = KnowledgeDocument(filename=file.filename or "untitled.txt", media_type=file.content_type or "text/plain", created_by=user.id, status="processing")
    db.add(document)
    db.flush()
    vectors = embed_texts(parts)
    for position, (part, vector) in enumerate(zip(parts, vectors, strict=True)):
        db.add(KnowledgeChunk(document_id=document.id, position=position, content=part, embedding=vector))
    document.status = "ready"
    db.commit()
    return KnowledgeUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunks=len(parts),
    )


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentRead], tags=["knowledge"])
def list_documents(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())).all()


@router.delete("/knowledge/documents/{document_id}", status_code=204, tags=["knowledge"])
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.admin, Role.analyst))):
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    db.delete(document)
    db.commit()


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse, tags=["knowledge"])
def knowledge_search(q: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return KnowledgeSearchResponse(query=q, results=search_knowledge(db, q))


@router.post("/control-plans", response_model=ControlPlanRead, tags=["control"])
def propose_control(payload: ControlPlanCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.analyst))):
    return ControlService(db).propose(payload, user)


@router.get("/control-plans", response_model=list[ControlPlanRead], tags=["control"])
def list_control_plans(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(ControlPlan).order_by(ControlPlan.created_at.desc())).all()


@router.post("/control-plans/{plan_id}/approve", response_model=ControlPlanRead, tags=["control"])
def approve_control(plan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.approver))):
    plan = db.get(ControlPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="控制计划不存在")
    return ControlService(db).approve_and_execute(plan, user)


@router.post("/control-plans/{plan_id}/reject", response_model=ControlPlanRead, tags=["control"])
def reject_control(plan_id: uuid.UUID, payload: RejectRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin, Role.approver))):
    plan = db.get(ControlPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="控制计划不存在")
    return ControlService(db).reject(plan, user, payload.reason)


@router.get("/audit-events", response_model=list[AuditEventRead], tags=["audit"])
def audit_events(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_roles(Role.admin, Role.approver))):
    return db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()


@router.get("/health", include_in_schema=False)
def health() -> HealthResponse:
    return HealthResponse(
        time=datetime.now(UTC),
        industrial_data_provider=get_settings().industrial_data_provider,
    )
