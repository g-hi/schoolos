from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Literal, TypeVar

from fastapi import APIRouter, HTTPException, Request, status
from passlib.context import CryptContext
from pydantic import BaseModel, ValidationError
from json import JSONDecodeError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.connection import AsyncSessionLocal
from shared.db.models import Tenant, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/demo-bootstrap", tags=["Internal"])

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ALLOWED_ROLES = {"teacher", "parent", "principal"}
_FEATURE_FLAG_ENV = "SCHOOLOS_ENABLE_DEMO_BOOTSTRAP"
_SECRET_ENV = "SCHOOLOS_DEMO_BOOTSTRAP_SECRET"
_SECRET_HEADER = "X-SchoolOS-Bootstrap-Secret"


class _NotFoundGate(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


class _Conflict(HTTPException):
    def __init__(self, message: str = "Demo bootstrap conflict.") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=message)


TModel = TypeVar("TModel", bound=BaseModel)


class StatusAccountInput(BaseModel):
    email: str
    role: str


class StatusRequest(BaseModel):
    tenant_slug: str
    accounts: list[StatusAccountInput]


class ApplyTenantInput(BaseModel):
    slug: str
    name: str
    create_if_missing: bool


class ApplyAccountInput(BaseModel):
    email: str
    role: str
    display_name: str | None = None
    password: str


class ApplyRequest(BaseModel):
    tenant: ApplyTenantInput
    accounts: list[ApplyAccountInput]


@dataclass
class NormalizedAccount:
    email: str
    role: str
    display_name: str | None = None
    password: str | None = None


def get_sessionmaker():
    return AsyncSessionLocal


def _normalize_slug(value: str) -> str:
    return value.lower().strip()


def _normalize_email(value: str) -> str:
    return value.lower().strip()


def _validate_password(password: str) -> None:
    # SchoolOS currently has no stricter backend password policy than non-empty.
    if not password or not password.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid request body.",
        )


async def _parse_model(request: Request, model_type: type[TModel]) -> TModel:
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError, JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid request body.",
        )

    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc


def _validate_roles_and_emails(
    raw_accounts: list[StatusAccountInput] | list[ApplyAccountInput],
) -> list[NormalizedAccount]:
    if len(raw_accounts) != 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid request body.",
        )

    normalized: list[NormalizedAccount] = []
    seen_emails: set[str] = set()
    role_counts = {"teacher": 0, "parent": 0, "principal": 0}

    for account in raw_accounts:
        role = account.role.strip().lower()
        if role not in _ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid request body.",
            )
        role_counts[role] += 1

        email = _normalize_email(account.email)
        if not email or email in seen_emails:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid request body.",
            )
        seen_emails.add(email)

        if isinstance(account, ApplyAccountInput):
            _validate_password(account.password)
            normalized.append(
                NormalizedAccount(
                    email=email,
                    role=role,
                    display_name=(account.display_name or "").strip() or None,
                    password=account.password,
                )
            )
        else:
            normalized.append(NormalizedAccount(email=email, role=role))

    if any(role_counts[r] != 1 for r in role_counts):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid request body.",
        )

    return normalized


def _ensure_security_gate(request: Request) -> None:
    flag = os.environ.get(_FEATURE_FLAG_ENV, "").strip().lower()
    if flag != "true":
        raise _NotFoundGate()

    expected_secret = os.environ.get(_SECRET_ENV, "")
    if not expected_secret:
        raise _NotFoundGate()

    provided_secret = request.headers.get(_SECRET_HEADER)
    if not provided_secret:
        raise _NotFoundGate()

    if not secrets.compare_digest(provided_secret, expected_secret):
        raise _NotFoundGate()


async def _find_tenant_by_slug(db: AsyncSession, normalized_slug: str) -> Tenant | None:
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == normalized_slug))
    return tenant_result.scalar_one_or_none()


async def _find_users_by_email_case_insensitive(db: AsyncSession, normalized_email: str) -> list[User]:
    user_result = await db.execute(
        select(User)
        .where(User.email.is_not(None))
        .where(func.lower(User.email) == normalized_email)
    )
    return list(user_result.scalars().all())


async def _find_tenant_by_slug_for_update(db: AsyncSession, normalized_slug: str) -> Tenant | None:
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == normalized_slug).with_for_update()
    )
    return tenant_result.scalar_one_or_none()


async def _find_users_by_email_case_insensitive_for_update(db: AsyncSession, normalized_email: str) -> list[User]:
    user_result = await db.execute(
        select(User)
        .where(User.email.is_not(None))
        .where(func.lower(User.email) == normalized_email)
        .with_for_update()
    )
    return list(user_result.scalars().all())


@router.post("/status", include_in_schema=False)
async def demo_bootstrap_status(request: Request):
    _ensure_security_gate(request)

    body = await _parse_model(request, StatusRequest)
    normalized_accounts = _validate_roles_and_emails(body.accounts)
    normalized_slug = _normalize_slug(body.tenant_slug)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        tenant = await _find_tenant_by_slug(db, normalized_slug)

        account_rows: list[dict[str, object]] = []
        for account in normalized_accounts:
            matches = await _find_users_by_email_case_insensitive(db, account.email)
            ambiguous = len(matches) > 1
            match = matches[0] if len(matches) == 1 else None

            belongs_to_target = bool(match and tenant and match.tenant_id == tenant.id)
            role_matches = bool(match and match.role == account.role)
            active = bool(match and match.is_active)
            has_password_hash = bool(match and match.password_hash)

            account_rows.append(
                {
                    "email": account.email,
                    "requested_role": account.role,
                    "exists": bool(match),
                    "belongs_to_target_tenant": belongs_to_target,
                    "role_matches": role_matches,
                    "active": active,
                    "has_password_hash": has_password_hash,
                    "ambiguous": ambiguous,
                }
            )

    return {
        "tenant": {
            "slug": normalized_slug,
            "exists": tenant is not None,
            "active": bool(tenant and tenant.is_active),
        },
        "accounts": account_rows,
    }


@router.post("/apply", include_in_schema=False)
async def demo_bootstrap_apply(request: Request):
    _ensure_security_gate(request)

    body = await _parse_model(request, ApplyRequest)
    normalized_accounts = _validate_roles_and_emails(body.accounts)
    normalized_slug = _normalize_slug(body.tenant.slug)
    tenant_name = body.tenant.name.strip()

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        # All DB validation and writes must occur inside one transaction to avoid
        # SQLAlchemy's autobegin creating an implicit transaction before we start.
        created_users = 0
        updated_users = 0
        tenant_created = False

        try:
            async with db.begin():
                # Transaction begins here. All DB selects and writes occur
                # inside this `async with db.begin()` block.
                # Tenant lookup (locked to avoid races when creating).
                # Use the FOR UPDATE variant so concurrent applies serialize.
                tenant = await _find_tenant_by_slug_for_update(db, normalized_slug)

                if tenant and not tenant.is_active:
                    raise _Conflict()
                if not tenant and not body.tenant.create_if_missing:
                    raise _Conflict()
                if not tenant and body.tenant.create_if_missing and not tenant_name:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Invalid request body.",
                    )

                # Find existing users (case-insensitive) using helpers so tests
                # can assert the calls happen inside the transaction.
                found_by_email: dict[str, User | None] = {}
                for account in normalized_accounts:
                    matches = await _find_users_by_email_case_insensitive_for_update(db, account.email)
                    if len(matches) > 1:
                        raise _Conflict()
                    if not matches:
                        found_by_email[account.email] = None
                        continue

                    existing = matches[0]
                    if tenant is None:
                        raise _Conflict()
                    if existing.tenant_id != tenant.id:
                        raise _Conflict()
                    if existing.role != account.role:
                        raise _Conflict()
                    if not existing.is_active:
                        raise _Conflict()

                    found_by_email[account.email] = existing

                for account in normalized_accounts:
                    existing = found_by_email[account.email]
                    if existing is None and not account.display_name:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Invalid request body.",
                        )

                # All DB validation succeeded. Now compute password hashes
                # (done inside the transaction per requirement) and perform writes.
                password_hashes: dict[str, str] = {}
                for account in normalized_accounts:
                    password_hashes[account.email] = _pwd_context.hash(account.password or "")

                target_tenant = tenant
                if target_tenant is None:
                    target_tenant = Tenant(
                        name=tenant_name,
                        slug=normalized_slug,
                        settings={},
                        is_active=True,
                    )
                    db.add(target_tenant)
                    await db.flush()
                    tenant_created = True

                for account in normalized_accounts:
                    existing = found_by_email[account.email]
                    hashed = password_hashes[account.email]
                    if existing is None:
                        db.add(
                            User(
                                tenant_id=target_tenant.id,
                                name=account.display_name or "",
                                email=account.email,
                                role=account.role,
                                password_hash=hashed,
                                is_active=True,
                            )
                        )
                        created_users += 1
                    else:
                        existing.password_hash = hashed
                        updated_users += 1
        except _Conflict as exc:
            # Domain validation errors map to 409 with the conflict message.
            raise HTTPException(status_code=409, detail=str(exc))
        except HTTPException:
            # Re-raise HTTPExceptions (e.g., 422) unchanged.
            raise
        except IntegrityError:
            # Integrity errors indicate a DB constraint violation; surface
            # as 409 without revealing SQL details.
            logger.error("demo_bootstrap.apply_integrity_error")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Demo bootstrap conflict",
            )
        except SQLAlchemyError:
            # Unexpected DB errors should be a generic 500 with no details.
            logger.error("demo_bootstrap.apply_failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Demo bootstrap operation failed",
            )

    return {
        "status": "completed",
        "tenant_slug": normalized_slug,
        "tenant_created": tenant_created,
        "created_users": created_users,
        "updated_users": updated_users,
        "roles": ["teacher", "parent", "principal"],
    }
