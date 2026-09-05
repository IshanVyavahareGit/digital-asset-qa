"""Authentication & authorization primitives.

- Passwords hashed with bcrypt (via passlib).
- Stateless sessions via signed JWTs (HS256).
- Role gating exposed as FastAPI dependencies (require_manager / require_role).
- Two demo accounts are seeded on startup so the reviewer can log in immediately.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Role
from app.db.models import User
from app.db.session import SessionLocal, get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl is only used by the OpenAPI docs "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)


# --- password + token helpers ------------------------------------------------


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": user.id, "role": user.role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# --- dependencies ------------------------------------------------------------


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("sub")
    except JWTError:
        raise creds_error
    if not user_id:
        raise creds_error

    user = db.get(User, user_id)
    if user is None:
        raise creds_error
    return user


def require_role(*roles: Role):
    """Build a dependency that allows only the given role(s)."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in {r.value for r in roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(r.value for r in roles)}",
            )
        return user

    return _dep


# Convenience: managers run QA + overrides; designers are read-only.
require_manager = require_role(Role.manager)


# --- seed --------------------------------------------------------------------

DEMO_USERS = [
    ("manager@tec.dev", "manager123", Role.manager),
    ("designer@tec.dev", "designer123", Role.designer),
]


def seed_demo_users() -> None:
    """Idempotently create the two demo accounts on first boot."""
    db = SessionLocal()
    try:
        for email, password, role in DEMO_USERS:
            exists = db.scalar(select(User).where(User.email == email))
            if exists:
                continue
            db.add(
                User(email=email, hashed_password=hash_password(password), role=role)
            )
        db.commit()
    finally:
        db.close()
