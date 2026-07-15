"""
SchoolOS – Parent Authorization Dependencies
=============================================
FastAPI dependency chain for the Parent Experience Platform.

All dependencies use the authenticated user loaded from PostgreSQL via
shared.auth.jwt.get_current_user — never trust client-supplied headers
for identity or role.

Dependency chain
----------------
get_current_user          → User (validated JWT + DB load + active check)
    ↓
require_role("parent")    → User (role check using user.role from DB)
    ↓
resolve_authenticated_parent → User (alias that enforces parent role)
    ↓
resolve_family            → Family (derived from StudentParent.family_id)
    ↓
validate_parent_student_access(student_id) → StudentParent
    ↓
check_academic_access / check_behaviour_access → StudentParent (permission flag)

Family membership model (Version 1)
------------------------------------
Family membership is inferred from StudentParent.family_id.
A parent belongs to a family if they have at least one StudentParent row
with a matching family_id.

This is an intentional Version 1 simplification.  All StudentParent rows
for a given parent must point to the same family within the same tenant;
the application layer enforces this via ensure_consistent_family().

Tenant isolation
----------------
Every query is scoped by both tenant_id and the resolved family.
No cross-family or cross-tenant data is ever returned.
"""

from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


# ─────────────────────────────────────────────────────────────────────────────
# require_role — generic role enforcement
# ─────────────────────────────────────────────────────────────────────────────

def require_role(*allowed_roles: str) -> Callable:
    """
    Returns a FastAPI dependency that enforces one of the allowed roles.

    Uses user.role from the PostgreSQL User record — NOT the JWT role claim.
    Raises 403 if the authenticated user's DB role is not in allowed_roles.
    """
    async def _dependency(
        current_user=Depends(get_current_user),
    ):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this resource.",
            )
        return current_user

    return _dependency


# ─────────────────────────────────────────────────────────────────────────────
# resolve_authenticated_parent
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_authenticated_parent(
    current_user=Depends(require_role("parent")),
):
    """
    FastAPI dependency.
    Confirms the authenticated user has role='parent' (from DB).
    Returns the User ORM object.
    """
    return current_user


# ─────────────────────────────────────────────────────────────────────────────
# resolve_family
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_family(
    parent=Depends(resolve_authenticated_parent),
    tenant=Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Resolves the Family for the authenticated parent.

    Derives family membership from StudentParent.family_id (Version 1 model).
    The family must belong to the same tenant as the authenticated user.

    Raises 404 if no active family is found for this parent.
    The 404 is intentional for IDOR-sensitive resources — do not change to 403.
    """
    from shared.db.models import StudentParent
    from shared.db.parent_models import Family

    # Validate tenant consistency
    if parent.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find the family via any StudentParent row for this parent
    result = await db.execute(
        select(Family)
        .join(StudentParent, StudentParent.family_id == Family.id)
        .where(
            StudentParent.parent_id == parent.id,
            Family.tenant_id == tenant.id,
            Family.is_active.is_(True),
        )
        .limit(1)
    )
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active family found for this account.",
        )
    return family


# ─────────────────────────────────────────────────────────────────────────────
# validate_parent_student_access
# ─────────────────────────────────────────────────────────────────────────────

async def validate_parent_student_access(
    student_id: uuid.UUID,
    parent=Depends(resolve_authenticated_parent),
    tenant=Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Validates that the authenticated parent is authorized to access the given
    student.

    Returns the StudentParent row (carries permission flags is_primary,
    can_pickup, can_view_academics, can_view_behaviour).

    Never trusts the student_id from the URL without this validation.

    Returns 404 for unauthorized students to avoid confirming that another
    family's student exists (IDOR protection).
    """
    from shared.db.models import StudentParent, Student

    result = await db.execute(
        select(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .where(
            StudentParent.student_id == student_id,
            StudentParent.parent_id == parent.id,
            Student.tenant_id == tenant.id,
        )
    )
    sp = result.scalar_one_or_none()
    if not sp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found.",
        )
    return sp


# ─────────────────────────────────────────────────────────────────────────────
# check_academic_access
# ─────────────────────────────────────────────────────────────────────────────

def check_academic_access(sp) -> bool:
    """Returns True if the guardian has academic visibility permission."""
    return bool(sp.can_view_academics)


def check_behaviour_access(sp) -> bool:
    """Returns True if the guardian has behaviour visibility permission."""
    return bool(sp.can_view_behaviour)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_or_create_parent_preferences
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_or_create_parent_preferences(
    parent=Depends(resolve_authenticated_parent),
    tenant=Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the ParentPreferences for the authenticated parent.
    Creates a default row if none exists.
    Validates that user.tenant_id == tenant.id before creation.
    """
    from shared.db.parent_models import ParentPreferences

    if parent.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    result = await db.execute(
        select(ParentPreferences).where(
            ParentPreferences.user_id == parent.id,
            ParentPreferences.tenant_id == tenant.id,
        )
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = ParentPreferences(
            tenant_id=tenant.id,
            user_id=parent.id,
        )
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs
