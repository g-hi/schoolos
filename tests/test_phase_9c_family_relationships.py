from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers.families import (
    RelationshipCreateRequest,
    RelationshipUpdateRequest,
    create_relationship,
    update_relationship,
)
from shared.auth.dependencies import validate_parent_student_access
from shared.auth.jwt import get_current_user
from shared.auth.jwt import create_access_token
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", settings={})


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        name=f"{role.title()} User",
        email=f"{role}@example.test",
    )


def _auth_headers(user: SimpleNamespace, tenant_slug: str, *, jwt_role: str | None = None) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=jwt_role or user.role, tenant_slug=tenant_slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": tenant_slug}


def _auth_db(user: SimpleNamespace) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(scalar=user))
    return session


def test_leadership_family_summary_requires_leadership_role() -> None:
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _auth_db(teacher)

    async def _get_db():
        return db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/leadership/families/summary", headers=_auth_headers(teacher, tenant.slug, jwt_role="principal"))
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_relationship_rejects_inactive_parent() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    parent = _user(tenant_id=tenant.id, role="parent", is_active=False)
    student = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, name="Student")

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[parent, student, None])

    with patch("services.gateway.routers.families.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await create_relationship(
                body=RelationshipCreateRequest(
                    parent_id=parent.id,
                    student_id=student.id,
                    relationship_type="guardian",
                    is_primary=True,
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_relationship_rejects_duplicate_active_link() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    parent = _user(tenant_id=tenant.id, role="parent", is_active=True)
    student = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, name="Student")

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[parent, student, student.id])

    with patch("services.gateway.routers.families.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await create_relationship(
                body=RelationshipCreateRequest(
                    parent_id=parent.id,
                    student_id=student.id,
                    relationship_type="guardian",
                    is_primary=False,
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_relationship_can_deactivate_without_delete() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="school_admin")
    student_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    rel = SimpleNamespace(student_id=student_id, parent_id=parent_id, relation_type="guardian", is_primary=True, is_active=True)

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=rel)
    db.commit = AsyncMock()

    with patch("services.gateway.routers.families.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.families.log_action",
        new=AsyncMock(),
    ):
        response = await update_relationship(
            relationship_id=f"{student_id}:{parent_id}",
            body=RelationshipUpdateRequest(is_active=False),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert response["is_active"] is False
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_parent_access_denied_when_relationship_is_inactive() -> None:
    tenant = _tenant()
    parent = _user(tenant_id=tenant.id, role="parent")
    student_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result(scalar=None))

    with pytest.raises(HTTPException) as exc_info:
        await validate_parent_student_access(student_id=student_id, parent=parent, tenant=tenant, db=db)

    assert exc_info.value.status_code == 404
