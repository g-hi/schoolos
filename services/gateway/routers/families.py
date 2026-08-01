"""
SchoolOS – Families Router  (Phase 8.1)
=========================================
Family aggregate endpoints.

GET /families/me          — family identity and members
GET /families/me/timeline — chronological family event feed

Family membership is inferred from StudentParent.family_id (Version 1).
Timeline returns an empty collection in Phase 8.1 — no production writers
are registered yet.  Writers are added as each module integrates
(Phases 8.5–8.6).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.dependencies import resolve_authenticated_parent, resolve_family
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Student, StudentParent, Tenant, User
from shared.db.parent_models import FamilyTimelineEvent, Family

router = APIRouter(prefix="/families", tags=["Families"])
leadership_router = APIRouter(prefix="/leadership/families", tags=["Families"])

SUPPORTED_RELATIONSHIP_TYPES = {"mother", "father", "guardian", "sponsor", "other"}


def _active_relationship_clause():
    # Compatibility: pre-lifecycle rows are considered active when is_active is NULL.
    return or_(StudentParent.is_active.is_(True), StudentParent.is_active.is_(None))


class RelationshipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID
    student_id: uuid.UUID
    relationship_type: str
    is_primary: bool = False


class RelationshipUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_type: str | None = None
    is_primary: bool | None = None
    is_active: bool | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Cursor helpers (occurred_at + id compound cursor)
# ─────────────────────────────────────────────────────────────────────────────

def _encode_cursor(occurred_at: datetime, event_id: uuid.UUID) -> str:
    raw = f"{occurred_at.isoformat()}|{str(event_id)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        iso_part, id_part = raw.split("|", 1)
        return datetime.fromisoformat(iso_part), uuid.UUID(id_part)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid cursor value.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /families/me
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me", summary="Family identity and member summary")
async def get_family_me(
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    family: Family = Depends(resolve_family),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    # All parent/guardian users linked to this family via StudentParent
    sp_result = await db.execute(
        select(StudentParent, User, Student)
        .join(User, User.id == StudentParent.parent_id)
        .join(Student, Student.id == StudentParent.student_id)
        .where(
            StudentParent.family_id == family.id,
            Student.tenant_id == tenant.id,
        )
    )
    rows = sp_result.all()

    # Group by parent, collect their students
    parents_map: dict[str, dict] = {}
    for sp, guardian, student in rows:
        pid = str(guardian.id)
        if pid not in parents_map:
            parents_map[pid] = {
                "parent_id": pid,
                "name": guardian.name,
                "email": guardian.email,
                "is_primary": bool(sp.is_primary),
                "student_ids": [],
            }
        parents_map[pid]["student_ids"].append(str(student.id))

    # All authorized students for the viewing parent
    student_result = await db.execute(
        select(StudentParent, Student)
        .join(Student, Student.id == StudentParent.student_id)
        .where(
            StudentParent.parent_id == parent.id,
            Student.tenant_id == tenant.id,
        )
        .order_by(Student.name)
    )
    authorized_students = [
        {
            "student_id": str(s.id),
            "name": s.name,
            "student_code": s.student_code,
        }
        for _, s in student_result.all()
    ]

    return {
        "family_id": str(family.id),
        "family_name": family.name,
        "is_active": family.is_active,
        "members": list(parents_map.values()),
        "students": authorized_students,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /families/me/timeline
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me/timeline", summary="Family Timeline — chronological event feed")
async def get_family_timeline(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    student_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    family: Family = Depends(resolve_family),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns family timeline events in reverse chronological order.

    Cursor-based pagination:
    - Pass ?cursor=<next_cursor> from the previous response to get the next page.
    - ?limit defaults to 20 (max 100).
    - ?student_id filters to a specific child's events.
    - ?category filters by event_category (e.g., 'pickup', 'academic').

    Phase 8.1 status:
    No production event writers are registered yet.
    This endpoint returns an empty collection.
    Writers are added in Phases 8.5–8.6 as modules integrate.
    """
    await set_tenant_context(db, tenant.id)

    # Validate student_id belongs to this parent if supplied
    if student_id:
        sp_result = await db.execute(
            select(StudentParent).where(
                StudentParent.student_id == student_id,
                StudentParent.parent_id == parent.id,
            )
        )
        if not sp_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Student not found.",
            )

    query = select(FamilyTimelineEvent).where(
        FamilyTimelineEvent.family_id == family.id,
        FamilyTimelineEvent.tenant_id == tenant.id,
    )

    if student_id:
        query = query.where(FamilyTimelineEvent.student_id == student_id)

    if category:
        query = query.where(FamilyTimelineEvent.event_category == category)

    # Apply cursor: events strictly before the cursor position
    if cursor:
        cursor_occurred_at, cursor_id = _decode_cursor(cursor)
        query = query.where(
            (FamilyTimelineEvent.occurred_at < cursor_occurred_at)
            | (
                (FamilyTimelineEvent.occurred_at == cursor_occurred_at)
                & (FamilyTimelineEvent.id < cursor_id)
            )
        )

    # Fetch limit + 1 to detect if there is a next page
    query = query.order_by(
        FamilyTimelineEvent.occurred_at.desc(),
        FamilyTimelineEvent.id.desc(),
    ).limit(limit + 1)

    result = await db.execute(query)
    events = list(result.scalars().all())

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    next_cursor = None
    if has_more and events:
        last = events[-1]
        next_cursor = _encode_cursor(last.occurred_at, last.id)

    return {
        "events": [
            {
                "event_id": str(e.id),
                "event_type": e.event_type,
                "event_category": e.event_category,
                "title": e.title,
                "description": e.description,
                "occurred_at": e.occurred_at.isoformat(),
                "student_id": str(e.student_id) if e.student_id else None,
                "source_module": e.source_module,
                "priority": e.priority,
                "action_url": e.action_url,
                "visibility": e.visibility,
            }
            for e in events
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@leadership_router.get("/relationships", summary="List family relationships")
async def list_relationships(
    student_id: uuid.UUID | None = Query(default=None),
    parent_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=True),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    stmt = (
        select(StudentParent, Student, User)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(Student.tenant_id == tenant.id, User.tenant_id == tenant.id)
    )
    if student_id is not None:
        stmt = stmt.where(StudentParent.student_id == student_id)
    if parent_id is not None:
        stmt = stmt.where(StudentParent.parent_id == parent_id)
    if active_only:
        stmt = stmt.where(_active_relationship_clause())

    rows = (await db.execute(stmt.order_by(Student.name.asc(), User.name.asc()))).all()
    return [
        {
            "relationship_id": f"{str(sp.student_id)}:{str(sp.parent_id)}",
            "student_id": str(student.id),
            "student_name": student.name,
            "parent_id": str(parent.id),
            "parent_name": parent.name,
            "relationship_type": sp.relation_type,
            "is_primary": bool(sp.is_primary),
            "is_active": True if sp.is_active is None else bool(sp.is_active),
            "created_at": getattr(sp, "created_at", None),
            "updated_at": getattr(sp, "updated_at", None),
        }
        for sp, student, parent in rows
    ]


@leadership_router.post("/relationships", summary="Create family relationship")
async def create_relationship(
    body: RelationshipCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    if body.relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid relationship_type.")

    parent = await db.scalar(
        select(User).where(
            User.id == body.parent_id,
            User.tenant_id == tenant.id,
            User.role == "parent",
        )
    )
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent not found.")
    if hasattr(parent, "is_active") and not bool(parent.is_active):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parent account is inactive.")

    student = await db.scalar(
        select(Student).where(
            Student.id == body.student_id,
            Student.tenant_id == tenant.id,
        )
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    duplicate = await db.scalar(
        select(StudentParent.student_id).where(
            StudentParent.student_id == body.student_id,
            StudentParent.parent_id == body.parent_id,
            _active_relationship_clause(),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active relationship.")

    rel = StudentParent(
        student_id=body.student_id,
        parent_id=body.parent_id,
        relation_type=body.relationship_type,
        is_primary=body.is_primary,
        is_active=True,
    )
    db.add(rel)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="family_relationship.created",
        entity_type="StudentParent",
        entity_id=body.student_id,
        actor_id=actor.id,
        details={
            "student_id": str(body.student_id),
            "parent_id": str(body.parent_id),
            "relationship_type": body.relationship_type,
            "is_primary": body.is_primary,
        },
    )

    await db.commit()
    return {
        "relationship_id": f"{str(body.student_id)}:{str(body.parent_id)}",
        "student_id": str(body.student_id),
        "parent_id": str(body.parent_id),
        "relationship_type": rel.relation_type,
        "is_primary": bool(rel.is_primary),
        "is_active": True if rel.is_active is None else bool(rel.is_active),
    }


@leadership_router.patch("/relationships/{relationship_id}", summary="Update family relationship lifecycle")
async def update_relationship(
    relationship_id: str,
    body: RelationshipUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    try:
        student_part, parent_part = relationship_id.split(":", 1)
        student_uuid = uuid.UUID(student_part)
        parent_uuid = uuid.UUID(parent_part)
    except Exception as exc:  # pragma: no cover - defensive parse guard
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid relationship_id format.") from exc

    rel = await db.scalar(
        select(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(
            StudentParent.student_id == student_uuid,
            StudentParent.parent_id == parent_uuid,
            Student.tenant_id == tenant.id,
            User.tenant_id == tenant.id,
        )
    )
    if rel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found.")

    if body.relationship_type is not None:
        if body.relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid relationship_type.")
        rel.relation_type = body.relationship_type

    if body.is_primary is not None:
        rel.is_primary = body.is_primary

    if body.is_active is not None:
        rel.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="family_relationship.updated" if body.is_active is not False else "family_relationship.deactivated",
        entity_type="StudentParent",
        entity_id=student_uuid,
        actor_id=actor.id,
        details={
            "student_id": str(student_uuid),
            "parent_id": str(parent_uuid),
            "relationship_type": rel.relation_type,
            "is_primary": bool(rel.is_primary),
            "is_active": True if rel.is_active is None else bool(rel.is_active),
        },
    )

    await db.commit()
    return {
        "relationship_id": relationship_id,
        "student_id": str(student_uuid),
        "parent_id": str(parent_uuid),
        "relationship_type": rel.relation_type,
        "is_primary": bool(rel.is_primary),
        "is_active": True if rel.is_active is None else bool(rel.is_active),
    }


@leadership_router.get("/summary", summary="Family relationship diagnostics")
async def relationships_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    total_active_relationships = await db.scalar(
        select(func.count())
        .select_from(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(Student.tenant_id == tenant.id, User.tenant_id == tenant.id, _active_relationship_clause())
    ) or 0

    active_by_student = (
        await db.execute(
            select(StudentParent.student_id, func.count())
            .join(Student, Student.id == StudentParent.student_id)
            .join(User, User.id == StudentParent.parent_id)
            .where(Student.tenant_id == tenant.id, User.tenant_id == tenant.id, _active_relationship_clause())
            .group_by(StudentParent.student_id)
        )
    ).all()
    active_count_map = {sid: count for sid, count in active_by_student}

    tenant_students = (
        await db.execute(select(Student.id).where(Student.tenant_id == tenant.id))
    ).scalars().all()
    students_with_no_active_parent_guardian_relationship = sum(1 for sid in tenant_students if active_count_map.get(sid, 0) == 0)
    students_with_multiple_active_relationships = sum(1 for sid in tenant_students if active_count_map.get(sid, 0) > 1)

    primary_relationships = await db.scalar(
        select(func.count())
        .select_from(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(Student.tenant_id == tenant.id, User.tenant_id == tenant.id, _active_relationship_clause(), StudentParent.is_primary.is_(True))
    ) or 0

    inactive_historical_relationships = await db.scalar(
        select(func.count())
        .select_from(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(Student.tenant_id == tenant.id, User.tenant_id == tenant.id, StudentParent.is_active.is_(False))
    ) or 0

    cross_tenant_inconsistencies = await db.scalar(
        select(func.count())
        .select_from(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .join(User, User.id == StudentParent.parent_id)
        .where(Student.tenant_id != User.tenant_id)
    ) or 0

    return {
        "total_active_relationships": total_active_relationships,
        "students_with_no_active_parent_guardian_relationship": students_with_no_active_parent_guardian_relationship,
        "students_with_multiple_active_relationships": students_with_multiple_active_relationships,
        "primary_relationships": primary_relationships,
        "inactive_historical_relationships": inactive_historical_relationships,
        "cross_tenant_inconsistencies": cross_tenant_inconsistencies,
    }
