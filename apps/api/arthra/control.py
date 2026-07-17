import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from arthra.config import Settings, get_settings
from arthra.contracts import JsonObject
from arthra.models import AuditEvent, ControlPlan, ControlStatus, User
from arthra.schemas import (
    ControlParams,
    ControlPlanCreate,
    EmptyControlParams,
    SetModeParams,
    SetPowerLimitParams,
)
from arthra.thingsboard import ThingsBoardClient, ThingsBoardError


class ControlPolicy:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def parse_params(method: str, params: ControlParams | dict[str, Any]) -> ControlParams:
        model = {
            "setPowerLimit": SetPowerLimitParams,
            "setMode": SetModeParams,
            "start": EmptyControlParams,
            "stop": EmptyControlParams,
        }.get(method)
        if model is None:
            raise ValueError(f"控制方法 {method} 不在白名单")
        raw = params.model_dump() if hasattr(params, "model_dump") else params
        try:
            return model.model_validate(raw)
        except ValidationError as exc:
            if method == "setMode":
                raise ValueError("模式仅允许 auto/manual/eco/standby") from exc
            if method == "setPowerLimit":
                raise ValueError("功率限制参数必须是非负数值") from exc
            raise ValueError(f"控制方法 {method} 不允许额外参数") from exc

    def validate(self, device_type: str, method: str, params: ControlParams | dict[str, Any]) -> ControlParams:
        if device_type not in self.settings.control_allowed_device_types:
            raise ValueError(f"设备类型 {device_type} 不在控制白名单")
        if method not in self.settings.control_allowed_methods:
            raise ValueError(f"控制方法 {method} 不在白名单")
        parsed = self.parse_params(method, params)
        if method == "setPowerLimit":
            value = parsed.value if isinstance(parsed, SetPowerLimitParams) else None
            if value is None or value > self.settings.control_max_power_limit_kw:
                raise ValueError(
                    f"功率限制必须在 0 到 {self.settings.control_max_power_limit_kw:g} kW 之间"
                )
        return parsed


class ControlService:
    def __init__(
        self,
        db: Session,
        tb: ThingsBoardClient | None = None,
        policy: ControlPolicy | None = None,
    ):
        self.db = db
        self.tb = tb or ThingsBoardClient()
        self.policy = policy or ControlPolicy()

    def _audit(
        self,
        actor_id: uuid.UUID | None,
        action: str,
        plan: ControlPlan,
        details: JsonObject,
    ) -> None:
        self.db.add(
            AuditEvent(
                actor_id=actor_id,
                action=action,
                resource_type="control_plan",
                resource_id=str(plan.id),
                details=details.model_dump(mode="json"),
            )
        )

    def propose(self, payload: ControlPlanCreate, actor: User) -> ControlPlan:
        try:
            params = self.policy.validate(payload.device_type, payload.method, payload.params)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        plan = ControlPlan(
            **payload.model_dump(exclude={"params"}),
            params=params.model_dump(mode="json"),
            created_by=actor.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().control_plan_ttl_seconds),
        )
        self.db.add(plan)
        self.db.flush()
        self._audit(
            actor.id,
            "control.proposed",
            plan,
            JsonObject({"method": plan.method, "params": plan.params}),
        )
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def reject(self, plan: ControlPlan, actor: User, reason: str) -> ControlPlan:
        self._assert_proposed(plan)
        plan.status = ControlStatus.rejected
        self._audit(actor.id, "control.rejected", plan, JsonObject({"reason": reason}))
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def approve_and_execute(self, plan: ControlPlan, actor: User) -> ControlPlan:
        self._assert_proposed(plan)
        now = datetime.now(UTC)
        if plan.expires_at <= now:
            plan.status = ControlStatus.expired
            self._audit(actor.id, "control.expired", plan, JsonObject({}))
            self.db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="控制计划已过期")
        try:
            params = self.policy.validate(plan.device_type, plan.method, plan.params)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        plan.status = ControlStatus.approved
        plan.approved_by = actor.id
        plan.approved_at = now
        self._audit(actor.id, "control.approved", plan, JsonObject({}))
        self.db.flush()
        try:
            result = self.tb.send_rpc(
                plan.device_id,
                plan.method,
                JsonObject.model_validate(params.model_dump(mode="json")),
            )
            plan.status = ControlStatus.executed
            plan.execution_result = result.model_dump(mode="json")
            plan.executed_at = datetime.now(UTC)
            self._audit(
                actor.id,
                "control.executed",
                plan,
                JsonObject({"result": result.model_dump(mode="json")}),
            )
        except ThingsBoardError as exc:
            plan.status = ControlStatus.failed
            plan.execution_result = {"error": str(exc)}
            self._audit(
                actor.id,
                "control.failed",
                plan,
                JsonObject({"error": str(exc)}),
            )
        self.db.commit()
        self.db.refresh(plan)
        return plan

    @staticmethod
    def _assert_proposed(plan: ControlPlan) -> None:
        if plan.status != ControlStatus.proposed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="控制计划当前状态不可操作")
