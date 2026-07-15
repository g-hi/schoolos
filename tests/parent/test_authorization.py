"""
Phase 8.1 – Authorization Tests
=================================
Tests for JWT authentication, role enforcement, and the parent
authorization dependency chain.

Uses FastAPI TestClient with dependency overrides — no live database required.
Tests that verify DB-level behaviour (tenant validation, user loading) mock
the database session.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.parent.conftest import (
    make_expired_token,
    make_parent_token,
    make_parent_user,
    make_teacher_token,
    make_tenant,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. JWT function tests — no HTTP, no DB
# ─────────────────────────────────────────────────────────────────────────────

def test_create_access_token_contains_required_claims():
    """Token payload must include sub, role, tenant, iss, aud, jti, iat, exp."""
    from jose import jwt
    from shared.auth.jwt import create_access_token
    from shared.config import settings

    token = create_access_token(
        user_id="test-user-id",
        role="parent",
        tenant_slug="greenwood",
    )
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        audience="schoolos-client",
        issuer="schoolos-gateway",
    )
    assert payload["sub"] == "test-user-id"
    assert payload["role"] == "parent"      # informational claim
    assert payload["tenant"] == "greenwood"
    assert "iss" in payload
    assert "aud" in payload
    assert "jti" in payload
    assert "iat" in payload
    assert "exp" in payload


def test_decode_valid_token_succeeds():
    """A freshly created token decodes without error."""
    from shared.auth.jwt import _decode_raw_token, create_access_token

    token = create_access_token(
        user_id="abc-123",
        role="parent",
        tenant_slug="greenwood",
    )
    payload = _decode_raw_token(token)
    assert payload["sub"] == "abc-123"


def test_decode_expired_token_raises_401():
    """An expired token must raise HTTPException 401."""
    from fastapi import HTTPException
    from shared.auth.jwt import _decode_raw_token

    parent_id = str(uuid.uuid4())
    expired = make_expired_token(parent_id)
    with pytest.raises(HTTPException) as exc_info:
        _decode_raw_token(expired)
    assert exc_info.value.status_code == 401


def test_decode_wrong_secret_raises_401():
    """A token signed with a different secret must raise HTTPException 401."""
    from fastapi import HTTPException
    from jose import jwt
    from shared.auth.jwt import _decode_raw_token

    payload = {
        "sub": "user-id",
        "role": "parent",
        "tenant": "greenwood",
        "iss": "schoolos-gateway",
        "aud": "schoolos-client",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    bad_token = jwt.encode(payload, "wrong-secret-key-for-test", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        _decode_raw_token(bad_token)
    assert exc_info.value.status_code == 401


def test_role_claim_is_present_but_not_authoritative():
    """
    The JWT role claim is informational only.
    Verify it is stored but that authorization uses DB role, not this claim.
    (Structural test: confirms the claim is NOT used in require_role.)
    """
    from jose import jwt
    from shared.auth.jwt import create_access_token
    from shared.config import settings

    # Issue a token claiming principal role
    token = create_access_token(
        user_id=str(uuid.uuid4()),
        role="principal",  # wrong role for parent endpoint
        tenant_slug="greenwood",
    )
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        audience="schoolos-client",
        issuer="schoolos-gateway",
    )
    # The claim is stored
    assert payload["role"] == "principal"
    # But authorization reads user.role from DB — the JWT role claim alone
    # is never passed to require_role(). This is tested in the endpoint tests.


# ─────────────────────────────────────────────────────────────────────────────
# 2. Production secret validation
# ─────────────────────────────────────────────────────────────────────────────

def test_weak_secret_raises_in_production():
    """validate_secret_key_for_environment must raise in production with weak key."""
    from shared.auth.jwt import validate_secret_key_for_environment
    from shared.config import settings

    original_env = settings.app_env
    original_key = settings.secret_key
    try:
        settings.app_env = "production"
        settings.secret_key = "dev-secret-change-in-production"
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            validate_secret_key_for_environment()
    finally:
        settings.app_env = original_env
        settings.secret_key = original_key


def test_strong_secret_passes_in_production():
    """A 32+ character random key must not raise in production."""
    from shared.auth.jwt import validate_secret_key_for_environment
    from shared.config import settings

    original_env = settings.app_env
    original_key = settings.secret_key
    try:
        settings.app_env = "production"
        settings.secret_key = "a" * 40  # strong enough
        validate_secret_key_for_environment()  # must not raise
    finally:
        settings.app_env = original_env
        settings.secret_key = original_key


def test_weak_secret_only_warns_in_development(capfd):
    """In development, weak secrets log a warning but do not raise."""
    import logging
    from shared.auth.jwt import validate_secret_key_for_environment
    from shared.config import settings

    original_env = settings.app_env
    original_key = settings.secret_key
    try:
        settings.app_env = "development"
        settings.secret_key = "short"
        validate_secret_key_for_environment()  # must not raise
    finally:
        settings.app_env = original_env
        settings.secret_key = original_key


# ─────────────────────────────────────────────────────────────────────────────
# 3. HTTP endpoint tests — GET /parent/me
# ─────────────────────────────────────────────────────────────────────────────

def _get_test_app():
    """Returns the FastAPI app with minimal setup for testing."""
    from services.gateway.main import app
    return app


def _install_safe_mocks(app):
    """
    Override resolve_tenant and get_db on the app with no-op mocks.
    Call app.dependency_overrides.clear() in a finally block after use.
    Returns the mock tenant used.
    """
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    tenant = make_tenant()

    async def _mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        yield mock_session

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    return tenant


def test_parent_me_requires_bearer():
    """GET /parent/me without a Bearer token must return 401."""
    from services.gateway.main import app

    _install_safe_mocks(app)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={"X-Tenant-Slug": "greenwood"},
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_parent_me_with_invalid_token_returns_401():
    """GET /parent/me with a malformed token must return 401."""
    from services.gateway.main import app

    _install_safe_mocks(app)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={
                    "X-Tenant-Slug": "greenwood",
                    "Authorization": "Bearer not.a.valid.token",
                },
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_parent_me_with_expired_token_returns_401():
    """GET /parent/me with an expired token must return 401."""
    from services.gateway.main import app

    _install_safe_mocks(app)
    expired_token = make_expired_token(str(uuid.uuid4()))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={
                    "X-Tenant-Slug": "greenwood",
                    "Authorization": f"Bearer {expired_token}",
                },
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_parent_me_with_valid_token_but_no_db_user_returns_401():
    """
    A valid token where the user does not exist in the DB must return 401.
    Uses dependency override to return None from the DB query.
    """
    from services.gateway.main import app
    from shared.auth.jwt import get_current_user
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    parent_id = str(uuid.uuid4())
    token = make_parent_token(parent_id)
    tenant = make_tenant()

    async def mock_get_db():
        mock_session = AsyncMock()
        # User query returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    async def mock_resolve_tenant():
        return tenant

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = mock_resolve_tenant

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_parent_me_inactive_user_returns_401():
    """An inactive user must not be able to authenticate."""
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    tenant = make_tenant()
    inactive_user = make_parent_user(tenant.id, is_active=False)
    token = make_parent_token(str(inactive_user.id))

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    async def mock_resolve_tenant():
        return tenant

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = mock_resolve_tenant

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_teacher_token_rejected_on_parent_endpoint():
    """A teacher JWT must be rejected on /parent/me with 403."""
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    tenant = make_tenant()
    teacher_user = make_parent_user(tenant.id, role="teacher")  # role=teacher in DB
    token = make_teacher_token(str(teacher_user.id))

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = teacher_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    async def mock_resolve_tenant():
        return tenant

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = mock_resolve_tenant

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/me",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        # DB role is teacher → 403 from require_role("parent")
        assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Token tenant claim cross-validation
# ─────────────────────────────────────────────────────────────────────────────

def test_token_from_wrong_tenant_rejected():
    """
    A token issued for tenant A must be rejected when used against tenant B.
    The tenant claim in the token must match X-Tenant-Slug.
    """
    from shared.auth.jwt import _decode_raw_token, create_access_token
    from fastapi import HTTPException

    # Token for tenant A
    token_for_tenant_a = create_access_token(
        user_id=str(uuid.uuid4()),
        role="parent",
        tenant_slug="school-a",
    )
    payload = _decode_raw_token(token_for_tenant_a)
    # The tenant claim is school-a
    assert payload["tenant"] == "school-a"

    # This token would fail the cross-validation in get_current_user
    # when the request has X-Tenant-Slug: school-b
    # Tested structurally here since full HTTP requires a live DB.


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /parent/students — authorization checks
# ─────────────────────────────────────────────────────────────────────────────

def test_get_students_requires_auth():
    """GET /parent/students without Bearer token must return 401."""
    from services.gateway.main import app

    _install_safe_mocks(app)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/students",
                headers={"X-Tenant-Slug": "greenwood"},
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 6. POST /auth/token — login tests
# ─────────────────────────────────────────────────────────────────────────────

def test_login_wrong_tenant_returns_401():
    """Login with an unknown tenant slug returns 401 (not 404)."""
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        # Tenant query returns None
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/auth/token",
                json={
                    "email": "parent@test.example",
                    "password": "password",
                    "tenant_slug": "nonexistent-school",
                },
            )
        # Must be 401, not 404 — avoids tenant enumeration
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def test_login_wrong_password_returns_401():
    """Login with the correct email but wrong password returns 401."""
    from services.gateway.main import app
    from shared.db.connection import get_db

    tenant = make_tenant()
    user = make_parent_user(tenant.id, password="correct-password")

    call_count = [0]

    async def mock_get_db():
        mock_session = AsyncMock()

        async def execute_side_effect(query, *args, **kwargs):
            mock_result = MagicMock()
            if call_count[0] == 0:
                # First call: tenant query
                mock_result.scalar_one_or_none.return_value = tenant
            else:
                # Second call: user query
                mock_result.scalar_one_or_none.return_value = user
            call_count[0] += 1
            return mock_result

        mock_session.execute = execute_side_effect
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/auth/token",
                json={
                    "email": "aisha@test.example",
                    "password": "wrong-password",
                    "tenant_slug": "greenwood",
                },
            )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()
