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

import asyncio
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
    DutySlotLocation,
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

class SlotLocationAdd(BaseModel):
    name: str                    # location name — created if it doesn't exist
    description: str | None = None

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
# POST /duties/slots/{slot_id}/locations — link a location to a slot
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/slots/{slot_id}/locations", summary="Add a location to a duty slot")
async def add_slot_location(
    slot_id: str,
    body: SlotLocationAdd,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Link a location to a duty slot. Creates the location if it doesn't exist."""
    await set_tenant_context(db, tenant.id)

    # Verify slot exists
    slot_q = await db.execute(
        select(DutySlot).where(DutySlot.id == slot_id, DutySlot.tenant_id == tenant.id)
    )
    slot = slot_q.scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Duty slot not found")

    # Find or create location by name
    loc_q = await db.execute(
        select(DutyLocation).where(
            DutyLocation.tenant_id == tenant.id,
            func.lower(DutyLocation.name) == body.name.strip().lower(),
        )
    )
    location = loc_q.scalar_one_or_none()
    if not location:
        location = DutyLocation(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=body.name.strip(),
            description=body.description,
        )
        db.add(location)
        await db.flush()

    # Check if already linked
    existing = await db.execute(
        select(DutySlotLocation).where(
            DutySlotLocation.tenant_id == tenant.id,
            DutySlotLocation.slot_id == slot.id,
            DutySlotLocation.location_id == location.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Location already linked to this slot")

    link = DutySlotLocation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        slot_id=slot.id,
        location_id=location.id,
    )
    db.add(link)
    await db.commit()

    return {
        "id": str(link.id),
        "slot_id": str(slot.id),
        "location_id": str(location.id),
        "location_name": location.name,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /duties/slots/{slot_id}/locations/{location_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/slots/{slot_id}/locations/{location_id}", summary="Remove a location from a slot")
async def remove_slot_location(
    slot_id: str,
    location_id: str,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        sa_delete(DutySlotLocation).where(
            DutySlotLocation.tenant_id == tenant.id,
            DutySlotLocation.slot_id == slot_id,
            DutySlotLocation.location_id == location_id,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# GET /duties/slots-config — slots with their locations
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/slots-config", summary="Get all slots with their linked locations")
async def get_slots_config(
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    q = await db.execute(
        select(DutySlotLocation)
        .where(DutySlotLocation.tenant_id == tenant.id)
        .options(
            selectinload(DutySlotLocation.slot),
            selectinload(DutySlotLocation.location),
        )
    )
    links = q.scalars().all()

    # Also load slots with no locations yet
    slots_q = await db.execute(
        select(DutySlot)
        .where(DutySlot.tenant_id == tenant.id, DutySlot.is_active.is_(True))
        .order_by(DutySlot.start_time)
    )
    all_slots = slots_q.scalars().all()

    # Build slot -> locations map
    slot_map: dict[str, dict] = {}
    for s in all_slots:
        slot_map[str(s.id)] = {
            "id": str(s.id),
            "name": s.name,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "locations": [],
        }
    for link in links:
        sid = str(link.slot_id)
        if sid in slot_map:
            slot_map[sid]["locations"].append({
                "id": str(link.location.id),
                "name": link.location.name,
                "description": link.location.description,
            })

    return list(slot_map.values())


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
    Batches all slot-locations per day into ONE LLM call (5 calls total).
    """
    import traceback
    try:
        return await _do_generate(body, tenant, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")


async def _do_generate(body: GenerateRequest, tenant: Tenant, db: AsyncSession):
    from services.gateway.ai.duty_agent import pick_duty_teachers_batch

    await set_tenant_context(db, tenant.id)

    # ── Clear previous assignments for this academic year ──
    await db.execute(
        sa_delete(DutyAssignment).where(
            DutyAssignment.tenant_id == tenant.id,
            DutyAssignment.academic_year == body.academic_year,
        )
    )
    await db.flush()

    # Load slot-location mappings
    sl_q = await db.execute(
        select(DutySlotLocation)
        .where(DutySlotLocation.tenant_id == tenant.id)
        .options(
            selectinload(DutySlotLocation.slot),
            selectinload(DutySlotLocation.location),
        )
    )
    slot_locations = sl_q.scalars().all()

    if not slot_locations:
        raise HTTPException(
            status_code=400,
            detail="No slot-location mappings configured. Add locations to your duty slots first.",
        )

    # Load all teachers
    teachers_q = await db.execute(
        select(Teacher)
        .where(Teacher.tenant_id == tenant.id)
        .options(selectinload(Teacher.user))
    )
    all_teachers = teachers_q.scalars().all()

    if not all_teachers:
        raise HTTPException(status_code=400, detail="No teachers found.")

    # Pre-load timetable entries
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

    # Build name->teacher map for quick lookup
    teacher_by_name: dict[str, object] = {}
    for t in all_teachers:
        name = t.user.name if t.user else f"Teacher-{t.id}"
        teacher_by_name[name.lower()] = t

    # Build slot/location lookup by name
    slot_by_name: dict[str, object] = {}
    loc_by_name: dict[str, object] = {}
    for sl in slot_locations:
        slot_by_name[sl.slot.name] = sl.slot
        loc_by_name[sl.location.name] = sl.location

    results = []
    duty_count: dict[uuid.UUID, int] = {}
    # Track (teacher_id, slot_id, day_idx) to enforce unique constraint
    assigned_combos: set[tuple] = set()

    for day_idx in range(5):  # Mon-Fri
        # Build duties list for this day
        duties = []
        for sl in slot_locations:
            duties.append({
                "slot_name": sl.slot.name,
                "start_time": sl.slot.start_time,
                "end_time": sl.slot.end_time,
                "location": sl.location.name,
            })

        # Build teacher profiles with busy slots for this day
        teacher_profiles = []
        for teacher in all_teachers:
            name = teacher.user.name if teacher.user else f"Teacher-{teacher.id}"
            periods_today = teacher_schedule.get((teacher.id, day_idx), [])

            busy_slots = []
            for sl in slot_locations:
                if _times_overlap(sl.slot.start_time, sl.slot.end_time, periods_today):
                    if sl.slot.name not in busy_slots:
                        busy_slots.append(sl.slot.name)

            teacher_profiles.append({
                "name": name,
                "weekly_periods": teacher_weekly_periods.get(teacher.id, 0),
                "max_weekly_hours": teacher.max_weekly_hours or 20,
                "duties_so_far": duty_count.get(teacher.id, 0),
                "busy_slots": busy_slots,
            })

        # ONE LLM call for this entire day
        day_results = await pick_duty_teachers_batch(
            day=DAY_NAMES[day_idx],
            duties=duties,
            teachers=teacher_profiles,
        )

        # Small delay between days to avoid Groq rate limits
        if day_idx < 4:
            await asyncio.sleep(2)

        # Process results and save to DB
        for r in day_results:
            chosen_name = r.get("chosen")
            reasoning = r.get("reasoning", "")
            chosen_teacher = None

            if chosen_name:
                chosen_teacher = teacher_by_name.get(chosen_name.lower())
                if not chosen_teacher:
                    for key, t in teacher_by_name.items():
                        if chosen_name.lower() in key or key in chosen_name.lower():
                            chosen_teacher = t
                            break

            slot_obj = slot_by_name.get(r.get("slot", ""))
            loc_obj = loc_by_name.get(r.get("location", ""))

            if chosen_teacher and slot_obj and loc_obj:
                combo = (chosen_teacher.id, slot_obj.id, day_idx)
                if combo in assigned_combos:
                    # Teacher already assigned to this slot+day — pick alternate
                    used_names = {
                        (t.user.name if t.user else "").lower()
                        for tid, sid, di in assigned_combos
                        if sid == slot_obj.id and di == day_idx
                        for t in all_teachers
                        if t.id == tid
                    }
                    for t in sorted(all_teachers, key=lambda x: duty_count.get(x.id, 0)):
                        tname = t.user.name.lower() if t.user else ""
                        if tname not in used_names:
                            # Check not busy
                            periods_today = teacher_schedule.get((t.id, day_idx), [])
                            if not _times_overlap(slot_obj.start_time, slot_obj.end_time, periods_today):
                                chosen_teacher = t
                                combo = (t.id, slot_obj.id, day_idx)
                                reasoning = f"Re-assigned to avoid duplicate (original: {chosen_name})"
                                break
                    else:
                        # All teachers already used or busy — skip
                        chosen_teacher = None

                if chosen_teacher and combo not in assigned_combos:
                    assigned_combos.add(combo)
                    assignment = DutyAssignment(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        teacher_id=chosen_teacher.id,
                        duty_slot_id=slot_obj.id,
                        location_id=loc_obj.id,
                        day_of_week=day_idx,
                        academic_year=body.academic_year,
                        ai_reasoning=reasoning,
                    )
                    db.add(assignment)
                    duty_count[chosen_teacher.id] = duty_count.get(chosen_teacher.id, 0) + 1

            results.append({
                "day": DAY_NAMES[day_idx],
                "slot": r.get("slot", ""),
                "location": r.get("location", ""),
                "teacher": (chosen_teacher.user.name if chosen_teacher and chosen_teacher.user else None),
                "reasoning": reasoning,
            })

    await db.commit()

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
