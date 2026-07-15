"""
SchoolOS – JWT Authentication
==============================
Provides token creation, validation, and the get_current_user FastAPI
dependency.

Security model
--------------
- The JWT role claim is informational metadata ONLY.
- Authorization always uses user.role loaded from PostgreSQL.
- The user's is_active flag and tenant_id are validated against the DB record.
- The tenant claim in the token is cross-validated against the resolved tenant
  to prevent cross-tenant token replay.

Production requirements
-----------------------
- SECRET_KEY must be at least 32 characters.
- SECRET_KEY must not be the default development value.
- The application refuses to start in production with a weak secret.
  Call validate_secret_key_for_environment() during startup.

Never log tokens, passwords, or password hashes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_ISSUER = "schoolos-gateway"
_AUDIENCE = "schoolos-client"

_KNOWN_WEAK_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "dev-secret-change-in-production",
        "secret",
        "changeme",
        "password",
        "development",
        "test",
        "schoolos",
        "default",
        "your-secret-key",
    }
)

_bearer_scheme = HTTPBearer(auto_error=True)


# ─────────────────────────────────────────────────────────────────────────────
# Production startup validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_secret_key_for_environment() -> None:
    """
    Must be called once during gateway startup (lifespan).

    Raises RuntimeError if the application is running in production with a
    default, empty, or insufficiently short SECRET_KEY. This stops a
    misconfigured production deployment before it can accept traffic.

    Development and test environments log a warning but continue.
    """
    from shared.config import settings  # local import to avoid circular deps

    secret = settings.secret_key
    is_production = settings.app_env == "production"

    weak = (
        not secret
        or secret.lower() in _KNOWN_WEAK_SECRETS
        or len(secret) < 32
    )

    if weak and is_production:
        raise RuntimeError(
            "SchoolOS cannot start in production with a default, empty, or "
            "insufficiently strong SECRET_KEY. "
            "Set a randomly generated SECRET_KEY of at least 32 characters "
            "in the environment or Render secret store."
        )

    if weak:
        logger.warning(
            "SECRET_KEY is weak or default. This is acceptable for "
            "development/test only. Do not use in production."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Token creation
# ─────────────────────────────────────────────────────────────────────────────

def create_access_token(
    *,
    user_id: str,
    role: str,
    tenant_slug: str,
) -> str:
    """
    Creates a signed JWT access token.

    The role claim is informational only — authorization must use the
    user.role column loaded from the database.
    """
    from shared.config import settings  # local import to avoid circular deps

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,           # informational — do not authorize from this alone
        "tenant": tenant_slug,  # validated against X-Tenant-Slug on every request
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


# ─────────────────────────────────────────────────────────────────────────────
# Token decoding (internal)
# ─────────────────────────────────────────────────────────────────────────────

def _decode_raw_token(token: str) -> dict[str, Any]:
    from shared.config import settings

    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except JWTError:
        # Do not log the token or raw error — it may contain sensitive data.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency — get_current_user
# ─────────────────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    tenant=Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    FastAPI dependency.

    Authorization flow:
    1. Validate JWT signature and expiry.
    2. Resolve the tenant from X-Tenant-Slug header (via Depends).
    3. Cross-validate the token's tenant claim against the resolved tenant.
    4. Load the User record from PostgreSQL.
    5. Confirm user.is_active is True.
    6. Confirm user.tenant_id matches the resolved tenant.

    Returns the User ORM object. The caller uses user.role (from DB) for
    all authorization decisions — never the JWT role claim alone.
    """
    from shared.db.models import User  # local import to avoid circular deps

    payload = _decode_raw_token(credentials.credentials)

    # ── 1. Extract and validate sub claim ────────────────────────────────────
    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── 2. Cross-validate tenant claim against X-Tenant-Slug ─────────────────
    # resolve_tenant is injected via Depends, so it can be overridden in tests.
    token_tenant: str = payload.get("tenant", "")
    if token_tenant != tenant.slug:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    resolved_tenant_id = tenant.id

    # ── 3. Load user from PostgreSQL ─────────────────────────────────────────
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    # Use a generic message for all failure modes — do not distinguish between
    # "user not found" and "wrong tenant" to prevent user enumeration.
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.tenant_id != resolved_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
