from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers.auth import AcceptInvitationRequest, accept_invitation
from services.gateway.routers.people import _issue_invitation, update_user_status
from shared.auth.jwt import create_access_token
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        name=f"{role.title()} User",
        email=f"{role}@example.test",
        password_hash=None,
    )


def _auth_headers(user: SimpleNamespace, tenant_slug: str, *, jwt_role: str | None = None) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=jwt_role or user.role, tenant_slug=tenant_slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": tenant_slug}


def _auth_db(user: SimpleNamespace) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(scalar=user))
    return session


def test_leadership_people_summary_requires_leadership_role() -> None:
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _auth_db(teacher)

    async def _get_db():
        return db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/leadership/people/summary", headers=_auth_headers(teacher, tenant.slug, jwt_role="principal"))
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_issue_invitation_rejects_non_invitable_role() -> None:
    db = AsyncMock()
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    principal = _user(tenant_id=tenant_id, role="principal")

    with pytest.raises(HTTPException) as exc_info:
        await _issue_invitation(db=db, tenant_id=tenant_id, user=principal, actor_id=actor_id)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_issue_invitation_conflicts_when_pending_exists() -> None:
    db = AsyncMock()
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    parent = _user(tenant_id=tenant_id, role="parent")
    pending = SimpleNamespace(expires_at=datetime.now(timezone.utc) + timedelta(hours=2), revoked_at=None)
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: pending)))

    with pytest.raises(HTTPException) as exc_info:
        await _issue_invitation(db=db, tenant_id=tenant_id, user=parent, actor_id=actor_id)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_invitation_rejects_weak_password() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await accept_invitation(body=AcceptInvitationRequest(token="abc", new_password="short"), db=AsyncMock())
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_accept_invitation_activates_account_and_revokes_other_pending() -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    token = "one-time-token"
    invitation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        invited_email="parent@example.test",
        role="parent",
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        accepted_at=None,
        revoked_at=None,
    )
    other_pending = SimpleNamespace(revoked_at=None)
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, email="parent@example.test", role="parent", is_active=False, password_hash=None)

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[invitation, tenant, user])
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [other_pending])))
    db.commit = AsyncMock()

    with patch("services.gateway.routers.auth.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.auth.log_action",
        new=AsyncMock(),
    ):
        result = await accept_invitation(
            body=AcceptInvitationRequest(token=token, new_password="StrongPass1"),
            db=db,
        )

    assert result["status"] == "accepted"
    assert user.is_active is True
    assert isinstance(user.password_hash, str)
    assert invitation.accepted_at is not None
    assert other_pending.revoked_at is not None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_deactivate_last_active_principal_is_blocked() -> None:
    tenant = _tenant()
    principal = _user(tenant_id=tenant.id, role="principal", is_active=True)
    actor = _user(tenant_id=tenant.id, role="school_admin")

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[principal, 1])

    with patch("services.gateway.routers.people.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await update_user_status(
                user_id=principal.id,
                body=SimpleNamespace(is_active=False, reason="test"),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 409


def test_phase_9c_is_current_migration_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "1a9d5e7c3b21"
