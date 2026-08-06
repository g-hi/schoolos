from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from services.gateway.main import app
from services.gateway.routers import timetable_setup_centre
from shared.auth.dependencies import require_role
from shared.db.models import Tenant, User


REQUIRED_ROUTE_PATHS = {
    "/leadership/timetable-setup/centre/summary",
    "/leadership/timetable-setup/centre/steps",
    "/leadership/timetable-setup/centre/steps/{step_key}",
    "/leadership/timetable-setup/centre/issues",
    "/leadership/timetable-setup/centre/approvals",
    "/leadership/timetable-setup/centre/activity",
    "/leadership/timetable-setup/centre/recommendations",
    "/leadership/timetable-setup/centre/revalidate",
}


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Route Contract User",
        email=f"{uuid.uuid4()}@example.com",
        role=role,
        password_hash="hashed",
        is_active=is_active,
    )


def _tenant(*, tenant_id: uuid.UUID | None = None) -> Tenant:
    tid = tenant_id or uuid.uuid4()
    return Tenant(id=tid, name="Route Contract Tenant", slug=f"tenant-{tid.hex[:8]}", settings={}, is_active=True)


def test_route_inventory_and_no_destructive_delete_routes() -> None:
    paths = app.openapi()["paths"]
    assert REQUIRED_ROUTE_PATHS.issubset(paths.keys())
    for path, methods in paths.items():
        if path.startswith("/leadership/timetable-setup/centre"):
            assert "delete" not in methods


def test_leadership_role_contract() -> None:
    tenant_id = uuid.uuid4()
    dep = require_role("principal", "school_admin")

    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="principal")))
    asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role="school_admin")))

    for role in ("teacher", "parent", "student"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(dep(current_user=_user(tenant_id=tenant_id, role=role)))
        assert exc.value.status_code == 403


def test_inactive_and_cross_tenant_access_rejected() -> None:
    tenant_id = uuid.uuid4()
    tenant = _tenant(tenant_id=tenant_id)
    inactive = _user(tenant_id=tenant_id, role="principal", is_active=False)
    wrong_tenant = _user(tenant_id=uuid.uuid4(), role="principal", is_active=True)

    with pytest.raises(HTTPException) as inactive_exc:
        timetable_setup_centre._ensure_actor_tenant(inactive, tenant)
    assert inactive_exc.value.status_code == 403

    with pytest.raises(HTTPException) as tenant_exc:
        timetable_setup_centre._ensure_actor_tenant(wrong_tenant, tenant)
    assert tenant_exc.value.status_code == 401


def test_router_dependencies_include_tenant_and_leadership() -> None:
    for route in timetable_setup_centre.router.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = {dep.call for dep in route.dependant.dependencies}
        assert timetable_setup_centre.resolve_tenant in dependencies
        assert timetable_setup_centre.resolve_authenticated_leadership in dependencies
