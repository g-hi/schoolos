"""
SchoolOS – Parent Router  (Phase 8.1)
=======================================
Authenticated parent self-service endpoints.

All endpoints require a valid JWT with role='parent'.
Authorization is performed using user.role from PostgreSQL — not the
JWT role claim.

Unimplemented modules return an explicit { "available": false, "reason": "..." }
response rather than fabricated or hardcoded data.

Assessment results are NOT linked by student_code because:
- AssessmentSubmission has no student_id foreign key.
- student_code is mutable and not guaranteed unique in this context.
Returns "available: false" until a direct FK relationship is established.

Pickup data is safely includable because PickupRequest.parent_id is a
confirmed FK to users.id.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import (
    resolve_authenticated_parent,
    resolve_family,
    resolve_or_create_parent_preferences,
    validate_parent_student_access,
    check_academic_access,
    check_behaviour_access,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    PickupRequest,
    Student,
    StudentParent,
    Teacher,
    TimetableEntry,
    Tenant,
    User,
)
from shared.db.parent_models import Family, ParentPreferences

router = APIRouter(prefix="/parent", tags=["Parent Experience"])

# Sentinel for modules not yet implemented
_UNAVAILABLE = {"available": False}


def _module_unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


# ─────────────────────────────────────────────────────────────────────────────
# GET /parent/me  —  authenticated parent profile
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me", summary="Authenticated parent profile")
async def get_parent_me(
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    prefs: ParentPreferences = Depends(resolve_or_create_parent_preferences),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    # Look up family
    from shared.db.parent_models import Family
    from shared.db.models import StudentParent
    family_result = await db.execute(
        select(Family)
        .join(StudentParent, StudentParent.family_id == Family.id)
        .where(
            StudentParent.parent_id == parent.id,
            Family.tenant_id == tenant.id,
            Family.is_active.is_(True),
        )
        .limit(1)
    )
    family = family_result.scalar_one_or_none()

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.profile_viewed",
        entity_type="User",
        entity_id=parent.id,
        details={},
    )
    await db.commit()

    return {
        "user_id": str(parent.id),
        "name": parent.name,
        "email": parent.email,
        "role": parent.role,
        "family_id": str(family.id) if family else None,
        "family_name": family.name if family else None,
        "preferred_language": prefs.preferred_language,
        "timezone": prefs.timezone,
        "theme": prefs.theme,
        "email_notifications": prefs.email_notifications,
        "in_app_notifications": prefs.in_app_notifications,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /parent/students  —  list authorized students
# ─────────────────────────────────────────────────────────────────────────────

async def _get_authorized_students(parent_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession):
    """
    Returns all students that the authenticated parent is authorized to view,
    scoped to the tenant.
    """
    result = await db.execute(
        select(StudentParent, Student, Class)
        .join(Student, Student.id == StudentParent.student_id)
        .join(Class, Class.id == Student.class_id)
        .where(
            StudentParent.parent_id == parent_id,
            Student.tenant_id == tenant_id,
        )
        .order_by(Student.name)
    )
    rows = result.all()

    students = []
    for sp, student, cls in rows:
        # Resolve homeroom teacher name
        homeroom_teacher_name = None
        if cls.class_teacher_id:
            t_result = await db.execute(
                select(Teacher, User)
                .join(User, User.id == Teacher.user_id)
                .where(Teacher.id == cls.class_teacher_id)
            )
            t_row = t_result.first()
            if t_row:
                homeroom_teacher_name = t_row[1].name

        students.append({
            "student_id": str(student.id),
            "name": student.name,
            "student_code": student.student_code,
            "grade": cls.grade,
            "section": cls.section,
            "class_name": f"{cls.grade}-{cls.section}",
            "homeroom_teacher": homeroom_teacher_name,
            "is_primary_guardian": bool(sp.is_primary),
            "can_pickup": bool(sp.can_pickup),
            "can_view_academics": bool(sp.can_view_academics),
            "can_view_behaviour": bool(sp.can_view_behaviour),
        })
    return students


@router.get("/students", summary="List students the parent is authorized to view")
async def get_parent_students(
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    students = await _get_authorized_students(parent.id, tenant.id, db)
    return {"students": students}


# ─────────────────────────────────────────────────────────────────────────────
# GET /parent/students/{student_id}  —  per-child overview
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/students/{student_id}", summary="Per-child overview")
async def get_student_overview(
    student_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    sp = await validate_parent_student_access(
        student_id=student_id, parent=parent, tenant=tenant, db=db
    )

    # Load student + class
    result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(Student.id == student_id, Student.tenant_id == tenant.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    student, cls = row

    # Homeroom teacher
    homeroom_teacher_name = None
    if cls.class_teacher_id:
        t_result = await db.execute(
            select(Teacher, User)
            .join(User, User.id == Teacher.user_id)
            .where(Teacher.id == cls.class_teacher_id)
        )
        t_row = t_result.first()
        if t_row:
            homeroom_teacher_name = t_row[1].name

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.student_overview_viewed",
        entity_type="Student",
        entity_id=student.id,
        actor_id=parent.id,
        details={"student_id": str(student.id)},
    )
    await db.commit()

    return {
        "student_id": str(student.id),
        "name": student.name,
        "student_code": student.student_code,
        "grade": cls.grade,
        "section": cls.section,
        "class_name": f"{cls.grade}-{cls.section}",
        "homeroom_teacher": homeroom_teacher_name,
        # Modules that are not yet implemented return explicit availability state.
        "academics": _module_unavailable("Academic module not yet configured.")
        if not check_academic_access(sp)
        else _module_unavailable("Academic module not yet configured."),
        "attendance": _module_unavailable("Attendance module not yet configured."),
        "homework": _module_unavailable("Homework module not yet configured."),
        "behaviour": _module_unavailable("Behaviour module not yet configured.")
        if not check_behaviour_access(sp)
        else _module_unavailable("Behaviour module not yet configured."),
        # Assessment results require a direct student_id FK in AssessmentSubmission.
        # Currently AssessmentSubmission only has student_name/student_code.
        # Linking via student_code is not safe (mutable, not guaranteed unique).
        "assessment_results": _module_unavailable(
            "Assessment results are not yet linked to the student profile."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /parent/dashboard  —  Family Hub aggregation
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", summary="Family Hub — aggregated parent dashboard")
async def get_parent_dashboard(
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    # Resolve family
    from shared.db.parent_models import Family, FamilyTimelineEvent
    from shared.db.models import StudentParent

    family_result = await db.execute(
        select(Family)
        .join(StudentParent, StudentParent.family_id == Family.id)
        .where(
            StudentParent.parent_id == parent.id,
            Family.tenant_id == tenant.id,
            Family.is_active.is_(True),
        )
        .limit(1)
    )
    family = family_result.scalar_one_or_none()

    # Authorized students
    students = await _get_authorized_students(parent.id, tenant.id, db)

    # Active pickup requests — safe because PickupRequest.parent_id → users.id
    pickup_result = await db.execute(
        select(PickupRequest)
        .where(
            PickupRequest.parent_id == parent.id,
            PickupRequest.tenant_id == tenant.id,
            PickupRequest.status == "requested",
        )
        .order_by(PickupRequest.requested_at.desc())
        .limit(5)
    )
    active_pickups = [
        {
            "pickup_id": str(p.id),
            "student_id": str(p.student_id),
            "status": p.status,
            "requested_at": p.requested_at.isoformat() if p.requested_at else None,
        }
        for p in pickup_result.scalars().all()
    ]

    # Timeline preview — last 5 events (empty in Phase 8.1)
    timeline_preview: list = []
    if family:
        tl_result = await db.execute(
            select(FamilyTimelineEvent)
            .where(
                FamilyTimelineEvent.family_id == family.id,
                FamilyTimelineEvent.tenant_id == tenant.id,
            )
            .order_by(FamilyTimelineEvent.occurred_at.desc())
            .limit(5)
        )
        timeline_preview = [
            {
                "event_id": str(e.id),
                "event_type": e.event_type,
                "title": e.title,
                "occurred_at": e.occurred_at.isoformat(),
                "priority": e.priority,
                "action_url": e.action_url,
            }
            for e in tl_result.scalars().all()
        ]

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.dashboard_viewed",
        entity_type="User",
        entity_id=parent.id,
        details={"student_count": len(students)},
    )
    await db.commit()

    return {
        "family_name": family.name if family else None,
        "family_id": str(family.id) if family else None,
        "students": students,
        "timeline_preview": timeline_preview,
        "pickup": {
            "available": True,
            "active_requests": active_pickups,
        },
        # Modules not yet implemented — explicit availability state
        "academics": _module_unavailable("Academic module not yet configured."),
        "attendance": _module_unavailable("Attendance module not yet configured."),
        "homework": _module_unavailable("Homework module not yet configured."),
        "reports": _module_unavailable("Report module not yet configured."),
        "messages": _module_unavailable("Messaging module not yet configured."),
        "payments": _module_unavailable("Finance module not yet configured."),
        "announcements": _module_unavailable("Announcement module not yet configured."),
        "notifications": _module_unavailable("Notification module not yet configured."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /parent/settings  —  read preferences
# PATCH /parent/settings  —  update preferences
# ─────────────────────────────────────────────────────────────────────────────

class PreferencesUpdate(BaseModel):
    preferred_language: str | None = None
    timezone: str | None = None
    theme: str | None = None
    weekly_report_digest: bool | None = None
    email_notifications: bool | None = None
    in_app_notifications: bool | None = None


@router.get("/settings", summary="Parent notification and display settings")
async def get_parent_settings(
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    prefs: ParentPreferences = Depends(resolve_or_create_parent_preferences),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    return {
        "preferred_language": prefs.preferred_language,
        "timezone": prefs.timezone,
        "theme": prefs.theme,
        "weekly_report_digest": prefs.weekly_report_digest,
        "email_notifications": prefs.email_notifications,
        "in_app_notifications": prefs.in_app_notifications,
    }


@router.patch("/settings", summary="Update parent notification and display settings")
async def update_parent_settings(
    body: PreferencesUpdate,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    prefs: ParentPreferences = Depends(resolve_or_create_parent_preferences),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    valid_themes = {"light", "dark", "system"}
    if body.theme is not None and body.theme not in valid_themes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"theme must be one of {sorted(valid_themes)}.",
        )

    if body.preferred_language is not None:
        prefs.preferred_language = body.preferred_language
    if body.timezone is not None:
        prefs.timezone = body.timezone
    if body.theme is not None:
        prefs.theme = body.theme
    if body.weekly_report_digest is not None:
        prefs.weekly_report_digest = body.weekly_report_digest
    if body.email_notifications is not None:
        prefs.email_notifications = body.email_notifications
    if body.in_app_notifications is not None:
        prefs.in_app_notifications = body.in_app_notifications

    db.add(prefs)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.settings_updated",
        entity_type="ParentPreferences",
        entity_id=prefs.id,
        actor_id=parent.id,
        details={},
    )
    await db.commit()
    await db.refresh(prefs)

    return {
        "preferred_language": prefs.preferred_language,
        "timezone": prefs.timezone,
        "theme": prefs.theme,
        "weekly_report_digest": prefs.weekly_report_digest,
        "email_notifications": prefs.email_notifications,
        "in_app_notifications": prefs.in_app_notifications,
    }
