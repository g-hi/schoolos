from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_policies
from shared.auth.dependencies import require_role
from shared.db.models import Tenant, User


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Policy Auth User",
        email=f"{uuid.uuid4()}@example.com",
        role=role,
        password_hash="hashed",
        is_active=is_active,
    )


def _tenant(*, tenant_id: uuid.UUID | None = None) -> Tenant:
    tid = tenant_id or uuid.uuid4()
    return Tenant(id=tid, name="Policy Tenant", slug=f"tenant-{tid.hex[:8]}", settings={}, is_active=True)


def test_leadership_roles_allowed() -> None:
    dep = require_role("principal", "school_admin")
    tenant_id = uuid.uuid4()

    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="principal")))
    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="school_admin")))


def test_non_leadership_roles_rejected() -> None:
    dep = require_role("principal", "school_admin")
    tenant_id = uuid.uuid4()

    for role in ("teacher", "parent", "student"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role=role)))
        assert exc.value.status_code == 403


def test_inactive_and_cross_tenant_rejected() -> None:
    tenant = _tenant()
    inactive_actor = _user(tenant_id=tenant.id, role="principal", is_active=False)
    cross_tenant_actor = _user(tenant_id=uuid.uuid4(), role="principal", is_active=True)

    with pytest.raises(HTTPException) as inactive_exc:
        timetable_policies._ensure_actor_tenant(inactive_actor, tenant)
    assert inactive_exc.value.status_code == 403

    with pytest.raises(HTTPException) as cross_tenant_exc:
        timetable_policies._ensure_actor_tenant(cross_tenant_actor, tenant)
    assert cross_tenant_exc.value.status_code == 401
