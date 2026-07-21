"""One-time demo password reset utility.

This script is intentionally disabled by default and performs no database
activity unless SCHOOLOS_RESET_DEMO_PASSWORDS=true.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.auth.passwords import hash_password
from shared.config import settings
from shared.db.models import Tenant, User

_RESET_FLAG = "SCHOOLOS_RESET_DEMO_PASSWORDS"
_TRUE_VALUE = "true"


class ResetError(Exception):
    """Raised when reset preconditions fail."""


@dataclass(frozen=True)
class AccountResetRequest:
    email: str
    role: str
    password: str


@dataclass(frozen=True)
class ResetConfig:
    tenant_slug: str
    accounts: tuple[AccountResetRequest, AccountResetRequest, AccountResetRequest]


def _is_reset_enabled() -> bool:
    return os.getenv(_RESET_FLAG, "").strip().lower() == _TRUE_VALUE


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ResetError(f"Missing required environment variable: {name}")
    return value.strip()


def _load_config() -> ResetConfig:
    return ResetConfig(
        tenant_slug=_required_env("SCHOOLOS_DEMO_TENANT_SLUG"),
        accounts=(
            AccountResetRequest(
                email=_required_env("SCHOOLOS_DEMO_PARENT_EMAIL"),
                role="parent",
                password=_required_env("SCHOOLOS_DEMO_PARENT_PASSWORD"),
            ),
            AccountResetRequest(
                email=_required_env("SCHOOLOS_DEMO_TEACHER_EMAIL"),
                role="teacher",
                password=_required_env("SCHOOLOS_DEMO_TEACHER_PASSWORD"),
            ),
            AccountResetRequest(
                email=_required_env("SCHOOLOS_DEMO_PRINCIPAL_EMAIL"),
                role="principal",
                password=_required_env("SCHOOLOS_DEMO_PRINCIPAL_PASSWORD"),
            ),
        ),
    )


async def _reset_passwords(session: AsyncSession, config: ResetConfig) -> list[tuple[str, str, str]]:
    safe_output: list[tuple[str, str, str]] = []

    async with session.begin():
        tenant_rows = (
            (
                await session.execute(
                    select(Tenant).where(
                        Tenant.slug == config.tenant_slug,
                        Tenant.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(tenant_rows) != 1:
            raise ResetError("Tenant lookup failed: expected exactly one active tenant")

        tenant = tenant_rows[0]

        matched_users: list[tuple[AccountResetRequest, User]] = []
        for account in config.accounts:
            user_rows = (
                (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant.id,
                            User.email == account.email,
                            User.role == account.role,
                            User.is_active.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(user_rows) != 1:
                raise ResetError(
                    "User lookup failed: expected exactly one active user "
                    f"for role={account.role}"
                )
            matched_users.append((account, user_rows[0]))

        for account, user in matched_users:
            user.password_hash = hash_password(account.password)
            safe_output.append((tenant.slug, account.email, account.role))

    return safe_output


async def _run_enabled_reset(config: ResetConfig) -> list[tuple[str, str, str]]:
    engine = create_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await _reset_passwords(session, config)
    finally:
        await engine.dispose()


def main() -> int:
    if not _is_reset_enabled():
        return 0

    try:
        config = _load_config()
        rows = asyncio.run(_run_enabled_reset(config))
    except ResetError as exc:
        print(f"RESET_FAILED: {exc}")
        return 1
    except Exception:
        print("RESET_FAILED: unexpected error")
        return 1

    for tenant_slug, email, role in rows:
        print(f"tenant_slug={tenant_slug} email={email} role={role}")
    print("RESET_COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
