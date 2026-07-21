"""
SchoolOS – Authentication Router
==================================
POST /auth/token  — Exchange email + password for a JWT access token.

Security design
---------------
- Failed logins always return 401 with a generic "Invalid credentials"
  message regardless of whether the tenant, email, or password is wrong.
  This prevents user/tenant enumeration.
- No rate limiting middleware is available in this environment.
  A simple in-memory per-IP counter is used as a bounded safeguard.
  Replace with Redis-backed rate limiting before high-scale production use.
- Successful and repeated-failure logins are audit-logged.
- Passwords and hashes are never logged.

Password provisioning
---------------------
No parent accounts have hashed passwords by default.
Use the seed fixture in tests/parent/conftest.py to create test accounts.
For production, an administrator provisioning endpoint is required
(not part of Phase 8.1 scope).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.jwt import create_access_token, get_current_user
from shared.auth.passwords import verify_password
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Tenant, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

# ─────────────────────────────────────────────────────────────────────────────
# Simple in-memory rate limiter
# Replace with Redis-backed implementation for production scale.
# ─────────────────────────────────────────────────────────────────────────────

_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_ATTEMPTS = 10

_rate_counters: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()


def _is_rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        attempts = _rate_counters[client_ip]
        # Purge old attempts outside the window
        _rate_counters[client_ip] = [t for t in attempts if t > window_start]
        if len(_rate_counters[client_ip]) >= _RATE_LIMIT_MAX_ATTEMPTS:
            return True
        _rate_counters[client_ip].append(now)
        return False


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Request / response schemas
# ─────────────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    email: str
    password: str
    tenant_slug: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class MeResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    is_active: bool


# ─────────────────────────────────────────────────────────────────────────────
# Login endpoint
# ─────────────────────────────────────────────────────────────────────────────

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Obtain a JWT access token",
    description=(
        "Exchange email and password for a JWT. "
        "All failure modes return 401 to prevent enumeration. "
        "Rate-limited to 10 attempts per minute per client IP."
    ),
)
async def login(
    body: TokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = _get_client_ip(request)
    if _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait before trying again.",
        )

    # ── Resolve tenant ────────────────────────────────────────────────────────
    # We intentionally do NOT raise a distinct error for unknown tenants —
    # every failure path returns the same 401.
    result = await db.execute(
        select(Tenant).where(
            Tenant.slug == body.tenant_slug.lower().strip(),
            Tenant.is_active.is_(True),
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        # Do not log the slug — avoid leaking tenant enumeration in logs.
        raise _INVALID_CREDENTIALS

    await set_tenant_context(db, tenant.id)

    # ── Look up user by email within this tenant ──────────────────────────────
    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.tenant_id == tenant.id,
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise _INVALID_CREDENTIALS

    # ── Verify password ───────────────────────────────────────────────────────
    if not verify_password(body.password, user.password_hash):
        logger.warning(
            "auth.login_failed | tenant=%s user_id=%s",
            tenant.slug,
            str(user.id),
        )
        await log_action(
            db=db,
            tenant_id=tenant.id,
            action="auth.login_failed",
            entity_type="User",
            entity_id=user.id,
            details={"reason": "invalid_password", "client_ip": client_ip},
        )
        await db.commit()
        raise _INVALID_CREDENTIALS

    # ── Issue token ───────────────────────────────────────────────────────────
    from shared.config import settings

    token = create_access_token(
        user_id=str(user.id),
        role=user.role,
        tenant_slug=tenant.slug,
    )

    logger.info("auth.login_success | tenant=%s user_id=%s", tenant.slug, str(user.id))
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="auth.login_success",
        entity_type="User",
        entity_id=user.id,
        details={"client_ip": client_ip},
    )
    await db.commit()

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get authenticated user profile",
    description=(
        "Returns the authenticated user resolved from the database using "
        "validated JWT + tenant context."
    ),
)
async def me(
    current_user=Depends(get_current_user),
    tenant=Depends(resolve_tenant),
):
    return MeResponse(
        user_id=str(current_user.id),
        name=current_user.name,
        email=current_user.email or "",
        role=current_user.role,
        tenant_id=str(current_user.tenant_id),
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        is_active=bool(current_user.is_active),
    )
