from __future__ import annotations

import re
import uuid
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.readiness import compute_timetable_input_readiness
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    BellSchedule,
    BellSchedulePeriod,
    Campus,
    Class,
    OperationalCalendarEvent,
    SchoolWeekConfig,
    Subject,
    Teacher,
    TeachingRoom,
    Tenant,
    Term,
    User,
    WeeklyTeachingRequirement,
)

router = APIRouter(prefix="/leadership/timetable-setup", tags=["Timetable Setup"])

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CalendarCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    event_name: str
    description: str | None = None
    start_date: date_type
    end_date: date_type
    is_all_day: bool = True
    event_type: str
    teaching_day_effect: str = "no_change"
    source_type: str = "manual"
    source_reference: str | None = None
    original_source_text: str | None = None
    allow_term_override: bool = False


class CalendarUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    event_name: str | None = None
    description: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    is_all_day: bool | None = None
    event_type: str | None = None
    teaching_day_effect: str | None = None
    source_reference: str | None = None
    original_source_text: str | None = None
    allow_term_override: bool = False


class SchoolWeekCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    name: str
    operational_weekdays: list[int]
    is_default: bool = True
    source_type: str = "manual"


class SchoolWeekUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    operational_weekdays: list[int] | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class BellScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    school_week_config_id: uuid.UUID | None = None
    name: str
    schedule_type: str = "normal"
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    is_default: bool = True
    source_type: str = "manual"


class BellScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_week_config_id: uuid.UUID | None = None
    name: str | None = None
    schedule_type: str | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class BellSchedulePeriodCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable_grade_level_id: uuid.UUID | None = None
    period_number: int
    label: str
    start_time: str
    end_time: str
    is_teaching_period: bool = True
    is_break: bool = False
    is_lunch: bool = False


class BellSchedulePeriodUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable_grade_level_id: uuid.UUID | None = None
    period_number: int | None = None
    label: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    is_teaching_period: bool | None = None
    is_break: bool | None = None
    is_lunch: bool | None = None
    is_active: bool | None = None


class RoomCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    room_code: str
    room_name: str
    room_type: str
    capacity: int = 0
    floor_or_location: str | None = None
    specialist_capabilities: list[str] = Field(default_factory=list)
    accessibility_notes: str | None = None
    source_type: str = "manual"


class RoomUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    room_code: str | None = None
    room_name: str | None = None
    room_type: str | None = None
    capacity: int | None = None
    floor_or_location: str | None = None
    specialist_capabilities: list[str] | None = None
    accessibility_notes: str | None = None
    is_active: bool | None = None


class TeachingRequirementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID
    academic_year_id: uuid.UUID
    term_id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    teacher_id: uuid.UUID | None = None
    sessions_per_week: int
    periods_per_session: int = 1
    min_daily_sessions: int = 0
    max_daily_sessions: int = 3
    double_period_mode: str = "none"
    specialist_room_type: str | None = None
    preferred_period_numbers: list[int] = Field(default_factory=list)
    forbidden_period_numbers: list[int] = Field(default_factory=list)
    has_fixed_sessions: bool = False
    fixed_session_rules: list[dict[str, Any]] = Field(default_factory=list)
    priority: int = 100
    source_type: str = "manual"


class TeachingRequirementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teacher_id: uuid.UUID | None = None
    sessions_per_week: int | None = None
    periods_per_session: int | None = None
    min_daily_sessions: int | None = None
    max_daily_sessions: int | None = None
    double_period_mode: str | None = None
    specialist_room_type: str | None = None
    preferred_period_numbers: list[int] | None = None
    forbidden_period_numbers: list[int] | None = None
    has_fixed_sessions: bool | None = None
    fixed_session_rules: list[dict[str, Any]] | None = None
    priority: int | None = None
    is_active: bool | None = None


def _ensure_actor_tenant(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _clean_required_text(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must not be blank.")
    return cleaned


def _validate_time(value: str, *, label: str) -> str:
    if not TIME_RE.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must be in HH:MM format.")
    return value


async def _resolve_term(db: AsyncSession, tenant_id: uuid.UUID, term_id: uuid.UUID) -> Term:
    term = await db.scalar(select(Term).where(Term.id == term_id, Term.tenant_id == tenant_id))
    if term is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Term not found.")
    return term


async def _resolve_academic_year(db: AsyncSession, tenant_id: uuid.UUID, academic_year_id: uuid.UUID) -> AcademicYear:
    year = await db.scalar(select(AcademicYear).where(AcademicYear.id == academic_year_id, AcademicYear.tenant_id == tenant_id))
    if year is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Academic year not found.")
    return year


async def _validate_term_bounds(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    term_id: uuid.UUID | None,
    start_date: date_type,
    end_date: date_type,
    allow_term_override: bool,
) -> None:
    if term_id is None:
        return
    term = await _resolve_term(db, tenant_id, term_id)
    if allow_term_override:
        return
    if start_date < term.start_date or end_date > term.end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Term-bound events must fall within the related term unless explicit override is provided.",
        )


async def _validate_scope_keys(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    campus_id: uuid.UUID | None,
    academic_year_id: uuid.UUID | None,
    term_id: uuid.UUID | None,
) -> None:
    if campus_id is not None:
        campus = await db.scalar(select(Campus.id).where(Campus.id == campus_id, Campus.tenant_id == tenant_id))
        if campus is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campus not found.")
    if academic_year_id is not None:
        await _resolve_academic_year(db, tenant_id, academic_year_id)
    if term_id is not None:
        term = await _resolve_term(db, tenant_id, term_id)
        if academic_year_id is not None and term.academic_year_id != academic_year_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Term does not belong to the selected academic year.")


def _calendar_payload(item: OperationalCalendarEvent) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "academic_year_id": str(item.academic_year_id) if item.academic_year_id else None,
        "term_id": str(item.term_id) if item.term_id else None,
        "event_name": item.event_name,
        "description": item.description,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "is_all_day": item.is_all_day,
        "event_type": item.event_type,
        "teaching_day_effect": item.teaching_day_effect,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "source_reference": item.source_reference,
        "original_source_text": item.original_source_text,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _bell_schedule_payload(item: BellSchedule) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "academic_year_id": str(item.academic_year_id) if item.academic_year_id else None,
        "term_id": str(item.term_id) if item.term_id else None,
        "school_week_config_id": str(item.school_week_config_id) if item.school_week_config_id else None,
        "name": item.name,
        "schedule_type": item.schedule_type,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "is_default": item.is_default,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _period_payload(item: BellSchedulePeriod) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "bell_schedule_id": str(item.bell_schedule_id),
        "applicable_grade_level_id": str(item.applicable_grade_level_id) if item.applicable_grade_level_id else None,
        "period_number": item.period_number,
        "label": item.label,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "is_teaching_period": item.is_teaching_period,
        "is_break": item.is_break,
        "is_lunch": item.is_lunch,
        "is_active": item.is_active,
    }


def _room_payload(item: TeachingRoom) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "room_code": item.room_code,
        "room_name": item.room_name,
        "room_type": item.room_type,
        "capacity": item.capacity,
        "floor_or_location": item.floor_or_location,
        "specialist_capabilities": item.specialist_capabilities,
        "accessibility_notes": item.accessibility_notes,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _requirement_payload(item: WeeklyTeachingRequirement) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "class_id": str(item.class_id),
        "subject_id": str(item.subject_id),
        "teacher_id": str(item.teacher_id) if item.teacher_id else None,
        "sessions_per_week": item.sessions_per_week,
        "periods_per_session": item.periods_per_session,
        "min_daily_sessions": item.min_daily_sessions,
        "max_daily_sessions": item.max_daily_sessions,
        "double_period_mode": item.double_period_mode,
        "specialist_room_type": item.specialist_room_type,
        "preferred_period_numbers": item.preferred_period_numbers,
        "forbidden_period_numbers": item.forbidden_period_numbers,
        "has_fixed_sessions": item.has_fixed_sessions,
        "fixed_session_rules": item.fixed_session_rules,
        "priority": item.priority,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


@router.get("/calendar", summary="List operational calendar entries")
async def list_calendar_entries(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(OperationalCalendarEvent)
            .where(OperationalCalendarEvent.tenant_id == tenant.id)
            .order_by(OperationalCalendarEvent.start_date.asc(), OperationalCalendarEvent.created_at.asc())
        )
    ).scalars().all()
    return [_calendar_payload(item) for item in rows]


@router.post("/calendar", summary="Create operational calendar entry")
async def create_calendar_entry(
    body: CalendarCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.end_date < body.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date cannot be after end_date.")

    await _validate_scope_keys(
        db=db,
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
    )
    await _validate_term_bounds(
        db=db,
        tenant_id=tenant.id,
        term_id=body.term_id,
        start_date=body.start_date,
        end_date=body.end_date,
        allow_term_override=body.allow_term_override,
    )

    duplicate = await db.scalar(
        select(OperationalCalendarEvent.id).where(
            OperationalCalendarEvent.tenant_id == tenant.id,
            OperationalCalendarEvent.campus_id == body.campus_id,
            OperationalCalendarEvent.academic_year_id == body.academic_year_id,
            OperationalCalendarEvent.term_id == body.term_id,
            OperationalCalendarEvent.event_name == body.event_name.strip(),
            OperationalCalendarEvent.start_date == body.start_date,
            OperationalCalendarEvent.end_date == body.end_date,
            OperationalCalendarEvent.event_type == body.event_type,
            OperationalCalendarEvent.is_active.is_(True),
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active calendar entry already exists.")

    is_manual = body.source_type == "manual"
    item = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        event_name=_clean_required_text(body.event_name, label="event_name"),
        description=body.description,
        start_date=body.start_date,
        end_date=body.end_date,
        is_all_day=body.is_all_day,
        event_type=body.event_type,
        teaching_day_effect=body.teaching_day_effect,
        source_type=body.source_type,
        review_status="approved" if is_manual else "pending_review",
        source_reference=body.source_reference,
        original_source_text=body.original_source_text,
        created_by_user_id=actor.id,
        reviewed_by_user_id=actor.id if is_manual else None,
        approved_by_user_id=actor.id if is_manual else None,
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar.created",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"review_status": item.review_status, "source_type": item.source_type},
    )
    await db.commit()
    await db.refresh(item)
    return _calendar_payload(item)


@router.patch("/calendar/{entry_id}", summary="Update operational calendar entry")
async def update_calendar_entry(
    entry_id: uuid.UUID,
    body: CalendarUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.id == entry_id, OperationalCalendarEvent.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar entry not found.")

    next_start = body.start_date if body.start_date is not None else item.start_date
    next_end = body.end_date if body.end_date is not None else item.end_date
    next_term_id = body.term_id if body.term_id is not None else item.term_id
    next_campus_id = body.campus_id if body.campus_id is not None else item.campus_id
    next_year_id = body.academic_year_id if body.academic_year_id is not None else item.academic_year_id

    if next_end < next_start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date cannot be after end_date.")

    await _validate_scope_keys(db=db, tenant_id=tenant.id, campus_id=next_campus_id, academic_year_id=next_year_id, term_id=next_term_id)
    await _validate_term_bounds(
        db=db,
        tenant_id=tenant.id,
        term_id=next_term_id,
        start_date=next_start,
        end_date=next_end,
        allow_term_override=body.allow_term_override,
    )

    if body.event_name is not None:
        item.event_name = _clean_required_text(body.event_name, label="event_name")
    if body.description is not None:
        item.description = body.description
    if body.start_date is not None:
        item.start_date = body.start_date
    if body.end_date is not None:
        item.end_date = body.end_date
    if body.is_all_day is not None:
        item.is_all_day = body.is_all_day
    if body.event_type is not None:
        item.event_type = body.event_type
    if body.teaching_day_effect is not None:
        item.teaching_day_effect = body.teaching_day_effect
    if body.source_reference is not None:
        item.source_reference = body.source_reference
    if body.original_source_text is not None:
        item.original_source_text = body.original_source_text
    if body.campus_id is not None:
        item.campus_id = body.campus_id
    if body.academic_year_id is not None:
        item.academic_year_id = body.academic_year_id
    if body.term_id is not None:
        item.term_id = body.term_id

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar.updated",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"review_status": item.review_status, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _calendar_payload(item)


@router.post("/calendar/{entry_id}/approve", summary="Approve pending calendar entry")
async def approve_calendar_entry(
    entry_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.id == entry_id, OperationalCalendarEvent.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar entry not found.")
    if item.review_status != "pending_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending_review entries can be approved.")

    item.review_status = "approved"
    item.reviewed_by_user_id = actor.id
    item.approved_by_user_id = actor.id
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar.approved",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"from_status": "pending_review", "to_status": "approved"},
    )
    await db.commit()
    await db.refresh(item)
    return _calendar_payload(item)


@router.post("/calendar/{entry_id}/reject", summary="Reject pending calendar entry")
async def reject_calendar_entry(
    entry_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.id == entry_id, OperationalCalendarEvent.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar entry not found.")
    if item.review_status != "pending_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending_review entries can be rejected.")

    item.review_status = "rejected"
    item.reviewed_by_user_id = actor.id
    item.approved_by_user_id = None
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar.rejected",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"from_status": "pending_review", "to_status": "rejected"},
    )
    await db.commit()
    await db.refresh(item)
    return _calendar_payload(item)


@router.post("/calendar/{entry_id}/deactivate", summary="Deactivate calendar entry")
async def deactivate_calendar_entry(
    entry_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.id == entry_id, OperationalCalendarEvent.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar entry not found.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar.deactivated",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _calendar_payload(item)


@router.get("/school-week", summary="List school week configurations")
async def list_school_week_configs(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (await db.execute(select(SchoolWeekConfig).where(SchoolWeekConfig.tenant_id == tenant.id).order_by(SchoolWeekConfig.created_at.desc()))).scalars().all()
    return [
        {
            "id": str(item.id),
            "tenant_id": str(item.tenant_id),
            "campus_id": str(item.campus_id) if item.campus_id else None,
            "academic_year_id": str(item.academic_year_id) if item.academic_year_id else None,
            "term_id": str(item.term_id) if item.term_id else None,
            "name": item.name,
            "operational_weekdays": item.operational_weekdays,
            "is_default": item.is_default,
            "source_type": item.source_type,
            "review_status": item.review_status,
            "is_active": item.is_active,
        }
        for item in rows
    ]


@router.post("/school-week", summary="Create school week configuration")
async def create_school_week_config(
    body: SchoolWeekCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    if not body.operational_weekdays:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operational_weekdays must not be empty.")
    if any(day < 0 or day > 6 for day in body.operational_weekdays):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operational_weekdays must be between 0 and 6.")

    await _validate_scope_keys(db=db, tenant_id=tenant.id, campus_id=body.campus_id, academic_year_id=body.academic_year_id, term_id=body.term_id)
    item = SchoolWeekConfig(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        name=_clean_required_text(body.name, label="name"),
        operational_weekdays=sorted(set(body.operational_weekdays)),
        is_default=body.is_default,
        source_type=body.source_type,
        review_status="approved" if body.source_type == "manual" else "pending_review",
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.school_week.created",
        entity_type="SchoolWeekConfig",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_default": item.is_default, "review_status": item.review_status},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active default school week already exists for this scope.")
    await db.refresh(item)
    return {
        "id": str(item.id),
        "name": item.name,
        "operational_weekdays": item.operational_weekdays,
        "is_default": item.is_default,
        "is_active": item.is_active,
        "review_status": item.review_status,
    }


@router.patch("/school-week/{config_id}", summary="Update school week configuration")
async def update_school_week_config(
    config_id: uuid.UUID,
    body: SchoolWeekUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(SchoolWeekConfig).where(SchoolWeekConfig.id == config_id, SchoolWeekConfig.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School week configuration not found.")
    if body.name is not None:
        item.name = _clean_required_text(body.name, label="name")
    if body.operational_weekdays is not None:
        if not body.operational_weekdays:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operational_weekdays must not be empty.")
        if any(day < 0 or day > 6 for day in body.operational_weekdays):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operational_weekdays must be between 0 and 6.")
        item.operational_weekdays = sorted(set(body.operational_weekdays))
    if body.is_default is not None:
        item.is_default = body.is_default
    if body.is_active is not None:
        item.is_active = body.is_active
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.school_week.updated",
        entity_type="SchoolWeekConfig",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_default": item.is_default, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active default school week already exists for this scope.")
    await db.refresh(item)
    return {
        "id": str(item.id),
        "name": item.name,
        "operational_weekdays": item.operational_weekdays,
        "is_default": item.is_default,
        "is_active": item.is_active,
    }


@router.get("/bell-schedules", summary="List bell schedules")
async def list_bell_schedules(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (await db.execute(select(BellSchedule).where(BellSchedule.tenant_id == tenant.id).order_by(BellSchedule.created_at.desc()))).scalars().all()
    return [_bell_schedule_payload(item) for item in rows]


@router.post("/bell-schedules", summary="Create bell schedule")
async def create_bell_schedule(
    body: BellScheduleCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.effective_start_date and body.effective_end_date and body.effective_end_date < body.effective_start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="effective_start_date cannot be after effective_end_date.")
    await _validate_scope_keys(db=db, tenant_id=tenant.id, campus_id=body.campus_id, academic_year_id=body.academic_year_id, term_id=body.term_id)
    if body.school_week_config_id is not None:
        exists = await db.scalar(
            select(SchoolWeekConfig.id).where(
                SchoolWeekConfig.id == body.school_week_config_id,
                SchoolWeekConfig.tenant_id == tenant.id,
            )
        )
        if exists is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="school_week_config_id not found.")

    item = BellSchedule(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        school_week_config_id=body.school_week_config_id,
        name=_clean_required_text(body.name, label="name"),
        schedule_type=body.schedule_type,
        effective_start_date=body.effective_start_date,
        effective_end_date=body.effective_end_date,
        is_default=body.is_default,
        source_type=body.source_type,
        review_status="approved" if body.source_type == "manual" else "pending_review",
        is_active=True,
        created_by_user_id=actor.id,
        approved_by_user_id=actor.id if body.source_type == "manual" else None,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_schedule.created",
        entity_type="BellSchedule",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_default": item.is_default, "review_status": item.review_status},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active default bell schedule already exists for this scope.")
    await db.refresh(item)
    return _bell_schedule_payload(item)


@router.patch("/bell-schedules/{schedule_id}", summary="Update bell schedule")
async def update_bell_schedule(
    schedule_id: uuid.UUID,
    body: BellScheduleUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(BellSchedule).where(BellSchedule.id == schedule_id, BellSchedule.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule not found.")

    next_start = body.effective_start_date if body.effective_start_date is not None else item.effective_start_date
    next_end = body.effective_end_date if body.effective_end_date is not None else item.effective_end_date
    if next_start and next_end and next_end < next_start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="effective_start_date cannot be after effective_end_date.")

    if body.school_week_config_id is not None:
        exists = await db.scalar(
            select(SchoolWeekConfig.id).where(
                SchoolWeekConfig.id == body.school_week_config_id,
                SchoolWeekConfig.tenant_id == tenant.id,
            )
        )
        if exists is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="school_week_config_id not found.")
        item.school_week_config_id = body.school_week_config_id
    if body.name is not None:
        item.name = _clean_required_text(body.name, label="name")
    if body.schedule_type is not None:
        item.schedule_type = body.schedule_type
    if body.effective_start_date is not None:
        item.effective_start_date = body.effective_start_date
    if body.effective_end_date is not None:
        item.effective_end_date = body.effective_end_date
    if body.is_default is not None:
        item.is_default = body.is_default
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_schedule.updated",
        entity_type="BellSchedule",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_default": item.is_default, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active default bell schedule already exists for this scope.")
    await db.refresh(item)
    return _bell_schedule_payload(item)


@router.post("/bell-schedules/{schedule_id}/deactivate", summary="Deactivate bell schedule")
async def deactivate_bell_schedule(
    schedule_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(BellSchedule).where(BellSchedule.id == schedule_id, BellSchedule.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule not found.")
    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_schedule.deactivated",
        entity_type="BellSchedule",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _bell_schedule_payload(item)


@router.get("/bell-schedules/{schedule_id}/periods", summary="List periods in bell schedule")
async def list_schedule_periods(
    schedule_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    schedule = await db.scalar(select(BellSchedule.id).where(BellSchedule.id == schedule_id, BellSchedule.tenant_id == tenant.id))
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule not found.")
    rows = (
        await db.execute(
            select(BellSchedulePeriod)
            .where(BellSchedulePeriod.bell_schedule_id == schedule_id, BellSchedulePeriod.tenant_id == tenant.id)
            .order_by(BellSchedulePeriod.period_number.asc())
        )
    ).scalars().all()
    return [_period_payload(item) for item in rows]


async def _validate_period_overlap(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    bell_schedule_id: uuid.UUID,
    period_id: uuid.UUID | None,
    start_time: str,
    end_time: str,
    is_active: bool,
) -> None:
    if not is_active:
        return
    rows = (
        await db.execute(
            select(BellSchedulePeriod)
            .where(
                BellSchedulePeriod.tenant_id == tenant_id,
                BellSchedulePeriod.bell_schedule_id == bell_schedule_id,
                BellSchedulePeriod.is_active.is_(True),
            )
            .order_by(BellSchedulePeriod.start_time.asc())
        )
    ).scalars().all()
    for row in rows:
        if period_id is not None and row.id == period_id:
            continue
        # overlap if [start,end) intersects existing interval
        if start_time < row.end_time and end_time > row.start_time:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active periods cannot overlap in the same bell schedule.")


@router.post("/bell-schedules/{schedule_id}/periods", summary="Create bell schedule period")
async def create_schedule_period(
    schedule_id: uuid.UUID,
    body: BellSchedulePeriodCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    schedule = await db.scalar(select(BellSchedule).where(BellSchedule.id == schedule_id, BellSchedule.tenant_id == tenant.id))
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule not found.")

    start_time = _validate_time(body.start_time, label="start_time")
    end_time = _validate_time(body.end_time, label="end_time")
    if start_time >= end_time:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period start_time must be before end_time.")

    duplicate = await db.scalar(
        select(BellSchedulePeriod.id).where(
            BellSchedulePeriod.tenant_id == tenant.id,
            BellSchedulePeriod.bell_schedule_id == schedule_id,
            BellSchedulePeriod.period_number == body.period_number,
            BellSchedulePeriod.is_active.is_(True),
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active period_number in this schedule.")

    is_teaching_period = body.is_teaching_period
    if body.is_break or body.is_lunch:
        is_teaching_period = False

    await _validate_period_overlap(
        db=db,
        tenant_id=tenant.id,
        bell_schedule_id=schedule_id,
        period_id=None,
        start_time=start_time,
        end_time=end_time,
        is_active=True,
    )

    item = BellSchedulePeriod(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        bell_schedule_id=schedule_id,
        applicable_grade_level_id=body.applicable_grade_level_id,
        period_number=body.period_number,
        label=_clean_required_text(body.label, label="label"),
        start_time=start_time,
        end_time=end_time,
        is_teaching_period=is_teaching_period,
        is_break=body.is_break,
        is_lunch=body.is_lunch,
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_period.created",
        entity_type="BellSchedulePeriod",
        entity_id=item.id,
        actor_id=actor.id,
        details={"period_number": item.period_number, "is_teaching_period": item.is_teaching_period},
    )
    await db.commit()
    await db.refresh(item)
    return _period_payload(item)


@router.patch("/bell-schedules/{schedule_id}/periods/{period_id}", summary="Update bell schedule period")
async def update_schedule_period(
    schedule_id: uuid.UUID,
    period_id: uuid.UUID,
    body: BellSchedulePeriodUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(BellSchedulePeriod).where(
            BellSchedulePeriod.id == period_id,
            BellSchedulePeriod.bell_schedule_id == schedule_id,
            BellSchedulePeriod.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule period not found.")

    next_start = body.start_time if body.start_time is not None else item.start_time
    next_end = body.end_time if body.end_time is not None else item.end_time
    next_active = body.is_active if body.is_active is not None else item.is_active

    next_start = _validate_time(next_start, label="start_time")
    next_end = _validate_time(next_end, label="end_time")
    if next_start >= next_end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period start_time must be before end_time.")

    if body.period_number is not None and body.period_number != item.period_number and next_active:
        duplicate = await db.scalar(
            select(BellSchedulePeriod.id).where(
                BellSchedulePeriod.tenant_id == tenant.id,
                BellSchedulePeriod.bell_schedule_id == schedule_id,
                BellSchedulePeriod.period_number == body.period_number,
                BellSchedulePeriod.is_active.is_(True),
                BellSchedulePeriod.id != period_id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active period_number in this schedule.")

    await _validate_period_overlap(
        db=db,
        tenant_id=tenant.id,
        bell_schedule_id=schedule_id,
        period_id=period_id,
        start_time=next_start,
        end_time=next_end,
        is_active=next_active,
    )

    if body.applicable_grade_level_id is not None:
        item.applicable_grade_level_id = body.applicable_grade_level_id
    if body.period_number is not None:
        item.period_number = body.period_number
    if body.label is not None:
        item.label = _clean_required_text(body.label, label="label")
    item.start_time = next_start
    item.end_time = next_end

    next_is_break = body.is_break if body.is_break is not None else item.is_break
    next_is_lunch = body.is_lunch if body.is_lunch is not None else item.is_lunch
    next_is_teaching = body.is_teaching_period if body.is_teaching_period is not None else item.is_teaching_period
    if next_is_break or next_is_lunch:
        next_is_teaching = False

    item.is_break = next_is_break
    item.is_lunch = next_is_lunch
    item.is_teaching_period = next_is_teaching
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_period.updated",
        entity_type="BellSchedulePeriod",
        entity_id=item.id,
        actor_id=actor.id,
        details={"period_number": item.period_number, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _period_payload(item)


@router.post("/bell-schedules/{schedule_id}/periods/{period_id}/deactivate", summary="Deactivate bell schedule period")
async def deactivate_schedule_period(
    schedule_id: uuid.UUID,
    period_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(
        select(BellSchedulePeriod).where(
            BellSchedulePeriod.id == period_id,
            BellSchedulePeriod.bell_schedule_id == schedule_id,
            BellSchedulePeriod.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule period not found.")
    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.bell_period.deactivated",
        entity_type="BellSchedulePeriod",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _period_payload(item)


@router.get("/rooms", summary="List rooms")
async def list_rooms(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (await db.execute(select(TeachingRoom).where(TeachingRoom.tenant_id == tenant.id).order_by(TeachingRoom.room_code.asc()))).scalars().all()
    return [_room_payload(item) for item in rows]


@router.post("/rooms", summary="Create room")
async def create_room(
    body: RoomCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    if body.capacity < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="capacity cannot be negative.")
    if body.campus_id is not None:
        campus = await db.scalar(select(Campus.id).where(Campus.id == body.campus_id, Campus.tenant_id == tenant.id))
        if campus is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campus not found.")

    item = TeachingRoom(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        room_code=_clean_required_text(body.room_code, label="room_code").upper(),
        room_name=_clean_required_text(body.room_name, label="room_name"),
        room_type=body.room_type,
        capacity=body.capacity,
        floor_or_location=body.floor_or_location,
        specialist_capabilities=body.specialist_capabilities,
        accessibility_notes=body.accessibility_notes,
        source_type=body.source_type,
        review_status="approved" if body.source_type == "manual" else "pending_review",
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.room.created",
        entity_type="TeachingRoom",
        entity_id=item.id,
        actor_id=actor.id,
        details={"room_code": item.room_code, "room_type": item.room_type},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room code already exists in this scope.")
    await db.refresh(item)
    return _room_payload(item)


@router.patch("/rooms/{room_id}", summary="Update room")
async def update_room(
    room_id: uuid.UUID,
    body: RoomUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(TeachingRoom).where(TeachingRoom.id == room_id, TeachingRoom.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found.")

    if body.capacity is not None and body.capacity < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="capacity cannot be negative.")
    if body.campus_id is not None:
        campus = await db.scalar(select(Campus.id).where(Campus.id == body.campus_id, Campus.tenant_id == tenant.id))
        if campus is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campus not found.")
        item.campus_id = body.campus_id
    if body.room_code is not None:
        item.room_code = _clean_required_text(body.room_code, label="room_code").upper()
    if body.room_name is not None:
        item.room_name = _clean_required_text(body.room_name, label="room_name")
    if body.room_type is not None:
        item.room_type = body.room_type
    if body.capacity is not None:
        item.capacity = body.capacity
    if body.floor_or_location is not None:
        item.floor_or_location = body.floor_or_location
    if body.specialist_capabilities is not None:
        item.specialist_capabilities = body.specialist_capabilities
    if body.accessibility_notes is not None:
        item.accessibility_notes = body.accessibility_notes
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.room.updated",
        entity_type="TeachingRoom",
        entity_id=item.id,
        actor_id=actor.id,
        details={"room_code": item.room_code, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room code already exists in this scope.")
    await db.refresh(item)
    return _room_payload(item)


@router.post("/rooms/{room_id}/deactivate", summary="Deactivate room")
async def deactivate_room(
    room_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(TeachingRoom).where(TeachingRoom.id == room_id, TeachingRoom.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.room.deactivated",
        entity_type="TeachingRoom",
        entity_id=item.id,
        actor_id=actor.id,
        details={"room_code": item.room_code, "is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _room_payload(item)


async def _validate_requirement_scope(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    body: TeachingRequirementCreateRequest,
) -> tuple[Class, Subject]:
    await _validate_scope_keys(
        db=db,
        tenant_id=tenant_id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
    )
    klass = await db.scalar(select(Class).where(Class.id == body.class_id, Class.tenant_id == tenant_id))
    if klass is None or not klass.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class not found or inactive.")
    subject = await db.scalar(select(Subject).where(Subject.id == body.subject_id, Subject.tenant_id == tenant_id))
    if subject is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject not found.")
    if klass.campus_id != body.campus_id or klass.academic_year_id != body.academic_year_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class scope does not match campus/year.")
    if body.teacher_id is not None:
        teacher = await db.scalar(select(Teacher).where(Teacher.id == body.teacher_id, Teacher.tenant_id == tenant_id))
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher not found.")
    if body.specialist_room_type is not None:
        room = await db.scalar(
            select(TeachingRoom.id).where(
                TeachingRoom.tenant_id == tenant_id,
                TeachingRoom.room_type == body.specialist_room_type,
                TeachingRoom.is_active.is_(True),
            )
        )
        if room is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="specialist_room_type has no active room.")
    return klass, subject


@router.get("/teaching-requirements", summary="List weekly teaching requirements")
async def list_teaching_requirements(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(WeeklyTeachingRequirement)
            .where(WeeklyTeachingRequirement.tenant_id == tenant.id)
            .order_by(WeeklyTeachingRequirement.priority.asc(), WeeklyTeachingRequirement.created_at.asc())
        )
    ).scalars().all()
    return [_requirement_payload(item) for item in rows]


@router.post("/teaching-requirements", summary="Create weekly teaching requirement")
async def create_teaching_requirement(
    body: TeachingRequirementCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.sessions_per_week <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sessions_per_week must be positive.")
    if body.periods_per_session <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="periods_per_session must be positive.")
    if body.max_daily_sessions < body.min_daily_sessions:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="max_daily_sessions must be >= min_daily_sessions.")

    await _validate_requirement_scope(db=db, tenant_id=tenant.id, body=body)

    duplicate = await db.scalar(
        select(WeeklyTeachingRequirement.id).where(
            WeeklyTeachingRequirement.tenant_id == tenant.id,
            WeeklyTeachingRequirement.campus_id == body.campus_id,
            WeeklyTeachingRequirement.academic_year_id == body.academic_year_id,
            WeeklyTeachingRequirement.term_id == body.term_id,
            WeeklyTeachingRequirement.class_id == body.class_id,
            WeeklyTeachingRequirement.subject_id == body.subject_id,
            WeeklyTeachingRequirement.is_active.is_(True),
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active requirement for class/subject/term.")

    if body.has_fixed_sessions and body.fixed_session_rules:
        existing_fixed = await db.scalar(
            select(func.count(WeeklyTeachingRequirement.id)).where(
                WeeklyTeachingRequirement.tenant_id == tenant.id,
                WeeklyTeachingRequirement.class_id == body.class_id,
                WeeklyTeachingRequirement.term_id == body.term_id,
                WeeklyTeachingRequirement.has_fixed_sessions.is_(True),
                WeeklyTeachingRequirement.is_active.is_(True),
            )
        )
        if int(existing_fixed or 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Fixed session constraints already exist for this class and term; update existing requirement instead.",
            )

    item = WeeklyTeachingRequirement(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        class_id=body.class_id,
        subject_id=body.subject_id,
        teacher_id=body.teacher_id,
        sessions_per_week=body.sessions_per_week,
        periods_per_session=body.periods_per_session,
        min_daily_sessions=body.min_daily_sessions,
        max_daily_sessions=body.max_daily_sessions,
        double_period_mode=body.double_period_mode,
        specialist_room_type=body.specialist_room_type,
        preferred_period_numbers=body.preferred_period_numbers,
        forbidden_period_numbers=body.forbidden_period_numbers,
        has_fixed_sessions=body.has_fixed_sessions,
        fixed_session_rules=body.fixed_session_rules,
        priority=body.priority,
        source_type=body.source_type,
        review_status="approved" if body.source_type == "manual" else "pending_review",
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.requirement.created",
        entity_type="WeeklyTeachingRequirement",
        entity_id=item.id,
        actor_id=actor.id,
        details={"sessions_per_week": item.sessions_per_week, "review_status": item.review_status},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active requirement for class/subject/term.")
    await db.refresh(item)
    return _requirement_payload(item)


@router.patch("/teaching-requirements/{requirement_id}", summary="Update weekly teaching requirement")
async def update_teaching_requirement(
    requirement_id: uuid.UUID,
    body: TeachingRequirementUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(
        select(WeeklyTeachingRequirement).where(
            WeeklyTeachingRequirement.id == requirement_id,
            WeeklyTeachingRequirement.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly teaching requirement not found.")

    if body.teacher_id is not None:
        teacher = await db.scalar(select(Teacher.id).where(Teacher.id == body.teacher_id, Teacher.tenant_id == tenant.id))
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher not found.")
        item.teacher_id = body.teacher_id
    if body.sessions_per_week is not None:
        if body.sessions_per_week <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sessions_per_week must be positive.")
        item.sessions_per_week = body.sessions_per_week
    if body.periods_per_session is not None:
        if body.periods_per_session <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="periods_per_session must be positive.")
        item.periods_per_session = body.periods_per_session
    if body.min_daily_sessions is not None:
        if body.min_daily_sessions < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="min_daily_sessions must be >= 0.")
        item.min_daily_sessions = body.min_daily_sessions
    if body.max_daily_sessions is not None:
        item.max_daily_sessions = body.max_daily_sessions
    if item.max_daily_sessions < item.min_daily_sessions:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="max_daily_sessions must be >= min_daily_sessions.")
    if body.double_period_mode is not None:
        item.double_period_mode = body.double_period_mode
    if body.specialist_room_type is not None:
        if body.specialist_room_type:
            room = await db.scalar(
                select(TeachingRoom.id).where(
                    TeachingRoom.tenant_id == tenant.id,
                    TeachingRoom.room_type == body.specialist_room_type,
                    TeachingRoom.is_active.is_(True),
                )
            )
            if room is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="specialist_room_type has no active room.")
        item.specialist_room_type = body.specialist_room_type
    if body.preferred_period_numbers is not None:
        item.preferred_period_numbers = body.preferred_period_numbers
    if body.forbidden_period_numbers is not None:
        item.forbidden_period_numbers = body.forbidden_period_numbers
    if body.has_fixed_sessions is not None:
        item.has_fixed_sessions = body.has_fixed_sessions
    if body.fixed_session_rules is not None:
        item.fixed_session_rules = body.fixed_session_rules
    if body.priority is not None:
        if body.priority <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="priority must be positive.")
        item.priority = body.priority
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.requirement.updated",
        entity_type="WeeklyTeachingRequirement",
        entity_id=item.id,
        actor_id=actor.id,
        details={"sessions_per_week": item.sessions_per_week, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active requirement for class/subject/term.")
    await db.refresh(item)
    return _requirement_payload(item)


@router.post("/teaching-requirements/{requirement_id}/deactivate", summary="Deactivate weekly teaching requirement")
async def deactivate_teaching_requirement(
    requirement_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(WeeklyTeachingRequirement).where(WeeklyTeachingRequirement.id == requirement_id, WeeklyTeachingRequirement.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly teaching requirement not found.")
    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.requirement.deactivated",
        entity_type="WeeklyTeachingRequirement",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _requirement_payload(item)


@router.get("/readiness", summary="Get timetable-input readiness summary")
async def get_timetable_readiness_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await compute_timetable_input_readiness(db, tenant.id)
    return {
        "checked_at": payload["checked_at"],
        "blocker_count": payload["blocker_count"],
        "warning_count": payload["warning_count"],
        "information_count": payload["information_count"],
        "is_generation_ready": payload["is_generation_ready"],
    }


@router.get("/readiness/checks", summary="Get detailed timetable-input readiness checks")
async def get_timetable_readiness_checks(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await compute_timetable_input_readiness(db, tenant.id)
