from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from services.gateway.main import app
from services.gateway.routers import timetable_setup
from shared.auth.dependencies import require_role
from shared.db.models import Tenant, User


REQUIRED_ROUTE_PATHS = {
    "/leadership/timetable-setup/calendar",
    "/leadership/timetable-setup/calendar/events",
    "/leadership/timetable-setup/calendar/events/{event_id}",
    "/leadership/timetable-setup/calendar/events/{event_id}/submit",
    "/leadership/timetable-setup/calendar/events/{event_id}/approve",
    "/leadership/timetable-setup/calendar/events/{event_id}/publish",
    "/leadership/timetable-setup/calendar/events/{event_id}/reschedule",
    "/leadership/timetable-setup/calendar/events/{event_id}/cancel",
    "/leadership/timetable-setup/calendar/events/{event_id}/restore",
    "/leadership/timetable-setup/calendar/events/{event_id}/archive",
    "/leadership/timetable-setup/calendar/events/{event_id}/versions",
    "/leadership/timetable-setup/calendar/events/{event_id}/impact",
    "/leadership/timetable-setup/calendar/pdf-intake/upload",
    "/leadership/timetable-setup/calendar/pdf-intake/imports",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/pages",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/extract",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/candidates",
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}",
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/approve",
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/reject",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/validate",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/commit",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/cancel",
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/diagnostics",
    "/leadership/timetable-setup/calendar/notification-plans",
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}",
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}/approve",
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}/cancel",
    "/leadership/timetable-setup/calendar/events/{event_id}/notification-plan",
    "/leadership/timetable-setup/school-week",
    "/leadership/timetable-setup/bell-schedules",
    "/leadership/timetable-setup/rooms",
    "/leadership/timetable-setup/teaching-requirements",
    "/leadership/timetable-setup/readiness",
    "/leadership/timetable-setup/readiness/checks",
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
        if path.startswith("/leadership/timetable-setup"):
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


def test_inactive_leadership_rejected() -> None:
    tenant_id = uuid.uuid4()
    tenant = _tenant(tenant_id=tenant_id)
    actor = _user(tenant_id=tenant_id, role="principal", is_active=False)
    with pytest.raises(HTTPException) as exc:
        timetable_setup._ensure_actor_tenant(actor, tenant)
    assert exc.value.status_code == 403


def test_cross_tenant_access_rejected() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=uuid.uuid4(), role="principal", is_active=True)
    with pytest.raises(HTTPException) as exc:
        timetable_setup._ensure_actor_tenant(actor, tenant)
    assert exc.value.status_code == 401


def test_router_dependencies_include_tenant_and_leadership() -> None:
    for route in timetable_setup.router.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = {dep.call for dep in route.dependant.dependencies}
        assert timetable_setup.resolve_tenant in dependencies
        assert timetable_setup.resolve_authenticated_leadership in dependencies
