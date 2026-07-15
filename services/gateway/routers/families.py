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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.dependencies import resolve_authenticated_parent, resolve_family
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Student, StudentParent, Tenant, User
from shared.db.parent_models import FamilyTimelineEvent, Family

router = APIRouter(prefix="/families", tags=["Families"])


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
