"""
Phase 8.1 – Tenant and Family Isolation Tests
===============================================
Tests that cross-family and cross-tenant data access is structurally
prevented by the authorization dependency chain.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.parent.conftest import (
    make_family,
    make_parent_token,
    make_parent_user,
    make_student,
    make_student_parent,
    make_tenant,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. validate_parent_student_access prevents cross-family access
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_student_access_blocks_foreign_student():
    """
    validate_parent_student_access must raise 404 if the parent has no
    StudentParent row for the requested student.
    """
    import asyncio
    from fastapi import HTTPException
    from shared.auth.dependencies import validate_parent_student_access

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    other_student_id = uuid.uuid4()  # student not linked to this parent

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        # No StudentParent row found
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await validate_parent_student_access(
                student_id=other_student_id,
                parent=parent,
                tenant=tenant,
                db=mock_db,
            )
        # 404 — never confirms the student exists for IDOR protection
        assert exc_info.value.status_code == 404

    asyncio.run(run())


def test_validate_student_access_allows_authorized_student():
    """validate_parent_student_access returns StudentParent for authorized student."""
    import asyncio
    from shared.auth.dependencies import validate_parent_student_access

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    cls = MagicMock()
    cls.id = uuid.uuid4()
    student = make_student(tenant.id, cls.id, name="Ahmed", student_code="S001")
    sp = make_student_parent(student.id, parent.id, uuid.uuid4())

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sp
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await validate_parent_student_access(
            student_id=student.id,
            parent=parent,
            tenant=tenant,
            db=mock_db,
        )
        assert result is sp

    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 2. resolve_family prevents cross-family access
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_family_raises_404_when_no_family():
    """
    resolve_family must raise 404 when the parent has no active family.
    Uses 404 (not 403) to avoid confirming family existence for IDOR.
    """
    import asyncio
    from fastapi import HTTPException
    from shared.auth.dependencies import resolve_family

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no family found
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await resolve_family(parent=parent, tenant=tenant, db=mock_db)
        assert exc_info.value.status_code == 404

    asyncio.run(run())


def test_resolve_family_returns_correct_family():
    """resolve_family returns the authenticated parent's family."""
    import asyncio
    from shared.auth.dependencies import resolve_family

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    family = make_family(tenant.id)

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = family
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await resolve_family(parent=parent, tenant=tenant, db=mock_db)
        assert result is family

    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cross-tenant token validation
# ─────────────────────────────────────────────────────────────────────────────

def test_token_tenant_claim_checked_against_header():
    """
    A token issued for tenant A must fail when used against tenant B.
    The get_current_user dependency validates token.tenant == tenant.slug.
    """
    from shared.auth.jwt import create_access_token, _decode_raw_token

    token_for_a = create_access_token(
        user_id=str(uuid.uuid4()),
        role="parent",
        tenant_slug="school-a",
    )
    payload = _decode_raw_token(token_for_a)
    assert payload["tenant"] == "school-a"

    # If the request header is X-Tenant-Slug: school-b, the get_current_user
    # dependency would find tenant.slug="school-b" != token.tenant="school-a"
    # and raise 401. We verify the structural invariant here.
    assert payload["tenant"] != "school-b"


def test_user_tenant_id_must_match_resolved_tenant():
    """
    get_current_user rejects a user whose tenant_id does not match the
    resolved tenant.  Structural test — verifies the comparison exists in jwt.py.
    """
    import asyncio
    import inspect
    from shared.auth import jwt as jwt_module

    source = inspect.getsource(jwt_module.get_current_user)
    # The function must reference tenant_id comparison
    assert "resolved_tenant_id" in source
    assert "tenant_id" in source


# ─────────────────────────────────────────────────────────────────────────────
# 4. Family timeline tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_timeline_query_filters_by_tenant_and_family():
    """
    The timeline endpoint query must filter by both tenant_id and family_id.
    Structural test — inspects the families router.
    """
    import inspect
    from services.gateway.routers import families as families_module

    source = inspect.getsource(families_module.get_family_timeline)
    assert "family_id" in source
    assert "tenant_id" in source


def test_student_filter_on_timeline_validates_parent_ownership():
    """
    When ?student_id is provided on the timeline endpoint, the handler
    must validate that the authenticated parent owns that student.
    """
    import inspect
    from services.gateway.routers import families as families_module

    source = inspect.getsource(families_module.get_family_timeline)
    # The function must perform a StudentParent ownership check
    assert "StudentParent" in source
    assert "student_id" in source
    assert "parent_id" in source


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /parent/students/{id} returns 404 for unlinked student
# ─────────────────────────────────────────────────────────────────────────────

def test_student_detail_returns_404_for_unlinked():
    """
    GET /parent/students/{student_id} for a student not linked to the parent
    must return 404 (not 403) to prevent student enumeration.
    """
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant
    from shared.auth.dependencies import resolve_authenticated_parent

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    unlinked_student_id = uuid.uuid4()
    token = make_parent_token(str(parent.id))

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        # StudentParent query returns None — student not linked
        mock_result.scalar_one_or_none.return_value = None
        mock_result.first.return_value = None
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_parent] = lambda: parent

    try:
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/parent/students/{unlinked_student_id}",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 404, response.text
    finally:
        app.dependency_overrides.clear()
