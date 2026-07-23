import base64
import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from arthra.config import get_settings
from arthra.db import get_db
from arthra.models import DEFAULT_FACTORY_ID, DEFAULT_TENANT_ID, Role, User, UserFactoryAccess
from arthra.tenancy import bootstrap_default_scope

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "tid": str(user.tenant_id),
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的凭据")
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tid"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise credentials_error from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.tenant_id != tenant_id:
        raise credentials_error
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return dependency


def bootstrap_admin(db: Session) -> None:
    settings = get_settings()
    bootstrap_default_scope(db)
    existing = db.scalar(select(User).where(User.email == settings.bootstrap_admin_email))
    if existing is None:
        existing = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=settings.bootstrap_admin_email,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role=Role.admin,
        )
        db.add(existing)
        db.flush()
    grant = db.get(UserFactoryAccess, (existing.id, DEFAULT_FACTORY_ID))
    if grant is None:
        db.add(
            UserFactoryAccess(
                user_id=existing.id,
                factory_id=DEFAULT_FACTORY_ID,
                can_manage_devices=True,
            )
        )
    db.commit()
