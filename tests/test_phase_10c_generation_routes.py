from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from services.gateway.main import app
from services.gateway.routers import timetable_generation
from shared.auth.dependencies import require_role
from shared.db.models import Tenant, User


REQUIRED_GENERATION_ROUTES = {
    "/leadership/timetable-generation/configurations": {"get", "post"},
    "/leadership/timetable-generation/configurations/{configuration_id}": {"get", "patch"},
    "/leadership/timetable-generation/configurations/{configuration_id}/validate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/submit": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/approve": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/cancel": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/supersede": {"post"},
    "/leadership/timetable-generation/preferences": {"get", "post"},
    "/leadership/timetable-generation/preferences/{preference_id}": {"get", "patch"},
    "/leadership/timetable-generation/preferences/{preference_id}/deactivate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/overrides": {"get", "post"},
    "/leadership/timetable-generation/overrides/{override_id}": {"patch"},
    "/leadership/timetable-generation/overrides/{override_id}/remove": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/locks": {"get", "post"},
    "/leadership/timetable-generation/locks/{lock_id}": {"patch"},
    "/leadership/timetable-generation/locks/{lock_id}/remove": {"post"},
    "/leadership/timetable-generation/parallel-blocks": {"get", "post"},
    "/leadership/timetable-generation/parallel-blocks/{block_id}": {"get", "patch"},
    "/leadership/timetable-generation/parallel-blocks/{block_id}/deactivate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/summary": {"get"},
    "/leadership/timetable-generation/configurations/{configuration_id}/candidates/preview": {"post"},
    "/leadership/timetable-generation/timetables": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}/versions": {"get"},
    "/leadership/timetable-generation/timetable-versions/{version_id}": {"get"},
    "/leadership/timetable-generation/configurations/{configuration_id}/versions/from-candidate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/repair/impact-preview": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/submit": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/approve": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/publish": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/cancel": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/diff/{other_version_id}": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}/effective-version": {"get"},
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


def test_phase_10c_route_inventory_and_no_generate_endpoint() -> None:
    paths = app.openapi()["paths"]
    for path, methods in REQUIRED_GENERATION_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))

    assert "/leadership/timetable-generation/generate" not in paths


def test_no_delete_routes_under_generation_scope() -> None:
    paths = app.openapi()["paths"]
    for path, methods in paths.items():
        if path.startswith("/leadership/timetable-generation"):
            assert "delete" not in methods


def test_leadership_role_contract_for_generation_scope() -> None:
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
        timetable_generation._ensure_actor_tenant(actor, tenant)
    assert exc.value.status_code == 403


def test_cross_tenant_access_rejected() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=uuid.uuid4(), role="principal", is_active=True)
    with pytest.raises(HTTPException) as exc:
        timetable_generation._ensure_actor_tenant(actor, tenant)
    assert exc.value.status_code == 401


def test_router_dependencies_include_tenant_and_leadership() -> None:
    for route in timetable_generation.router.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = {dep.call for dep in route.dependant.dependencies}
        assert timetable_generation.resolve_tenant in dependencies
        assert timetable_generation.resolve_authenticated_leadership in dependencies
