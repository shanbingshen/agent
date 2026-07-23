import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.industrial_data.schemas import IndustrialDevice, IndustrialDevicePage
from arthra.models import (
    DEFAULT_FACTORY_ID,
    DEFAULT_TENANT_ID,
    AgentThread,
    Factory,
    FactoryDevice,
    Role,
    Tenant,
    User,
    UserFactoryAccess,
)


class TenantAccessError(RuntimeError):
    pass


class AgentThreadOwnershipError(RuntimeError):
    pass


def bootstrap_default_scope(db: Session) -> None:
    tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    if tenant is None:
        db.add(
            Tenant(
                id=DEFAULT_TENANT_ID,
                slug="default",
                name="默认租户",
            )
        )
        db.flush()
    factory = db.get(Factory, DEFAULT_FACTORY_ID)
    if factory is None:
        db.add(
            Factory(
                id=DEFAULT_FACTORY_ID,
                tenant_id=DEFAULT_TENANT_ID,
                code="DEFAULT",
                name="默认工厂",
            )
        )
        db.flush()


def factory_ids_for_user(db: Session, user: User) -> list[uuid.UUID]:
    if user.role == Role.admin:
        return list(
            db.scalars(
                select(Factory.id).where(
                    Factory.tenant_id == user.tenant_id,
                    Factory.is_active.is_(True),
                )
            ).all()
        )
    return list(
        db.scalars(
            select(UserFactoryAccess.factory_id)
            .join(Factory, Factory.id == UserFactoryAccess.factory_id)
            .where(
                UserFactoryAccess.user_id == user.id,
                Factory.tenant_id == user.tenant_id,
                Factory.is_active.is_(True),
            )
        ).all()
    )


def resolve_factory_id(
    db: Session,
    user: User,
    requested_factory_id: uuid.UUID | str | None,
) -> uuid.UUID:
    try:
        requested = uuid.UUID(str(requested_factory_id)) if requested_factory_id else None
    except ValueError as exc:
        raise TenantAccessError("工厂标识格式不正确") from exc
    allowed = factory_ids_for_user(db, user)
    if requested is not None:
        if requested not in allowed:
            raise TenantAccessError("无权访问指定工厂")
        return requested
    if DEFAULT_FACTORY_ID in allowed:
        return DEFAULT_FACTORY_ID
    if len(allowed) == 1:
        return allowed[0]
    if not allowed:
        raise TenantAccessError("当前账号尚未分配可访问工厂")
    raise TenantAccessError("当前账号可访问多个工厂，请明确选择工厂")


def sync_factory_devices(
    db: Session,
    factory_id: uuid.UUID,
    devices: list[IndustrialDevice],
) -> None:
    for device in devices:
        record = db.get(FactoryDevice, device.id.id)
        if record is None:
            db.add(
                FactoryDevice(
                    device_id=device.id.id,
                    factory_id=factory_id,
                    device_name=device.name,
                    device_type=device.type,
                )
            )
            continue
        if record.factory_id != factory_id:
            continue
        record.device_name = device.name
        record.device_type = device.type
        record.is_active = True


def accessible_device_ids(db: Session, user: User, factory_id: uuid.UUID) -> set[str]:
    if factory_id not in factory_ids_for_user(db, user):
        raise TenantAccessError("无权访问指定工厂")
    return set(
        db.scalars(
            select(FactoryDevice.device_id).where(
                FactoryDevice.factory_id == factory_id,
                FactoryDevice.is_active.is_(True),
            )
        ).all()
    )


def authorize_device_scope(
    db: Session,
    user: User,
    factory_id: uuid.UUID,
    device_ids: list[str],
) -> list[str]:
    requested = list(dict.fromkeys(device_ids))
    if not requested:
        return []
    allowed = accessible_device_ids(db, user, factory_id)
    missing = [device_id for device_id in requested if device_id not in allowed]
    if missing:
        raise TenantAccessError(f"无权访问设备：{', '.join(missing[:5])}")
    return requested


def filter_device_page(
    page: IndustrialDevicePage,
    allowed_device_ids: set[str],
) -> IndustrialDevicePage:
    rows = [device for device in page.data if device.id.id in allowed_device_ids]
    return IndustrialDevicePage(
        data=rows,
        total_pages=1 if rows else 0,
        total_elements=len(rows),
        has_next=False,
    )


def claim_agent_thread(
    db: Session,
    user: User,
    factory_id: uuid.UUID,
    checkpoint_ns: str,
    client_thread_id: str,
) -> AgentThread:
    thread = db.scalar(
        select(AgentThread).where(
            AgentThread.checkpoint_ns == checkpoint_ns,
            AgentThread.client_thread_id == client_thread_id,
        )
    )
    if thread is not None:
        if (
            thread.owner_user_id != user.id
            or thread.tenant_id != user.tenant_id
            or thread.factory_id != factory_id
        ):
            raise AgentThreadOwnershipError("该 Agent 会话已归属于其他用户或工厂")
        thread.last_used_at = datetime.now(UTC)
        return thread
    checkpoint_thread_id = (
        f"{user.tenant_id}:{factory_id}:{user.id}:{client_thread_id}"
    )
    thread = AgentThread(
        tenant_id=user.tenant_id,
        factory_id=factory_id,
        owner_user_id=user.id,
        checkpoint_ns=checkpoint_ns,
        client_thread_id=client_thread_id,
        checkpoint_thread_id=checkpoint_thread_id,
    )
    db.add(thread)
    db.flush()
    return thread


def assert_agent_thread_owner(
    db: Session,
    user: User,
    checkpoint_ns: str,
    client_thread_id: str,
) -> AgentThread:
    thread = db.scalar(
        select(AgentThread).where(
            AgentThread.checkpoint_ns == checkpoint_ns,
            AgentThread.client_thread_id == client_thread_id,
        )
    )
    if thread is None or thread.owner_user_id != user.id or thread.tenant_id != user.tenant_id:
        raise AgentThreadOwnershipError("Agent 会话不存在或不属于当前用户")
    return thread
