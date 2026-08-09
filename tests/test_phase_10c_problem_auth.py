from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from services.gateway.routers import timetable_generation
from shared.auth.dependencies import require_role
from shared.db.models import Tenant, User


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Problem Auth User",
        email=f"{uuid.uuid4()}@example.com",
        role=role,
        password_hash="hashed",
        is_active=is_active,
    )


def _tenant(*, tenant_id: uuid.UUID | None = None) -> Tenant:
    tid = tenant_id or uuid.uuid4()
    return Tenant(id=tid, name="Problem Auth Tenant", slug=f"tenant-{tid.hex[:8]}", settings={}, is_active=True)


def test_problem_routes_require_leadership_roles() -> None:
    tenant_id = uuid.uuid4()
    dep = require_role("principal", "school_admin")

    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="principal")))
    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="school_admin")))

    for role in ("teacher", "parent", "student"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role=role)))
        assert exc.value.status_code == 403


def test_problem_routes_reject_inactive_or_cross_tenant_actor() -> None:
    tenant = _tenant()

    with pytest.raises(HTTPException) as inactive_exc:
        timetable_generation._ensure_actor_tenant(_user(tenant_id=tenant.id, role="principal", is_active=False), tenant)
    assert inactive_exc.value.status_code == 403

    with pytest.raises(HTTPException) as cross_exc:
        timetable_generation._ensure_actor_tenant(_user(tenant_id=uuid.uuid4(), role="principal", is_active=True), tenant)
    assert cross_exc.value.status_code == 401


def test_problem_routes_include_tenant_and_leadership_dependencies() -> None:
    for route in timetable_generation.router.routes:
        if not isinstance(route, APIRoute):
            continue
        if "/problem/" not in route.path:
            continue
        dependencies = {dep.call for dep in route.dependant.dependencies}
        assert timetable_generation.resolve_tenant in dependencies
        assert timetable_generation.resolve_authenticated_leadership in dependencies
