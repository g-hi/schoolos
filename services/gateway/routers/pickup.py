"""
Phase 5 - Pickup Router (MVP)
=============================
Private car pickup flow with geofence verification and audit trail.

Endpoints
---------
POST /pickup/request   - parent sends "I've arrived" / "Pickup <student>"
POST /pickup/release   - teacher confirms child release
GET  /pickup/log       - principal/admin audit log filters (including early pickups)

MVP behavior
------------
1. Parent request arrives with command + GPS coordinates.
2. System resolves parent and student.
3. System verifies parent is inside school geofence.
4. If inside: create pickup request, notify teacher, notify parent.
5. Teacher confirms release; system notifies parent and closes request.
"""

import math
import uuid
from datetime import datetime, date as date_type, time as time_type

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.gateway.ai.audit import log_action
from services.gateway.ai.messenger import send_to_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    PickupRequest,
    Student,
    StudentParent,
    Teacher,
    Tenant,
    TimetableEntry,
    User,
)

router = APIRouter(prefix="/pickup", tags=["Pickup"])


class PickupCreateRequest(BaseModel):
    parent_phone: str
    command_text: str
    latitude: float
    longitude: float
    channel: str | None = None  # whatsapp/sms; inferred from number prefix if omitted
    requested_at: str | None = None  # optional ISO datetime for backfill/testing
    academic_year: str = "2025-2026"


class PickupReleaseRequest(BaseModel):
    pickup_id: str
    teacher_phone: str | None = None
    notes: str | None = None


def _normalize_phone(phone: str) -> str:
    p = phone.strip().lower()
    if p.startswith("whatsapp:"):
        p = p.split(":", 1)[1]
    return p.replace(" ", "")


def _extract_student_name(command_text: str) -> str | None:
    txt = command_text.strip().lower()
    if txt in {"i've arrived", "ive arrived", "arrived", "i am here", "im here"}:
        return None
    if txt.startswith("pickup "):
        raw = command_text.strip()[7:].strip()
        return raw if raw else None
    return None


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _parse_requested_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="requested_at must be ISO format.")


def _infer_channel(channel: str | None, phone: str) -> str:
    if channel in {"whatsapp", "sms"}:
        return channel
    return "whatsapp" if phone.strip().lower().startswith("whatsapp:") else "sms"


def _get_geofence(tenant: Tenant) -> tuple[float | None, float | None, int]:
    settings = tenant.settings or {}
    lat = settings.get("pickup_latitude", settings.get("school_latitude"))
    lng = settings.get("pickup_longitude", settings.get("school_longitude"))
    radius = int(settings.get("pickup_radius_m", 150))
    return lat, lng, radius


async def _resolve_parent(db: AsyncSession, tenant_id: uuid.UUID, parent_phone: str) -> User:
    norm = _normalize_phone(parent_phone)
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.role == "parent",
            User.phone.isnot(None),
        )
    )
    parents = result.scalars().all()
    for p in parents:
        if p.phone and _normalize_phone(p.phone) == norm:
            return p
    raise HTTPException(status_code=404, detail="Parent phone not found.")


async def _resolve_student_for_parent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parent_id: uuid.UUID,
    student_hint: str | None,
) -> Student:
    q = await db.execute(
        select(Student)
        .join(StudentParent, StudentParent.student_id == Student.id)
        .where(
            Student.tenant_id == tenant_id,
            StudentParent.parent_id == parent_id,
        )
    )
    students = q.scalars().all()

    if not students:
        raise HTTPException(status_code=404, detail="No students linked to this parent.")

    if student_hint is None:
        if len(students) == 1:
            return students[0]
        raise HTTPException(
            status_code=400,
            detail="Multiple children found. Use 'Pickup <student name>'.",
        )

    hint = student_hint.strip().lower()
    exact = [s for s in students if s.name.strip().lower() == hint]
    if exact:
        return exact[0]

    partial = [s for s in students if hint in s.name.strip().lower()]
    if len(partial) == 1:
        return partial[0]

    raise HTTPException(status_code=404, detail="Student not found for this parent.")


async def _resolve_teacher_for_class(db: AsyncSession, tenant_id: uuid.UUID, class_id: uuid.UUID) -> Teacher | None:
    class_q = await db.execute(
        select(Class).where(Class.tenant_id == tenant_id, Class.id == class_id)
    )
    klass = class_q.scalar_one_or_none()
    if not klass or not klass.class_teacher_id:
        return None

    teacher_q = await db.execute(
        select(Teacher).where(
            Teacher.tenant_id == tenant_id,
            Teacher.id == klass.class_teacher_id,
        )
    )
    return teacher_q.scalar_one_or_none()


async def _is_early_pickup(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    academic_year: str,
    request_dt: datetime,
) -> bool:
    day_of_week = request_dt.weekday()
    if day_of_week > 4:
        return False

    q = await db.execute(
        select(Period.end_time)
        .join(TimetableEntry, TimetableEntry.period_id == Period.id)
        .where(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.class_id == class_id,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.day_of_week == day_of_week,
            TimetableEntry.is_active.is_(True),
        )
        .order_by(Period.sort_order.desc())
        .limit(1)
    )
    end_time = q.scalar_one_or_none()
    if not end_time:
        return False

    try:
        hh, mm = end_time.split(":")
        dismissal = time_type(hour=int(hh), minute=int(mm))
    except Exception:
        return False

    return request_dt.time() < dismissal


@router.post("/request", summary="Create pickup request from parent arrival command")
async def create_pickup_request(
    body: PickupCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    parent = await _resolve_parent(db, tenant.id, body.parent_phone)
    student_hint = _extract_student_name(body.command_text)
    student = await _resolve_student_for_parent(db, tenant.id, parent.id, student_hint)

    class_q = await db.execute(
        select(Class).where(Class.tenant_id == tenant.id, Class.id == student.class_id)
    )
    klass = class_q.scalar_one_or_none()
    if not klass:
        raise HTTPException(status_code=404, detail="Student class not found.")

    request_dt = _parse_requested_at(body.requested_at)
    channel = _infer_channel(body.channel, body.parent_phone)

    school_lat, school_lng, radius_m = _get_geofence(tenant)
    if school_lat is None or school_lng is None:
        raise HTTPException(
            status_code=400,
            detail="Pickup geofence is not configured. Set tenant.settings pickup_latitude/pickup_longitude.",
        )

    distance_m = _haversine_meters(body.latitude, body.longitude, float(school_lat), float(school_lng))
    inside = distance_m <= radius_m
    early_pickup = await _is_early_pickup(db, tenant.id, klass.id, body.academic_year, request_dt)

    teacher = await _resolve_teacher_for_class(db, tenant.id, klass.id)

    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher.id if teacher else None,
        channel=channel,
        command_text=body.command_text,
        parent_latitude=body.latitude,
        parent_longitude=body.longitude,
        distance_meters=distance_m,
        geofence_radius_m=radius_m,
        within_geofence=inside,
        early_pickup=early_pickup,
        status="requested" if inside else "rejected_outside_geofence",
        requested_at=request_dt,
        notes=None,
    )
    db.add(pickup)

    if not inside:
        await send_to_user(
            parent,
            "It looks like you are not at school yet. Please send again when you arrive.",
            "pickup_geofence_rejected",
            db,
            student_id=student.id,
            email_subject="[SchoolOS] Pickup Request Rejected",
        )
        await log_action(
            db=db,
            tenant_id=tenant.id,
            action="pickup.rejected_outside_geofence",
            entity_type="PickupRequest",
            entity_id=pickup.id,
            actor_id=parent.id,
            details={"student": student.name, "distance_m": round(distance_m, 1)},
        )
        await db.commit()
        return {
            "pickup_id": str(pickup.id),
            "status": pickup.status,
            "distance_meters": round(distance_m, 1),
            "geofence_radius_m": radius_m,
            "message": "Parent outside geofence.",
        }

    # Notify teacher
    if teacher:
        teacher_user_q = await db.execute(select(User).where(User.id == teacher.user_id))
        teacher_user = teacher_user_q.scalar_one_or_none()
        if teacher_user:
            await send_to_user(
                teacher_user,
                f"[SchoolOS] Pickup alert: {student.name}'s parent has arrived. Please release the student.",
                "pickup_teacher_alert",
                db,
                student_id=student.id,
                email_subject=f"[SchoolOS] Pickup Alert - {student.name}",
            )

    # Confirm to parent
    await send_to_user(
        parent,
        f"[SchoolOS] Pickup request received for {student.name}. Please wait while the teacher releases the student.",
        "pickup_parent_ack",
        db,
        student_id=student.id,
        email_subject=f"[SchoolOS] Pickup Received - {student.name}",
    )

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="pickup.requested",
        entity_type="PickupRequest",
        entity_id=pickup.id,
        actor_id=parent.id,
        details={
            "student": student.name,
            "class": f"{klass.grade} {klass.section}",
            "early_pickup": early_pickup,
            "distance_m": round(distance_m, 1),
        },
    )

    await db.commit()

    return {
        "pickup_id": str(pickup.id),
        "status": pickup.status,
        "student": student.name,
        "class": f"{klass.grade} {klass.section}",
        "teacher_notified": teacher is not None,
        "distance_meters": round(distance_m, 1),
        "geofence_radius_m": radius_m,
        "early_pickup": early_pickup,
    }


@router.post("/release", summary="Teacher confirms student release")
async def release_pickup(
    body: PickupReleaseRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    try:
        pickup_id = uuid.UUID(body.pickup_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="pickup_id must be a valid UUID.")

    q = await db.execute(
        select(PickupRequest)
        .where(
            PickupRequest.tenant_id == tenant.id,
            PickupRequest.id == pickup_id,
        )
        .options(
            selectinload(PickupRequest.parent),
            selectinload(PickupRequest.student),
            selectinload(PickupRequest.teacher),
        )
    )
    pickup = q.scalar_one_or_none()
    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found.")

    if pickup.status != "requested":
        raise HTTPException(status_code=400, detail=f"Pickup is already '{pickup.status}'.")

    if body.teacher_phone and pickup.teacher:
        teacher_user_q = await db.execute(select(User).where(User.id == pickup.teacher.user_id))
        teacher_user = teacher_user_q.scalar_one_or_none()
        if teacher_user and teacher_user.phone:
            if _normalize_phone(teacher_user.phone) != _normalize_phone(body.teacher_phone):
                raise HTTPException(status_code=403, detail="Teacher phone does not match assigned class teacher.")

    pickup.status = "released"
    pickup.released_at = datetime.utcnow()
    pickup.notes = body.notes

    # Notify parent
    await send_to_user(
        pickup.parent,
        f"[SchoolOS] {pickup.student.name} has been released and is on the way to you.",
        "pickup_released",
        db,
        student_id=pickup.student_id,
        email_subject=f"[SchoolOS] {pickup.student.name} Released",
    )

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="pickup.released",
        entity_type="PickupRequest",
        entity_id=pickup.id,
        details={
            "student": pickup.student.name,
            "parent": pickup.parent.name,
            "early_pickup": pickup.early_pickup,
        },
    )

    await db.commit()

    return {
        "pickup_id": str(pickup.id),
        "status": pickup.status,
        "released_at": pickup.released_at.isoformat() if pickup.released_at else None,
    }


@router.get("/log", summary="Pickup audit log")
async def pickup_log(
    start_date: str | None = None,
    end_date: str | None = None,
    grade: str | None = None,
    section: str | None = None,
    early_only: bool = False,
    limit: int = 100,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    query = (
        select(PickupRequest)
        .where(PickupRequest.tenant_id == tenant.id)
        .options(
            selectinload(PickupRequest.parent),
            selectinload(PickupRequest.student),
            selectinload(PickupRequest.klass),
            selectinload(PickupRequest.teacher),
        )
        .order_by(PickupRequest.requested_at.desc())
        .limit(min(limit, 500))
    )

    if start_date:
        try:
            start = date_type.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")
        query = query.where(func.date(PickupRequest.requested_at) >= start)

    if end_date:
        try:
            end = date_type.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date must be YYYY-MM-DD")
        query = query.where(func.date(PickupRequest.requested_at) <= end)

    if early_only:
        query = query.where(PickupRequest.early_pickup.is_(True))

    if grade or section:
        class_q = select(Class.id).where(Class.tenant_id == tenant.id)
        if grade:
            class_q = class_q.where(Class.grade == grade)
        if section:
            class_q = class_q.where(Class.section == section)
        class_ids_result = await db.execute(class_q)
        class_ids = class_ids_result.scalars().all()
        if not class_ids:
            return []
        query = query.where(PickupRequest.class_id.in_(class_ids))

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        {
            "pickup_id": str(r.id),
            "student": r.student.name if r.student else None,
            "parent": r.parent.name if r.parent else None,
            "class": f"{r.klass.grade} {r.klass.section}" if r.klass else None,
            "status": r.status,
            "channel": r.channel,
            "within_geofence": r.within_geofence,
            "distance_meters": round(r.distance_meters, 1),
            "early_pickup": r.early_pickup,
            "requested_at": str(r.requested_at),
            "released_at": str(r.released_at) if r.released_at else None,
            "notes": r.notes,
        }
        for r in rows
    ]
