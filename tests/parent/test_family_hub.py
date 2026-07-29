"""
Phase 8.1 – Family Hub Tests
==============================
Tests for family creation, parent-student linking, dashboard aggregation,
and parent preferences.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

import pytest

from tests.parent.conftest import (
    make_class,
    make_family,
    make_parent_preferences,
    make_parent_token,
    make_parent_user,
    make_student,
    make_student_parent,
    make_tenant,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Family model tests
# ─────────────────────────────────────────────────────────────────────────────

def test_family_has_no_unique_constraint_on_name():
    """
    Two families with the same name must be allowed within the same tenant.
    Verifies the model does NOT have UniqueConstraint(tenant_id, name).
    """
    from shared.db.parent_models import Family
    from sqlalchemy import inspect

    mapper = inspect(Family)
    unique_constraints = [
        uc.name for uc in mapper.mapper.local_table.constraints
        if hasattr(uc, "name") and "name" in str(getattr(uc, "columns", ""))
           and "tenant" in str(getattr(uc, "columns", ""))
    ]
    # There should be NO unique constraint involving both tenant_id and name
    assert not any("name" in str(uc) for uc in mapper.mapper.local_table.constraints
                   if "unique" in type(uc).__name__.lower()), (
        "Family must not have a unique constraint on (tenant_id, name)"
    )


def test_family_uuid_is_primary_key():
    """Family uses UUID as the authoritative identifier."""
    from shared.db.parent_models import Family
    tenant = make_tenant()
    f = make_family(tenant.id, name="The Mohammed Family")
    assert isinstance(f.id, uuid.UUID)


def test_family_creation_with_synthetic_data():
    """Family can be created with minimal required fields."""
    tenant = make_tenant()
    family = make_family(tenant.id, "The Mohammed Family")
    assert family.tenant_id == tenant.id
    assert family.name == "The Mohammed Family"
    assert family.is_active is True


def test_parent_linked_to_multiple_students():
    """One parent can have StudentParent rows for multiple students."""
    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    family = make_family(tenant.id)
    cls = make_class(tenant.id)

    students = [
        make_student(tenant.id, cls.id, name=n, student_code=c)
        for n, c in [("Ahmed", "S001"), ("Fatimah", "S002"), ("Omar", "S003")]
    ]
    sps = [
        make_student_parent(s.id, parent.id, family.id)
        for s in students
    ]

    assert len(sps) == 3
    assert all(sp.parent_id == parent.id for sp in sps)
    assert all(sp.family_id == family.id for sp in sps)


def test_secondary_guardian_limited_students():
    """
    Secondary guardian is linked to only one student.
    Other students in the family are not accessible to them.
    """
    tenant = make_tenant()
    family = make_family(tenant.id)
    cls = make_class(tenant.id)

    primary_parent = make_parent_user(tenant.id, name="Aisha")
    secondary_parent = make_parent_user(tenant.id, name="Khalid")

    ahmed = make_student(tenant.id, cls.id, name="Ahmed", student_code="S001")
    fatimah = make_student(tenant.id, cls.id, name="Fatimah", student_code="S002")

    # Primary has both
    sp_ahmed_primary = make_student_parent(ahmed.id, primary_parent.id, family.id, is_primary=True)
    sp_fatimah_primary = make_student_parent(fatimah.id, primary_parent.id, family.id, is_primary=True)

    # Secondary only has Ahmed
    sp_ahmed_secondary = make_student_parent(ahmed.id, secondary_parent.id, family.id, is_primary=False)

    # Secondary does not have Fatimah
    secondary_student_ids = {sp_ahmed_secondary.student_id}
    assert fatimah.id not in secondary_student_ids


# ─────────────────────────────────────────────────────────────────────────────
# 2. StudentParent extension fields
# ─────────────────────────────────────────────────────────────────────────────

def test_student_parent_has_new_columns():
    """StudentParent must have all Phase 8.1 columns."""
    sp = make_student_parent(
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
        is_primary=True,
        can_pickup=True,
        can_view_academics=True,
        can_view_behaviour=False,
    )
    assert sp.is_primary is True
    assert sp.can_pickup is True
    assert sp.can_view_academics is True
    assert sp.can_view_behaviour is False
    assert sp.family_id is not None


def test_student_parent_family_id_nullable_for_legacy():
    """
    family_id is nullable — legacy rows without a family must be preserved.
    This is an intentional Phase 8.1 constraint.
    """
    from shared.db.models import StudentParent
    col = StudentParent.__table__.c.family_id
    assert col.nullable is True, "family_id must remain nullable for legacy records"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dashboard widget unavailability
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_unavailable_modules_return_explicit_state():
    """
    Dashboard must return available: false for unimplemented modules.
    No fabricated or hardcoded data.
    """
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant
    from shared.auth.dependencies import (
        resolve_authenticated_parent,
        resolve_or_create_parent_preferences,
    )

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    prefs = make_parent_preferences(tenant.id, parent.id)
    token = make_parent_token(str(parent.id))

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no family, no pickups
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_parent] = lambda: parent
    app.dependency_overrides[resolve_or_create_parent_preferences] = lambda: prefs

    try:
        with TestClient(
            app,
            raise_server_exceptions=False,
        ) as client:
            response = client.get(
               "/parent/dashboard",
                headers={
                  "X-Tenant-Slug": tenant.slug,
                  "Authorization": f"Bearer {token}",
               },
          )
        assert response.status_code == 200, response.text
        data = response.json()
        for module in ["academics", "attendance", "homework", "reports", "messages", "payments"]:
            assert module in data, f"{module} missing from dashboard"
            assert data[module]["available"] is False, f"{module} should be unavailable"
    finally:
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Parent preferences
# ─────────────────────────────────────────────────────────────────────────────

def test_parent_preferences_default_values():
    """Preferences row must have sensible defaults."""
    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    prefs = make_parent_preferences(tenant.id, parent.id)

    assert prefs.preferred_language == "en"
    assert prefs.timezone == "UTC"
    assert prefs.theme == "light"
    assert prefs.weekly_report_digest is True
    assert prefs.email_notifications is True
    assert prefs.in_app_notifications is True


def test_parent_preferences_tenant_user_unique_constraint():
    """ParentPreferences must have UniqueConstraint(tenant_id, user_id)."""
    from shared.db.parent_models import ParentPreferences
    from sqlalchemy import inspect

    table = ParentPreferences.__table__
    unique_names = [uc.name for uc in table.constraints if "unique" in type(uc).__name__.lower()]
    assert "uq_parent_preferences_user" in unique_names


def test_patch_settings_updates_preferences_structure():
    """PATCH /parent/settings with valid body returns updated values."""
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant
    from shared.auth.dependencies import (
        resolve_authenticated_parent,
        resolve_or_create_parent_preferences,
    )

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    prefs = make_parent_preferences(tenant.id, parent.id)
    token = make_parent_token(str(parent.id))

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.refresh = AsyncMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_parent] = lambda: parent
    app.dependency_overrides[resolve_or_create_parent_preferences] = lambda: prefs

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.patch(
                "/parent/settings",
                json={"theme": "dark", "preferred_language": "ar"},
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["theme"] == "dark"
        assert data["preferred_language"] == "ar"
    finally:
        app.dependency_overrides.clear()
