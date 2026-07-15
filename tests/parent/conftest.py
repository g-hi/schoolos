"""
Phase 8.1 Test Fixtures
========================
Synthetic parent, family, and student data for tests.

All records are created in memory — no production database is used.
These fixtures are also documented as the safe method for creating
test parent accounts with hashed passwords in development environments.

Password provisioning
---------------------
Parent accounts in the SchoolOS database require bcrypt-hashed passwords.
No default or placeholder passwords are created for production.

For development / test only, use create_test_parent() below:

    parent = create_test_parent(
        tenant=my_tenant,
        name="Aisha Mohammed",
        email="aisha@test.example",
        password="TestP@ss1234!",   # TEST USE ONLY
    )
    db.add(parent)
    await db.commit()

For production accounts, create a controlled admin provisioning flow
(outside Phase 8.1 scope).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# In-memory object factory helpers
# These produce plain Namespace objects that behave like ORM rows.
# ─────────────────────────────────────────────────────────────────────────────

class _Obj:
    """Minimal ORM-like object for test fixtures."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def make_tenant(slug: str = "greenwood", name: str = "Greenwood International") -> _Obj:
    return _Obj(
        id=_uuid(),
        slug=slug,
        name=name,
        is_active=True,
        settings={},
        created_at=datetime.now(timezone.utc),
    )


def make_parent_user(
    tenant_id: uuid.UUID,
    *,
    name: str = "Aisha Mohammed",
    email: str = "aisha@test.example",
    password: str = "TestP@ss1234!",
    role: str = "parent",
    is_active: bool = True,
) -> _Obj:
    """
    Creates a synthetic parent User with a bcrypt-hashed password.
    FOR TEST AND DEVELOPMENT USE ONLY.
    Never create production accounts with this function.
    """
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        name=name,
        email=email,
        role=role,
        is_active=is_active,
        password_hash=_pwd_context.hash(password),
        phone=None,
        preferred_channel="whatsapp",
    )


def make_family(tenant_id: uuid.UUID, name: str = "The Mohammed Family") -> _Obj:
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        name=name,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_class(tenant_id: uuid.UUID, grade: str = "Grade 8", section: str = "A") -> _Obj:
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        grade=grade,
        section=section,
        academic_year="2025-2026",
        class_teacher_id=None,
    )


def make_student(
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    name: str = "Ahmed Mohammed",
    student_code: str = "STU-001",
) -> _Obj:
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        class_id=class_id,
        name=name,
        student_code=student_code,
        created_at=datetime.now(timezone.utc),
    )


def make_student_parent(
    student_id: uuid.UUID,
    parent_id: uuid.UUID,
    family_id: uuid.UUID,
    *,
    is_primary: bool = True,
    relation_type: str = "mother",
    can_pickup: bool = True,
    can_view_academics: bool = True,
    can_view_behaviour: bool = True,
) -> _Obj:
    return _Obj(
        student_id=student_id,
        parent_id=parent_id,
        family_id=family_id,
        is_primary=is_primary,
        relation_type=relation_type,
        can_pickup=can_pickup,
        can_view_academics=can_view_academics,
        can_view_behaviour=can_view_behaviour,
    )


def make_parent_preferences(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> _Obj:
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        user_id=user_id,
        preferred_language="en",
        timezone="UTC",
        theme="light",
        weekly_report_digest=True,
        email_notifications=True,
        in_app_notifications=True,
    )


def make_teacher_user(tenant_id: uuid.UUID, name: str = "Mr. Hassan") -> _Obj:
    return _Obj(
        id=_uuid(),
        tenant_id=tenant_id,
        name=name,
        email=f"{name.lower().replace(' ', '.')}@school.test",
        role="teacher",
        is_active=True,
        password_hash=None,
        phone=None,
        preferred_channel="email",
    )


# ─────────────────────────────────────────────────────────────────────────────
# JWT token helpers for tests
# ─────────────────────────────────────────────────────────────────────────────

def make_parent_token(user_id: str, tenant_slug: str = "greenwood") -> str:
    """Creates a valid test JWT for a parent user."""
    from shared.auth.jwt import create_access_token
    return create_access_token(
        user_id=user_id,
        role="parent",
        tenant_slug=tenant_slug,
    )


def make_teacher_token(user_id: str, tenant_slug: str = "greenwood") -> str:
    """Creates a valid test JWT for a teacher user."""
    from shared.auth.jwt import create_access_token
    return create_access_token(
        user_id=user_id,
        role="teacher",
        tenant_slug=tenant_slug,
    )


def make_expired_token(user_id: str, tenant_slug: str = "greenwood") -> str:
    """Creates an already-expired JWT for negative tests."""
    from jose import jwt
    from datetime import timedelta
    from shared.config import settings

    payload = {
        "sub": str(user_id),
        "role": "parent",
        "tenant": tenant_slug,
        "iss": "schoolos-gateway",
        "aud": "schoolos-client",
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")
