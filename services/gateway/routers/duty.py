"""
Duty Schedule Router
====================
Manages duty locations, duty time slots, and auto-assignment of teachers
to supervise specific locations during non-teaching times.

Endpoints
---------
POST /duties/locations       – add a duty location
GET  /duties/locations       – list all duty locations
POST /duties/slots           – add a duty time slot
GET  /duties/slots           – list all duty slots
POST /duties/generate        – auto-assign teachers for a week (LLM-powered)
GET  /duties/                – view assignments for a week
DELETE /duties/reset          – clear assignments for a week
GET  /duties/download/pdf    – download duty roster as PDF
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    DutyAssignment,
    DutyLocation,
    DutySlot,
    Teacher,
    Tenant,
    TimetableEntry,
    User,
)

router = APIRouter(prefix="/duties", tags=["Duty Schedule"])

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class LocationCreate(BaseModel):
    name: str
    description: str | None = None

class SlotCreate(BaseModel):
    name: str           # e.g. "Morning Arrival", "Break", "Lunch", "Closing"
    start_time: str     # "07:30"
    end_time: str       # "08:00"

class GenerateRequest(BaseModel):
    academic_year: str = "2025-2026"


# ─────────────────────────────────────────────────────────────────────────────
# POST /duties/locations
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/locations", summary="Add a duty location")
async def create_location(
    body: LocationCreate,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    loc = DutyLocation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=body.name.strip(),
        description=body.description,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)

    return {"id": str(loc.id), "name": loc.name, "description": loc.description}


# ─────────────────────────────────────────────────────────────────────────────
# GET /duties/locations
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/locations", summary="List all duty locations")
async def list_locations(
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    q = await db.execute(
        select(DutyLocation)
        .where(DutyLocation.tenant_id == tenant.id, DutyLocation.is_active.is_(True))
        .order_by(DutyLocation.name)
    )
    locs = q.scalars().all()
    return [{"id": str(l.id), "name": l.name, "description": l.description} for l in locs]


# ─────────────────────────────────────────────────────────────────────────────
# POST /duties/slots
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/slots", summary="Add a duty time slot")
async def create_slot(
    body: SlotCreate,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    slot = DutySlot(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=body.name.strip(),
        start_time=body.start_time.strip(),
        end_time=body.end_time.strip(),
    )
    db.add(slot)
    await db.commit()
    await db.refresh(slot)

    return {"id": str(slot.id), "name": slot.name, "start_time": slot.start_time, "end_time": slot.end_time}


# ─────────────────────────────────────────────────────────────────────────────
# GET /duties/slots
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/slots", summary="List all duty time slots")
async def list_slots(
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    q = await db.execute(
        select(DutySlot)
        .where(DutySlot.tenant_id == tenant.id, DutySlot.is_active.is_(True))
        .order_by(DutySlot.start_time)
    )
    slots = q.scalars().all()
    return [{"id": str(s.id), "name": s.name, "start_time": s.start_time, "end_time": s.end_time} for s in slots]


# ─────────────────────────────────────────────────────────────────────────────
# POST /duties/generate — auto-assign teachers for a week
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate", summary="Auto-assign recurring duty roster (LLM-powered)")
async def generate_duties(
    body: GenerateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Generates a recurring weekly duty pattern for the academic year.
    For each (day, duty_slot, location):
      1. Check each teacher's timetable to see if they're free during that slot.
      2. Count their assigned duties so far (for fairness).
      3. Ask the LLM agent to pick the fairest teacher.
      4. Save the DutyAssignment (recurring — no specific week).
    """
    from services.gateway.ai.duty_agent import pick_duty_teacher

    await set_tenant_context(db, tenant.id)

    # Load duty slots and locations
    slots_q = await db.execute(
        select(DutySlot)
        .where(DutySlot.tenant_id == tenant.id, DutySlot.is_active.is_(True))
        .order_by(DutySlot.start_time)
    )
    duty_slots = slots_q.scalars().all()

    locs_q = await db.execute(
        select(DutyLocation)
        .where(DutyLocation.tenant_id == tenant.id, DutyLocation.is_active.is_(True))
        .order_by(DutyLocation.name)
    )
    locations = locs_q.scalars().all()

    if not duty_slots:
        raise HTTPException(status_code=400, detail="No duty slots configured. Add duty slots first.")
    if not locations:
        raise HTTPException(status_code=400, detail="No duty locations configured. Add locations first.")

    # Load all teachers
    teachers_q = await db.execute(
        select(Teacher)
        .where(Teacher.tenant_id == tenant.id)
        .options(selectinload(Teacher.user))
    )
    all_teachers = teachers_q.scalars().all()

    if not all_teachers:
        raise HTTPException(status_code=400, detail="No teachers found.")

    # Pre-load timetable entries for the week to check teacher availability
    # We need to know which teachers are teaching during each duty slot's time window
    timetable_q = await db.execute(
        select(TimetableEntry)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.academic_year == body.academic_year,
            TimetableEntry.is_active.is_(True),
        )
        .options(selectinload(TimetableEntry.period))
    )
    all_timetable = timetable_q.scalars().all()

    # Build lookup: (teacher_id, day_of_week) -> list of (start_time, end_time)
    teacher_schedule: dict[tuple, list[tuple[str, str]]] = {}
    for te in all_timetable:
        key = (te.teacher_id, te.day_of_week)
        teacher_schedule.setdefault(key, []).append(
            (te.period.start_time, te.period.end_time)
        )

    # Count weekly teaching periods per teacher
    teacher_weekly_periods: dict[uuid.UUID, int] = {}
    for te in all_timetable:
        teacher_weekly_periods[te.teacher_id] = teacher_weekly_periods.get(te.teacher_id, 0) + 1

    results = []
    duty_count: dict[uuid.UUID, int] = {}  # track total duties for fairness

    for day_idx in range(5):  # Mon-Fri
        for duty_slot in duty_slots:
            for location in locations:
                # Build candidate list: check who is free during this duty slot
                candidates = []
                for teacher in all_teachers:
                    name = teacher.user.name if teacher.user else f"Teacher-{teacher.id}"
                    max_h = teacher.max_weekly_hours or 20

                    # Check if teacher is teaching during this duty slot on this day
                    periods_today = teacher_schedule.get((teacher.id, day_idx), [])
                    is_free = not _times_overlap(
                        duty_slot.start_time, duty_slot.end_time, periods_today
                    )

                    weekly_periods = teacher_weekly_periods.get(teacher.id, 0)
                    duties = duty_count.get(teacher.id, 0)

                    candidates.append({
                        "name": name,
                        "is_free": is_free,
                        "weekly_periods": weekly_periods,
                        "max_weekly_hours": max_h,
                        "duties_this_week": duties,
                    })

                duty_info = {
                    "slot_name": duty_slot.name,
                    "start_time": duty_slot.start_time,
                    "end_time": duty_slot.end_time,
                    "location": location.name,
                    "day": DAY_NAMES[day_idx],
                }

                llm_result = await pick_duty_teacher(
                    duty=duty_info,
                    candidates=candidates,
                )

                chosen_name = llm_result.get("chosen")
                reasoning = llm_result.get("reasoning", "")
                chosen_teacher = None

                if chosen_name:
                    # Map name back to Teacher
                    for t in all_teachers:
                        t_name = t.user.name if t.user else ""
                        if t_name.lower() == chosen_name.lower():
                            chosen_teacher = t
                            break
                    # Fuzzy fallback
                    if not chosen_teacher:
                        for t in all_teachers:
                            t_name = t.user.name if t.user else ""
                            if chosen_name.lower() in t_name.lower() or t_name.lower() in chosen_name.lower():
                                chosen_teacher = t
                                break

                if chosen_teacher:
                    assignment = DutyAssignment(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        teacher_id=chosen_teacher.id,
                        duty_slot_id=duty_slot.id,
                        location_id=location.id,
                        day_of_week=day_idx,
                        academic_year=body.academic_year,
                        ai_reasoning=reasoning,
                    )
                    db.add(assignment)
                    duty_count[chosen_teacher.id] = duty_count.get(chosen_teacher.id, 0) + 1

                results.append({
                    "day": DAY_NAMES[day_idx],
                    "slot": duty_slot.name,
                    "location": location.name,
                    "teacher": (chosen_teacher.user.name if chosen_teacher and chosen_teacher.user else None),
                    "reasoning": reasoning,
                })

    await db.commit()

    # Audit
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="duty.generated",
        entity_type="DutyAssignment",
        entity_id=None,
        details={"academic_year": body.academic_year, "total_assignments": sum(1 for r in results if r["teacher"])},
    )
    await db.commit()

    assigned = sum(1 for r in results if r["teacher"])
    return {
        "academic_year": body.academic_year,
        "assignments": results,
        "summary": {
            "total_slots": len(results),
            "assigned": assigned,
            "unassigned": len(results) - assigned,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /duties/ — view recurring duty pattern
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", summary="View recurring duty roster for an academic year")
async def list_duties(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    q = await db.execute(
        select(DutyAssignment)
        .where(
            DutyAssignment.tenant_id == tenant.id,
            DutyAssignment.academic_year == academic_year,
        )
        .options(
            selectinload(DutyAssignment.teacher).selectinload(Teacher.user),
            selectinload(DutyAssignment.duty_slot),
            selectinload(DutyAssignment.location),
        )
        .order_by(DutyAssignment.day_of_week)
    )
    assignments = q.scalars().all()

    return [
        {
            "id": str(a.id),
            "day": DAY_NAMES[a.day_of_week],
            "day_of_week": a.day_of_week,
            "slot": a.duty_slot.name,
            "slot_time": f"{a.duty_slot.start_time}-{a.duty_slot.end_time}",
            "location": a.location.name,
            "teacher": a.teacher.user.name if a.teacher and a.teacher.user else None,
            "reasoning": a.ai_reasoning,
        }
        for a in assignments
    ]


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /duties/reset — clear duty roster for a year
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/reset", summary="Clear duty roster for an academic year")
async def reset_duties(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        sa_delete(DutyAssignment).where(
            DutyAssignment.tenant_id == tenant.id,
            DutyAssignment.academic_year == academic_year,
        )
    )
    await db.commit()
    return {"deleted": result.rowcount, "academic_year": academic_year}


# ─────────────────────────────────────────────────────────────────────────────
# GET /duties/download/pdf
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/download/pdf", summary="Download duty roster as PDF")
async def download_duty_pdf(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
):
    from services.gateway.ai.duty_pdf import build_duty_pdf

    pdf_bytes = await build_duty_pdf(tenant.id, academic_year)
    filename = f"duty_roster_{tenant.slug}_{academic_year}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: check if a duty slot time overlaps any teaching periods
# ─────────────────────────────────────────────────────────────────────────────

def _times_overlap(duty_start: str, duty_end: str, periods: list[tuple[str, str]]) -> bool:
    """
    Returns True if the duty time window overlaps with any teaching period.
    Times are "HH:MM" strings.
    """
    ds = _to_minutes(duty_start)
    de = _to_minutes(duty_end)
    for p_start, p_end in periods:
        ps = _to_minutes(p_start)
        pe = _to_minutes(p_end)
        if ds < pe and de > ps:
            return True
    return False


def _to_minutes(t: str) -> int:
    """Convert "HH:MM" to minutes since midnight."""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])
