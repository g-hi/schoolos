from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import MultipleResultsFound

from services.gateway.ai.audit import log_action
from services.gateway.ai.family_timeline import write_timeline_event
from services.gateway.ai.messenger import send_to_user
from services.gateway.authorization.teacher_scope import teacher_has_homeroom_scope, teacher_has_subject_scope
from shared.auth.dependencies import (
    resolve_authenticated_leadership,
    resolve_authenticated_parent,
    resolve_authenticated_teacher,
    resolve_family,
    validate_parent_student_access,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Appointment,
    Class,
    Student,
    StudentParent,
    Subject,
    Teacher,
    TimetableEntry,
    Tenant,
    User,
)
from shared.db.parent_models import Family

router = APIRouter(prefix="", tags=["Appointments"])
logger = logging.getLogger(__name__)

ALLOWED_APPOINTMENT_TRANSITIONS = {
    "requested": {"confirmed", "declined", "cancelled"},
    "confirmed": {"cancelled", "completed"},
}


class AppointmentCreateRequest(BaseModel):
    student_id: uuid.UUID
    teacher_id: uuid.UUID
    subject_id: uuid.UUID | None = None
    timetable_entry_id: uuid.UUID | None = None
    requested_start_at: datetime
    duration_minutes: int
    timezone: str
    meeting_mode: str
    location_or_link: str | None = None
    reason: str | None = None
    parent_notes: str | None = None

    @field_validator("requested_start_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("requested_start_at must be timezone-aware")
        if value <= datetime.now(timezone.utc):
            raise ValueError("requested_start_at must be in the future")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def valid_duration(cls, value: int) -> int:
        if value < 10 or value > 180:
            raise ValueError("duration_minutes must be between 10 and 180")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("meeting_mode")
    @classmethod
    def valid_meeting_mode(cls, value: str) -> str:
        if value not in {"in_person", "video", "phone"}:
            raise ValueError("meeting_mode must be one of in_person, video, phone")
        return value


class ParentAppointmentRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_start_at: datetime | None = None
    duration_minutes: int | None = None
    timezone: str | None = None
    meeting_mode: str | None = None
    location_or_link: str | None = None

    @field_validator("scheduled_start_at")
    @classmethod
    def must_be_timezone_aware_future_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("scheduled_start_at must be timezone-aware")
        if value <= datetime.now(timezone.utc):
            raise ValueError("scheduled_start_at must be in the future")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def valid_duration(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 10 or value > 180:
            raise ValueError("duration_minutes must be between 10 and 180")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("meeting_mode")
    @classmethod
    def valid_meeting_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"in_person", "video", "phone"}:
            raise ValueError("meeting_mode must be one of in_person, video, phone")
        return value


class TeacherAppointmentActionRequest(ParentAppointmentRescheduleRequest):
    model_config = ConfigDict(extra="forbid")

    staff_notes: str | None = None


class AppointmentListQuery(BaseModel):
    status: str | None = None
    teacher_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = 1
    page_size: int = 20


async def _resolve_teacher_profile(db: AsyncSession, tenant_id: uuid.UUID, user: User) -> Teacher | None:
    try:
        result = await db.execute(select(Teacher).where(Teacher.tenant_id == tenant_id, Teacher.user_id == user.id))
        return result.scalar_one_or_none()
    except MultipleResultsFound as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teacher profile data is inconsistent. Contact school administrator.",
        ) from exc


async def _lock_teacher_profile(db: AsyncSession, *, tenant_id: uuid.UUID, teacher_id: uuid.UUID) -> Teacher | None:
    result = await db.execute(
        select(Teacher)
        .where(Teacher.tenant_id == tenant_id, Teacher.id == teacher_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


def _appointments_overlap(existing_start: datetime, existing_end: datetime, proposed_start: datetime, proposed_end: datetime) -> bool:
    return existing_start < proposed_end and existing_end > proposed_start


async def _find_confirmed_overlap(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    proposed_start: datetime,
    proposed_end: datetime,
    current_appointment_id: uuid.UUID | None = None,
) -> Appointment | None:
    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.teacher_id == teacher_id,
            Appointment.status == "confirmed",
        )
    )
    for existing in result.scalars().all():
        if current_appointment_id is not None and existing.id == current_appointment_id:
            continue
        existing_end = existing.scheduled_start_at + timedelta(minutes=existing.duration_minutes)
        if _appointments_overlap(existing.scheduled_start_at, existing_end, proposed_start, proposed_end):
            return existing
    return None


def _validate_future_appointment_datetime(value: datetime, *, field_name: str = "scheduled_start_at") -> None:
    if value.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be timezone-aware")
    if value <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be in the future")


def _validate_iana_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="timezone must be a valid IANA timezone") from exc


def _validate_duration_minutes(value: int) -> None:
    if value < 10 or value > 180:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="duration_minutes must be between 10 and 180")


def _validate_meeting_mode(value: str) -> None:
    if value not in {"in_person", "video", "phone"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="meeting_mode must be one of in_person, video, phone")


def _allowed_transition(current_status: str, target_status: str) -> bool:
    return target_status in ALLOWED_APPOINTMENT_TRANSITIONS.get(current_status, set())


def _transition_appointment(*, appt: Appointment, target_status: str, actor_id: uuid.UUID) -> tuple[str, datetime]:
    if not _allowed_transition(appt.status, target_status):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Illegal lifecycle transition.")
    now = datetime.now(timezone.utc)
    appt.status = target_status
    appt.updated_at = now
    if target_status == "confirmed":
        appt.confirmed_at = now
    elif target_status == "declined":
        appt.declined_at = now
    elif target_status == "cancelled":
        appt.cancelled_at = now
        appt.cancelled_by = actor_id
    elif target_status == "completed":
        appt.completed_at = now
    return target_status, now


async def _write_appointment_timeline_event(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    family_id: uuid.UUID,
    appt: Appointment,
    action: str,
    resulting_status: str,
    title: str,
    description: str,
) -> None:
    await write_timeline_event(
        db=db,
        tenant_id=tenant_id,
        family_id=family_id,
        event_type=action,
        event_category="appointment",
        title=title,
        occurred_at=appt.scheduled_start_at,
        source_module="appointments",
        event_key=f"appointment:{appt.id}:{action}:{resulting_status}:{appt.scheduled_start_at.isoformat()}",
        student_id=appt.student_id,
        description=description,
        priority="informational",
        action_url="/parent/appointments",
        visibility="family",
    )


async def _attempt_appointment_notification_after_commit(
    *,
    db: AsyncSession,
    appt: Appointment,
    actor_id: uuid.UUID,
    action: str,
) -> None:
    try:
        async with db.begin():
            parent_user = await db.get(User, appt.parent_id)
            teacher_row = await db.execute(
                select(Teacher)
                .join(User, User.id == Teacher.user_id)
                .where(Teacher.id == appt.teacher_id, Teacher.tenant_id == appt.tenant_id)
            )
            teacher_profile = teacher_row.scalar_one_or_none()
            teacher_user = teacher_profile.user if teacher_profile is not None else None
            if parent_user is not None:
                await send_to_user(
                    parent_user,
                    f"Appointment update: {action} for {appt.scheduled_start_at.isoformat()}.",
                    "appointment",
                    db,
                    student_id=appt.student_id,
                    email_subject="[SchoolOS] Appointment Update",
                )
            if teacher_user is not None and teacher_user.id != actor_id:
                await send_to_user(
                    teacher_user,
                    f"Appointment update: {action} for {appt.scheduled_start_at.isoformat()}.",
                    "appointment",
                    db,
                    student_id=appt.student_id,
                    email_subject="[SchoolOS] Appointment Update",
                )
    except Exception:
        await db.rollback()
        logger.warning("appointment notification failed")


async def _validate_teacher_subject_option(
    *,
    db: AsyncSession,
    tenant: Tenant,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    subject_id: uuid.UUID | None,
    timetable_entry_id: uuid.UUID | None,
    effective_date,
) -> tuple[Student, Class, Teacher, TimetableEntry | None]:
    student_result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(Student.id == student_id, Student.tenant_id == tenant.id, Class.tenant_id == tenant.id)
    )
    row = student_result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    student, klass = row

    teacher_result = await db.execute(
        select(Teacher)
        .join(User, User.id == Teacher.user_id)
        .where(Teacher.id == teacher_id, Teacher.tenant_id == tenant.id, User.is_active.is_(True))
    )
    teacher = teacher_result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher not found.")

    homeroom_scope = await teacher_has_homeroom_scope(
        db=db,
        tenant_id=tenant.id,
        teacher_id=teacher.id,
        klass=klass,
        effective_date=effective_date,
    )

    if homeroom_scope.authorized:
        if subject_id is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Homeroom appointments must have subject_id null.")
        if timetable_entry_id is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Homeroom appointments must have timetable_entry_id null.")
        return student, klass, teacher, None

    if timetable_entry_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="timetable_entry_id is required for timetable-based appointments.")

    if subject_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unauthorized teacher-subject combination.")

    subject_scope = await teacher_has_subject_scope(
        db=db,
        tenant_id=tenant.id,
        teacher_id=teacher.id,
        klass=klass,
        subject_id=subject_id,
        timetable_entry_id=timetable_entry_id,
        effective_date=effective_date,
    )
    if not subject_scope.authorized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unauthorized teacher-subject combination.")

    entry_result = await db.execute(
        select(TimetableEntry).where(
            TimetableEntry.id == timetable_entry_id,
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.class_id == klass.id,
            TimetableEntry.academic_year == klass.academic_year,
            TimetableEntry.teacher_id == teacher.id,
            TimetableEntry.subject_id == subject_id,
            TimetableEntry.is_active.is_(True),
        )
    )
    entry = entry_result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unauthorized teacher-subject combination.")

    return student, klass, teacher, entry


async def _permission_for_parent(
    *,
    db: AsyncSession,
    tenant: Tenant,
    parent: User,
    student_id: uuid.UUID,
) -> tuple[Student, Family, StudentParent]:
    sp = await validate_parent_student_access(student_id=student_id, parent=parent, tenant=tenant, db=db)
    result = await db.execute(
        select(Student, Family)
        .join(Class, Class.id == Student.class_id)
        .join(StudentParent, StudentParent.student_id == Student.id)
        .join(Family, Family.id == StudentParent.family_id)
        .where(Student.id == student_id, Student.tenant_id == tenant.id, Family.tenant_id == tenant.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    student, family = row
    return student, family, sp


@router.get("/parent/students/{student_id}/eligible-appointment-teachers", summary="List eligible appointment teacher options")
async def get_eligible_appointment_teachers(
    student_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    student, family, _ = await _permission_for_parent(db=db, tenant=tenant, parent=parent, student_id=student_id)
    result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(Student.id == student_id, Student.tenant_id == tenant.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    _, klass = row

    options: list[dict] = []
    seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()

    if klass.class_teacher_id:
        teacher_result = await db.execute(select(Teacher, User).join(User, User.id == Teacher.user_id).where(Teacher.id == klass.class_teacher_id, Teacher.tenant_id == tenant.id))
        teacher_row = teacher_result.first()
        if teacher_row:
            teacher, user = teacher_row
            key = (teacher.id, None)
            if key not in seen:
                seen.add(key)
                options.append({"teacher_id": str(teacher.id), "teacher_name": user.name, "subject_id": None, "subject_name": None, "timetable_entry_id": None, "mode": "homeroom"})

    timetable_result = await db.execute(
        select(TimetableEntry, Subject, Teacher, User)
        .join(Subject, Subject.id == TimetableEntry.subject_id)
        .join(Teacher, Teacher.id == TimetableEntry.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.class_id == klass.id,
            TimetableEntry.academic_year == klass.academic_year,
            TimetableEntry.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(TimetableEntry.teacher_id, Subject.name)
    )
    for entry, subject, teacher, user in timetable_result.all():
        key = (teacher.id, entry.subject_id)
        if key in seen:
            continue
        seen.add(key)
        options.append({
            "teacher_id": str(teacher.id),
            "teacher_name": user.name,
            "subject_id": str(subject.id),
            "subject_name": subject.name,
            "timetable_entry_id": str(entry.id),
            "mode": "timetable",
        })

    return {"student_id": str(student.id), "options": options}


@router.post("/parent/appointments", summary="Create a parent appointment")
async def create_parent_appointment(
    body: AppointmentCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    student, family, _ = await _permission_for_parent(db=db, tenant=tenant, parent=parent, student_id=body.student_id)
    _, _, teacher, entry = await _validate_teacher_subject_option(
        db=db,
        tenant=tenant,
        student_id=body.student_id,
        teacher_id=body.teacher_id,
        subject_id=body.subject_id,
        timetable_entry_id=body.timetable_entry_id,
        effective_date=body.requested_start_at.date(),
    )

    appt = Appointment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        family_id=family.id,
        student_id=student.id,
        parent_id=parent.id,
        teacher_id=teacher.id,
        subject_id=body.subject_id,
        timetable_entry_id=entry.id if entry else None,
        status="requested",
        requested_start_at=body.requested_start_at,
        scheduled_start_at=body.requested_start_at,
        duration_minutes=body.duration_minutes,
        timezone=body.timezone,
        meeting_mode=body.meeting_mode,
        location_or_link=body.location_or_link,
        reason=body.reason,
        parent_notes=body.parent_notes,
        staff_notes=None,
    )
    db.add(appt)
    await db.flush()

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="appointment.requested",
        entity_type="Appointment",
        entity_id=appt.id,
        actor_id=parent.id,
        details={"status": "requested", "scheduled_start_at": appt.scheduled_start_at.isoformat()},
    )
    await write_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=family.id,
        event_type="appointment.requested",
        event_category="appointment",
        title="Appointment requested",
        occurred_at=appt.requested_start_at,
        source_module="appointments",
        source_reference=str(appt.id),
        student_id=student.id,
        description="A parent has requested a meeting with a teacher.",
        priority="informational",
        action_url="/parent/appointments",
        visibility="family",
    )
    await db.commit()
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=parent.id, action="requested")
    await db.refresh(appt)
    return {"appointment": {"id": str(appt.id), "status": appt.status, "scheduled_start_at": appt.scheduled_start_at.isoformat()}}


@router.get("/parent/appointments", summary="List parent appointments")
async def list_parent_appointments(
    status: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    family = await resolve_family(parent=parent, tenant=tenant, db=db)
    stmt = (
        select(Appointment)
        .where(
            Appointment.tenant_id == tenant.id,
            Appointment.family_id == family.id,
        )
    )
    if status:
        stmt = stmt.where(Appointment.status == status)
    if date_from:
        stmt = stmt.where(Appointment.requested_start_at >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.requested_start_at <= date_to)
    stmt = stmt.order_by(Appointment.requested_start_at.desc(), Appointment.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"items": [{"id": str(r.id), "status": r.status, "scheduled_start_at": r.scheduled_start_at.isoformat()} for r in rows], "page": page, "page_size": page_size}


@router.get("/parent/appointments/{appointment_id}", summary="Get parent appointment")
async def get_parent_appointment(
    appointment_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    family = await resolve_family(parent=parent, tenant=tenant, db=db)
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.tenant_id == tenant.id,
            Appointment.family_id == family.id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    return {"id": str(appt.id), "status": appt.status, "scheduled_start_at": appt.scheduled_start_at.isoformat()}


@router.post("/parent/appointments/{appointment_id}/cancel", summary="Cancel parent appointment")
async def cancel_parent_appointment(
    appointment_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    family = await resolve_family(parent=parent, tenant=tenant, db=db)
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.family_id == family.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    _, _ = _transition_appointment(appt=appt, target_status="cancelled", actor_id=parent.id)
    await log_action(db=db, tenant_id=tenant.id, action="appointment.cancelled", entity_type="Appointment", entity_id=appt.id, actor_id=parent.id, details={"status": "cancelled", "scheduled_start_at": appt.scheduled_start_at.isoformat()})
    await _write_appointment_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=family.id,
        appt=appt,
        action="appointment.cancelled",
        resulting_status="cancelled",
        title="Appointment cancelled",
        description="The parent has cancelled this appointment.",
    )
    await db.commit()
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=parent.id, action="cancelled")
    return {"status": appt.status}


@router.post("/parent/appointments/{appointment_id}/reschedule", summary="Reschedule parent appointment")
async def reschedule_parent_appointment(
    appointment_id: uuid.UUID,
    body: ParentAppointmentRescheduleRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        family = await resolve_family(parent=parent, tenant=tenant, db=db)
        result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.family_id == family.id))
        appt = result.scalar_one_or_none()
        if not appt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
        teacher_lock = await _lock_teacher_profile(db, tenant_id=tenant.id, teacher_id=appt.teacher_id)
        if teacher_lock is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
        if appt.status not in {"requested", "confirmed"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rescheduling terminal appointments is not allowed.")
        if body.scheduled_start_at is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scheduled_start_at is required")
        _validate_future_appointment_datetime(body.scheduled_start_at)
        if body.duration_minutes is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="duration_minutes is required")
        _validate_duration_minutes(body.duration_minutes)
        if body.timezone is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="timezone is required")
        _validate_iana_timezone(body.timezone)
        if body.meeting_mode is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="meeting_mode is required")
        _validate_meeting_mode(body.meeting_mode)

        proposed_start = body.scheduled_start_at
        proposed_end = proposed_start + timedelta(minutes=body.duration_minutes)
        if appt.status == "confirmed":
            overlap = await _find_confirmed_overlap(
                db=db,
                tenant_id=tenant.id,
                teacher_id=appt.teacher_id,
                proposed_start=proposed_start,
                proposed_end=proposed_end,
                current_appointment_id=appointment_id,
            )
            if overlap is not None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Appointment overlaps with an existing confirmed slot.")

        appt.scheduled_start_at = proposed_start
        appt.duration_minutes = body.duration_minutes
        appt.timezone = body.timezone
        appt.meeting_mode = body.meeting_mode
        appt.updated_at = datetime.now(timezone.utc)
        await log_action(db=db, tenant_id=tenant.id, action="appointment.rescheduled", entity_type="Appointment", entity_id=appt.id, actor_id=parent.id, details={"status": appt.status, "scheduled_start_at": appt.scheduled_start_at.isoformat()})
        await _write_appointment_timeline_event(
            db=db,
            tenant_id=tenant.id,
            family_id=family.id,
            appt=appt,
            action="appointment.rescheduled",
            resulting_status=appt.status,
            title="Appointment rescheduled",
            description="The parent has rescheduled this appointment.",
        )
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=parent.id, action="rescheduled")
    return {"status": appt.status}


@router.get("/teacher/appointments", summary="List teacher appointments")
async def list_teacher_appointments(
    appointment_status: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    stmt = select(Appointment).where(Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id)
    if appointment_status:
        stmt = stmt.where(Appointment.status == appointment_status)
    if date_from:
        stmt = stmt.where(Appointment.requested_start_at >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.requested_start_at <= date_to)
    stmt = stmt.order_by(Appointment.requested_start_at.desc(), Appointment.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"items": [{"id": str(r.id), "status": r.status, "scheduled_start_at": r.scheduled_start_at.isoformat()} for r in rows], "page": page, "page_size": page_size}


@router.get("/teacher/appointments/{appointment_id}", summary="Get teacher appointment")
async def get_teacher_appointment(
    appointment_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    return {
        "id": str(appt.id),
        "status": appt.status,
        "scheduled_start_at": appt.scheduled_start_at.isoformat(),
        "duration_minutes": appt.duration_minutes,
        "timezone": appt.timezone,
        "meeting_mode": appt.meeting_mode,
        "location_or_link": appt.location_or_link,
        "parent_notes": appt.parent_notes,
        "staff_notes": appt.staff_notes,
    }


@router.post("/teacher/appointments/{appointment_id}/confirm", summary="Confirm appointment")
async def confirm_teacher_appointment(appointment_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), teacher_user: User = Depends(resolve_authenticated_teacher), db: AsyncSession = Depends(get_db)):
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
        if not teacher_profile:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
        locked_teacher = await _lock_teacher_profile(db, tenant_id=tenant.id, teacher_id=teacher_profile.id)
        if locked_teacher is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

        result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
        appt = result.scalar_one_or_none()
        if not appt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")

        if appt.status != "requested":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Illegal lifecycle transition.")

        proposed_start = appt.scheduled_start_at
        proposed_end = proposed_start + timedelta(minutes=appt.duration_minutes)
        overlap = await _find_confirmed_overlap(
            db=db,
            tenant_id=tenant.id,
            teacher_id=teacher_profile.id,
            proposed_start=proposed_start,
            proposed_end=proposed_end,
            current_appointment_id=appointment_id,
        )
        if overlap is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Appointment overlaps with an existing confirmed slot.")

        _transition_appointment(appt=appt, target_status="confirmed", actor_id=teacher_user.id)
        await log_action(db=db, tenant_id=tenant.id, action="appointment.confirmed", entity_type="Appointment", entity_id=appt.id, actor_id=teacher_user.id, details={"status": "confirmed", "scheduled_start_at": appt.scheduled_start_at.isoformat()})
        await _write_appointment_timeline_event(
            db=db,
            tenant_id=tenant.id,
            family_id=appt.family_id,
            appt=appt,
            action="appointment.confirmed",
            resulting_status="confirmed",
            title="Appointment confirmed",
            description="The teacher has confirmed this appointment.",
        )
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=teacher_user.id, action="confirmed")
    return {"status": appt.status}


@router.post("/teacher/appointments/{appointment_id}/decline", summary="Decline appointment")
async def decline_teacher_appointment(appointment_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), teacher_user: User = Depends(resolve_authenticated_teacher), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    _transition_appointment(appt=appt, target_status="declined", actor_id=teacher_user.id)
    await log_action(db=db, tenant_id=tenant.id, action="appointment.declined", entity_type="Appointment", entity_id=appt.id, actor_id=teacher_user.id, details={"status": "declined", "scheduled_start_at": appt.scheduled_start_at.isoformat()})
    await _write_appointment_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=appt.family_id,
        appt=appt,
        action="appointment.declined",
        resulting_status="declined",
        title="Appointment declined",
        description="The teacher has declined this appointment.",
    )
    await db.commit()
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=teacher_user.id, action="declined")
    return {"status": appt.status}


@router.post("/teacher/appointments/{appointment_id}/cancel", summary="Cancel appointment")
async def cancel_teacher_appointment(appointment_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), teacher_user: User = Depends(resolve_authenticated_teacher), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    _transition_appointment(appt=appt, target_status="cancelled", actor_id=teacher_user.id)
    await log_action(db=db, tenant_id=tenant.id, action="appointment.cancelled", entity_type="Appointment", entity_id=appt.id, actor_id=teacher_user.id, details={"status": "cancelled", "scheduled_start_at": appt.scheduled_start_at.isoformat()})
    await _write_appointment_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=appt.family_id,
        appt=appt,
        action="appointment.cancelled",
        resulting_status="cancelled",
        title="Appointment cancelled",
        description="The teacher has cancelled this appointment.",
    )
    await db.commit()
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=teacher_user.id, action="cancelled")
    return {"status": appt.status}


@router.post("/teacher/appointments/{appointment_id}/complete", summary="Complete appointment")
async def complete_teacher_appointment(appointment_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), teacher_user: User = Depends(resolve_authenticated_teacher), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    _transition_appointment(appt=appt, target_status="completed", actor_id=teacher_user.id)
    await log_action(db=db, tenant_id=tenant.id, action="appointment.completed", entity_type="Appointment", entity_id=appt.id, actor_id=teacher_user.id, details={"status": "completed", "scheduled_start_at": appt.scheduled_start_at.isoformat()})
    await _write_appointment_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=appt.family_id,
        appt=appt,
        action="appointment.completed",
        resulting_status="completed",
        title="Appointment completed",
        description="The teacher has marked this appointment as completed.",
    )
    await db.commit()
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=teacher_user.id, action="completed")
    return {"status": appt.status}


@router.post("/teacher/appointments/{appointment_id}/reschedule", summary="Reschedule teacher appointment")
async def reschedule_teacher_appointment(
    appointment_id: uuid.UUID,
    body: TeacherAppointmentActionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        teacher_profile = await _resolve_teacher_profile(db, tenant.id, teacher_user)
        if not teacher_profile:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
        locked_teacher = await _lock_teacher_profile(db, tenant_id=tenant.id, teacher_id=teacher_profile.id)
        if locked_teacher is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

        result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id, Appointment.teacher_id == teacher_profile.id))
        appt = result.scalar_one_or_none()
        if not appt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
        if appt.status not in {"requested", "confirmed"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rescheduling terminal appointments is not allowed.")
        if body.scheduled_start_at is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scheduled_start_at is required")
        _validate_future_appointment_datetime(body.scheduled_start_at)
        if body.duration_minutes is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="duration_minutes is required")
        _validate_duration_minutes(body.duration_minutes)
        if body.timezone is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="timezone is required")
        _validate_iana_timezone(body.timezone)
        if body.meeting_mode is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="meeting_mode is required")
        _validate_meeting_mode(body.meeting_mode)

        proposed_start = body.scheduled_start_at
        proposed_end = proposed_start + timedelta(minutes=body.duration_minutes)
        if appt.status == "confirmed":
            overlap = await _find_confirmed_overlap(
                db=db,
                tenant_id=tenant.id,
                teacher_id=teacher_profile.id,
                proposed_start=proposed_start,
                proposed_end=proposed_end,
                current_appointment_id=appointment_id,
            )
            if overlap is not None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Appointment overlaps with an existing confirmed slot.")

        appt.scheduled_start_at = proposed_start
        appt.duration_minutes = body.duration_minutes
        appt.timezone = body.timezone
        appt.meeting_mode = body.meeting_mode
        if body.staff_notes is not None:
            appt.staff_notes = body.staff_notes
        appt.updated_at = datetime.now(timezone.utc)
        await log_action(db=db, tenant_id=tenant.id, action="appointment.rescheduled", entity_type="Appointment", entity_id=appt.id, actor_id=teacher_user.id, details={"status": appt.status, "scheduled_start_at": appt.scheduled_start_at.isoformat()})
        await _write_appointment_timeline_event(
            db=db,
            tenant_id=tenant.id,
            family_id=appt.family_id,
            appt=appt,
            action="appointment.rescheduled",
            resulting_status=appt.status,
            title="Appointment rescheduled",
            description="The teacher has rescheduled this appointment.",
        )
    await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=teacher_user.id, action="rescheduled")
    return {"status": appt.status}


@router.get("/leadership/appointments", summary="Leadership appointment visibility")
async def list_leadership_appointments(
    status: str | None = Query(default=None),
    teacher_id: uuid.UUID | None = Query(default=None),
    student_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    subject_id: uuid.UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    stmt = select(Appointment).where(Appointment.tenant_id == tenant.id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if teacher_id:
        stmt = stmt.where(Appointment.teacher_id == teacher_id)
    if student_id:
        stmt = stmt.where(Appointment.student_id == student_id)
    if subject_id:
        stmt = stmt.where(Appointment.subject_id == subject_id)
    if class_id:
        stmt = stmt.where(Appointment.student_id.in_(select(Student.id).join(Class, Class.id == Student.class_id).where(Class.id == class_id)))
    if date_from:
        stmt = stmt.where(Appointment.requested_start_at >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.requested_start_at <= date_to)
    stmt = stmt.order_by(Appointment.requested_start_at.desc(), Appointment.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"items": [{"id": str(r.id), "status": r.status, "scheduled_start_at": r.scheduled_start_at.isoformat(), "parent_notes": r.parent_notes, "staff_notes": r.staff_notes} for r in rows], "page": page, "page_size": page_size}


@router.get("/leadership/appointments/{appointment_id}", summary="Leadership appointment detail")
async def get_leadership_appointment(
    appointment_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")
    return {"id": str(appt.id), "status": appt.status, "parent_notes": appt.parent_notes, "staff_notes": appt.staff_notes}
