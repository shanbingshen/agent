import uuid

import pytest
from arthra.models import (
    AgentThread,
    Factory,
    FactoryDevice,
    Role,
    Tenant,
    User,
    UserFactoryAccess,
)
from arthra.tenancy import (
    AgentThreadOwnershipError,
    TenantAccessError,
    authorize_device_scope,
    bootstrap_default_scope,
    claim_agent_thread,
    resolve_factory_id,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Tenant.__table__.create(engine)
    Factory.__table__.create(engine)
    User.__table__.create(engine)
    UserFactoryAccess.__table__.create(engine)
    FactoryDevice.__table__.create(engine)
    AgentThread.__table__.create(engine)
    with Session(engine) as session:
        bootstrap_default_scope(session)
        session.commit()
        yield session


def _user(db: Session, email: str, role: Role = Role.analyst) -> User:
    user = User(email=email, password_hash="test", role=role)
    db.add(user)
    db.flush()
    return user


def test_factory_device_scope_is_enforced(db: Session):
    user = _user(db, "analyst@example.com")
    factory = db.get(Factory, uuid.UUID("00000000-0000-0000-0000-000000000001"))
    assert factory is not None
    db.add(UserFactoryAccess(user_id=user.id, factory_id=factory.id))
    db.add(
        FactoryDevice(
            device_id="meter-1",
            factory_id=factory.id,
            device_name="Meter 1",
            device_type="meter",
        )
    )
    db.commit()

    resolved = resolve_factory_id(db, user, factory.id)
    assert authorize_device_scope(db, user, resolved, ["meter-1"]) == ["meter-1"]
    with pytest.raises(TenantAccessError, match="无权访问设备"):
        authorize_device_scope(db, user, resolved, ["meter-2"])


def test_agent_thread_has_single_owner_and_factory(db: Session):
    owner = _user(db, "owner@example.com")
    other = _user(db, "other@example.com")
    factory = db.get(Factory, uuid.UUID("00000000-0000-0000-0000-000000000001"))
    assert factory is not None
    db.add_all(
        [
            UserFactoryAccess(user_id=owner.id, factory_id=factory.id),
            UserFactoryAccess(user_id=other.id, factory_id=factory.id),
        ]
    )
    db.commit()

    thread = claim_agent_thread(db, owner, factory.id, "agent-v2", "client-thread")
    db.commit()
    assert str(owner.tenant_id) in thread.checkpoint_thread_id
    assert str(factory.id) in thread.checkpoint_thread_id
    with pytest.raises(AgentThreadOwnershipError, match="其他用户或工厂"):
        claim_agent_thread(db, other, factory.id, "agent-v2", "client-thread")
