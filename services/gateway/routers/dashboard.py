"""
Principal Dashboard Router
===========================
Real-time leadership analytics using data we already have.

Endpoints
---------
GET  /dashboard/summary          – all 3 metrics in one response
GET  /dashboard/teacher-load     – detailed teacher workload analysis
GET  /dashboard/substitutions    – substitution frequency breakdown
GET  /dashboard/pickup-stats     – pickup activity analytics
"""

import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.gateway.ai.audit import log_action
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    PickupRequest,
    Student,
    Substitution,
    Teacher,
    TimetableEntry,
    Tenant,
    User,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ─────────────────────────────────────────────────────────────────────────────
# GET /dashboard/summary  —  everything at a glance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary", summary="Principal dashboard – all metrics at a glance")
async def dashboard_summary(
    academic_year: str = "2025-2026",
    days_back: int = 7,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    since = date_type.today() - timedelta(days=days_back)

    teacher_load = await _teacher_load_data(db, tenant.id, academic_year)
    sub_stats = await _substitution_stats(db, tenant.id, since)
    pickup_stats = await _pickup_stats(db, tenant.id, since)

    # Headline numbers
    overloaded = [t for t in teacher_load if t["load_pct"] > 85]
    spare = [t for t in teacher_load if t["load_pct"] < 50]

    await log_action(
        db=db, tenant_id=tenant.id,
        action="dashboard.viewed",
        entity_type="Dashboard",
        details={"view": "summary", "academic_year": academic_year, "days_back": days_back},
    )
    await db.commit()

    return {
        "period": f"last {days_back} days (since {since.isoformat()})",
        "academic_year": academic_year,
        "teacher_load": {
            "total_teachers": len(teacher_load),
            "overloaded_above_85pct": len(overloaded),
            "spare_capacity_below_50pct": len(spare),
            "overloaded_teachers": [
                {"name": t["name"], "load_pct": t["load_pct"], "assigned": t["assigned_periods"], "max": t["max_weekly_hours"]}
                for t in overloaded
            ],
        },
        "substitutions": sub_stats,
        "pickup": pickup_stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /dashboard/teacher-load  —  detailed teacher workload
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/teacher-load", summary="Teacher workload details")
async def teacher_load_detail(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    data = await _teacher_load_data(db, tenant.id, academic_year)
    await log_action(
        db=db, tenant_id=tenant.id,
        action="dashboard.viewed",
        entity_type="Dashboard",
        details={"view": "teacher-load", "academic_year": academic_year},
    )
    await db.commit()
    return {"teachers": data}


# ─────────────────────────────────────────────────────────────────────────────
# GET /dashboard/substitutions  —  substitution frequency
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/substitutions", summary="Substitution frequency breakdown")
async def substitution_detail(
    days_back: int = 30,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    since = date_type.today() - timedelta(days=days_back)
    stats = await _substitution_stats(db, tenant.id, since)
    await log_action(
        db=db, tenant_id=tenant.id,
        action="dashboard.viewed",
        entity_type="Dashboard",
        details={"view": "substitutions", "days_back": days_back},
    )
    await db.commit()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# GET /dashboard/pickup-stats  —  pickup activity
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/pickup-stats", summary="Pickup activity analytics")
async def pickup_detail(
    days_back: int = 30,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    since = date_type.today() - timedelta(days=days_back)
    stats = await _pickup_stats(db, tenant.id, since)
    await log_action(
        db=db, tenant_id=tenant.id,
        action="dashboard.viewed",
        entity_type="Dashboard",
        details={"view": "pickup-stats", "days_back": days_back},
    )
    await db.commit()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Internal: Teacher load calculation
# ─────────────────────────────────────────────────────────────────────────────

async def _teacher_load_data(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    academic_year: str,
) -> list[dict]:
    """Count weekly assigned periods per teacher vs their max_weekly_hours."""

    # All teachers
    teachers_q = await db.execute(
        select(Teacher)
        .where(Teacher.tenant_id == tenant_id)
        .options(selectinload(Teacher.user))
    )
    teachers = teachers_q.scalars().all()

    # Count assigned periods per teacher
    load_q = await db.execute(
        select(
            TimetableEntry.teacher_id,
            func.count(TimetableEntry.id).label("period_count"),
        )
        .where(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.is_active.is_(True),
        )
        .group_by(TimetableEntry.teacher_id)
    )
    load_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in load_q.all()}

    result = []
    for t in teachers:
        assigned = load_map.get(t.id, 0)
        max_h = t.max_weekly_hours or 20
        pct = round((assigned / max_h) * 100, 1) if max_h > 0 else 0
        result.append({
            "teacher_id": str(t.id),
            "name": t.user.name if t.user else "Unknown",
            "assigned_periods": assigned,
            "max_weekly_hours": max_h,
            "load_pct": pct,
            "status": "overloaded" if pct > 85 else ("normal" if pct >= 50 else "spare"),
        })

    result.sort(key=lambda x: x["load_pct"], reverse=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Internal: Substitution frequency
# ─────────────────────────────────────────────────────────────────────────────

async def _substitution_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    since: date_type,
) -> dict:
    """Substitution frequency: by substitute teacher and by class."""

    # Total subs
    total_q = await db.execute(
        select(func.count(Substitution.id)).where(
            Substitution.tenant_id == tenant_id,
            Substitution.date >= since,
        )
    )
    total = total_q.scalar() or 0

    assigned_q = await db.execute(
        select(func.count(Substitution.id)).where(
            Substitution.tenant_id == tenant_id,
            Substitution.date >= since,
            Substitution.status == "assigned",
        )
    )
    assigned = assigned_q.scalar() or 0

    # Most-called substitutes
    sub_freq_q = await db.execute(
        select(
            Substitution.substitute_teacher_id,
            func.count(Substitution.id).label("sub_count"),
        )
        .where(
            Substitution.tenant_id == tenant_id,
            Substitution.date >= since,
            Substitution.substitute_teacher_id.isnot(None),
        )
        .group_by(Substitution.substitute_teacher_id)
        .order_by(func.count(Substitution.id).desc())
        .limit(10)
    )
    sub_freq_rows = sub_freq_q.all()

    # Resolve teacher names
    sub_teacher_ids = [r[0] for r in sub_freq_rows]
    teacher_names: dict[uuid.UUID, str] = {}
    if sub_teacher_ids:
        tn_q = await db.execute(
            select(Teacher.id, User.name)
            .join(User, Teacher.user_id == User.id)
            .where(Teacher.id.in_(sub_teacher_ids))
        )
        teacher_names = {r[0]: r[1] for r in tn_q.all()}

    most_called_subs = [
        {"teacher_id": str(r[0]), "name": teacher_names.get(r[0], "Unknown"), "times_substituted": r[1]}
        for r in sub_freq_rows
    ]

    # Most absent teachers
    absent_freq_q = await db.execute(
        select(
            Substitution.absent_teacher_id,
            func.count(Substitution.id).label("absence_count"),
        )
        .where(
            Substitution.tenant_id == tenant_id,
            Substitution.date >= since,
        )
        .group_by(Substitution.absent_teacher_id)
        .order_by(func.count(Substitution.id).desc())
        .limit(10)
    )
    absent_freq_rows = absent_freq_q.all()

    absent_ids = [r[0] for r in absent_freq_rows]
    if absent_ids:
        atn_q = await db.execute(
            select(Teacher.id, User.name)
            .join(User, Teacher.user_id == User.id)
            .where(Teacher.id.in_(absent_ids))
        )
        for tid, name in atn_q.all():
            teacher_names[tid] = name

    most_absent = [
        {"teacher_id": str(r[0]), "name": teacher_names.get(r[0], "Unknown"), "absences": r[1]}
        for r in absent_freq_rows
    ]

    # Classes needing most cover
    class_freq_q = await db.execute(
        select(
            TimetableEntry.class_id,
            func.count(Substitution.id).label("cover_count"),
        )
        .join(TimetableEntry, Substitution.timetable_entry_id == TimetableEntry.id)
        .where(
            Substitution.tenant_id == tenant_id,
            Substitution.date >= since,
        )
        .group_by(TimetableEntry.class_id)
        .order_by(func.count(Substitution.id).desc())
        .limit(10)
    )
    class_freq_rows = class_freq_q.all()

    class_ids = [r[0] for r in class_freq_rows]
    class_names: dict[uuid.UUID, str] = {}
    if class_ids:
        cn_q = await db.execute(
            select(Class.id, Class.grade, Class.section).where(Class.id.in_(class_ids))
        )
        class_names = {r[0]: f"{r[1]} {r[2]}" for r in cn_q.all()}

    classes_needing_cover = [
        {"class_id": str(r[0]), "class": class_names.get(r[0], "Unknown"), "cover_count": r[1]}
        for r in class_freq_rows
    ]

    return {
        "since": since.isoformat(),
        "total_substitutions": total,
        "assigned": assigned,
        "unassigned": total - assigned,
        "most_called_substitutes": most_called_subs,
        "most_absent_teachers": most_absent,
        "classes_needing_most_cover": classes_needing_cover,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Internal: Pickup stats
# ─────────────────────────────────────────────────────────────────────────────

async def _pickup_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    since: date_type,
) -> dict:
    """Pickup activity: counts, avg time, early pickup by grade."""

    base_filter = [
        PickupRequest.tenant_id == tenant_id,
        func.date(PickupRequest.requested_at) >= since,
    ]

    # Total pickups
    total_q = await db.execute(
        select(func.count(PickupRequest.id)).where(*base_filter)
    )
    total = total_q.scalar() or 0

    # Released pickups
    released_q = await db.execute(
        select(func.count(PickupRequest.id)).where(
            *base_filter,
            PickupRequest.status == "released",
        )
    )
    released = released_q.scalar() or 0

    # Rejected (outside geofence)
    rejected_q = await db.execute(
        select(func.count(PickupRequest.id)).where(
            *base_filter,
            PickupRequest.status == "rejected_outside_geofence",
        )
    )
    rejected = rejected_q.scalar() or 0

    # Early pickups
    early_q = await db.execute(
        select(func.count(PickupRequest.id)).where(
            *base_filter,
            PickupRequest.early_pickup.is_(True),
        )
    )
    early_total = early_q.scalar() or 0

    # Early pickups by grade
    early_by_grade_q = await db.execute(
        select(
            Class.grade,
            func.count(PickupRequest.id).label("early_count"),
        )
        .join(Class, PickupRequest.class_id == Class.id)
        .where(
            *base_filter,
            PickupRequest.early_pickup.is_(True),
        )
        .group_by(Class.grade)
        .order_by(func.count(PickupRequest.id).desc())
    )
    early_by_grade = [
        {"grade": r[0], "early_pickups": r[1]}
        for r in early_by_grade_q.all()
    ]

    # Average pickup-to-release time (in minutes) for completed pickups
    avg_time_q = await db.execute(
        select(
            func.avg(
                func.extract("epoch", PickupRequest.released_at)
                - func.extract("epoch", PickupRequest.requested_at)
            )
        ).where(
            *base_filter,
            PickupRequest.status == "released",
            PickupRequest.released_at.isnot(None),
        )
    )
    avg_seconds = avg_time_q.scalar()
    avg_minutes = round(avg_seconds / 60, 1) if avg_seconds else None

    return {
        "since": since.isoformat(),
        "total_requests": total,
        "released": released,
        "rejected_outside_geofence": rejected,
        "pending": total - released - rejected,
        "early_pickups": early_total,
        "early_by_grade": early_by_grade,
        "avg_release_time_minutes": avg_minutes,
    }
