"""Resolve dated operational coverage needs caused by a confirmed absence."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.db.models import (
    AcademicYear,
    DailySession,
    DutyAssignment,
    OperationalAssignmentRequest,
    OperationalSchoolDay,
    SchoolWeekConfig,
    TeacherAbsence,
    Timetable,
    User,
)


ACTIVE_REQUEST_STATUSES = frozenset(
    {"pending", "evaluated", "pending_approval", "approved", "no_eligible_candidate"}
)


class AbsenceImpactError(Exception):
    """Controlled, HTTP-independent errors for absence impact resolution."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class AbsenceImpactResult:
    absence_id: uuid.UUID
    teacher_id: uuid.UUID
    teaching_requests_created: int
    duty_requests_created: int
    existing_requests: int
    total_affected_items: int
    created_request_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    existing_request_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


def _period_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate.startswith("p"):
        candidate = candidate[1:]
    if ":p" in candidate and candidate.startswith("d"):
        candidate = candidate.rsplit(":p", 1)[1]
    try:
        number = int(candidate)
    except ValueError:
        return None
    return number if number > 0 else None


def _normalized_period_numbers(selected_periods: list[object]) -> set[int]:
    numbers: set[int] = set()
    for value in selected_periods:
        number = _period_number(value)
        if number is None:
            raise AbsenceImpactError("absence_selected_periods_uninterpretable")
        numbers.add(number)
    return numbers


def _dates_between(start: date_type, end: date_type) -> list[date_type]:
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    ]


async def resolve_absence_impact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    absence_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> AbsenceImpactResult:
    """Create the minimal coverage requests for one confirmed absence.

    Selected periods apply to teaching sessions only. Duty slots have no
    absence-time identifiers, so duty coverage is conservatively limited to
    whole-day absences until that timing information exists.
    """
    absence = await db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.id == absence_id,
            TeacherAbsence.tenant_id == tenant_id,
        )
    )
    if absence is None:
        raise AbsenceImpactError("absence_not_found")
    if absence.status != "confirmed":
        raise AbsenceImpactError("absence_not_confirmed")

    if actor_user_id is not None:
        actor = await db.scalar(
            select(User).where(User.id == actor_user_id, User.tenant_id == tenant_id)
        )
        if actor is None:
            raise AbsenceImpactError("actor_not_found")

    dates = _dates_between(absence.start_date, absence.end_date)

    sessions_result = await db.execute(
        select(DailySession)
        .join(
            OperationalSchoolDay,
            OperationalSchoolDay.id == DailySession.operational_school_day_id,
        )
        .where(
            DailySession.tenant_id == tenant_id,
            DailySession.teacher_id == str(absence.teacher_id),
            DailySession.school_date.in_(dates),
            OperationalSchoolDay.tenant_id == tenant_id,
            OperationalSchoolDay.is_active.is_(True),
            OperationalSchoolDay.is_teaching_day.is_(True),
        )
        .order_by(DailySession.school_date, DailySession.id)
    )
    sessions = sessions_result.scalars().all()
    if absence.scope_type == "selected_periods":
        selected_period_numbers = _normalized_period_numbers(
            list(absence.selected_periods or [])
        )
        sessions = [
            session
            for session in sessions
            if session.period_number in selected_period_numbers
        ]

    duty_dates: set[date_type] = set()
    duty_day_indexes: dict[date_type, int] = {}
    duty_context: dict[date_type, set[str]] = {}
    if absence.scope_type == "whole_day":
        school_week = await db.scalar(
            select(SchoolWeekConfig).where(
                SchoolWeekConfig.tenant_id == tenant_id,
                SchoolWeekConfig.is_active.is_(True),
                SchoolWeekConfig.is_default.is_(True),
            )
        )
        if school_week is None:
            raise AbsenceImpactError("school_week_config_required")
        operational_weekdays = list(school_week.operational_weekdays or [])
        school_days_result = await db.execute(
            select(OperationalSchoolDay, Timetable, AcademicYear)
            .join(Timetable, Timetable.id == OperationalSchoolDay.timetable_id)
            .join(AcademicYear, AcademicYear.id == Timetable.academic_year_id)
            .where(
                OperationalSchoolDay.tenant_id == tenant_id,
                Timetable.tenant_id == tenant_id,
                AcademicYear.tenant_id == tenant_id,
                OperationalSchoolDay.school_date.in_(dates),
                OperationalSchoolDay.is_active.is_(True),
                OperationalSchoolDay.is_teaching_day.is_(True),
            )
        )
        for school_day, _timetable, academic_year in school_days_result.all():
            school_date = school_day.school_date
            try:
                day_index = operational_weekdays.index(school_date.weekday())
            except ValueError:
                continue
            duty_dates.add(school_date)
            duty_day_indexes[school_date] = day_index
            duty_context.setdefault(school_date, set()).add(academic_year.name)

    duty_result = await db.execute(
        select(DutyAssignment)
        .where(
            DutyAssignment.tenant_id == tenant_id,
            DutyAssignment.teacher_id == absence.teacher_id,
            DutyAssignment.day_of_week.in_(list(duty_day_indexes.values())),
            DutyAssignment.academic_year.in_(
                sorted({name for names in duty_context.values() for name in names}) or ["__none__"]
            ),
        )
        .order_by(DutyAssignment.day_of_week, DutyAssignment.id)
    ) if duty_dates else None
    duties = duty_result.scalars().all() if duty_result is not None else []
    duty_targets = [
        (duty, school_date)
        for duty in duties
        for school_date in sorted(duty_dates)
        if duty.academic_year in duty_context.get(school_date, set())
        and duty.day_of_week == duty_day_indexes[school_date]
    ]

    existing_result = await db.execute(
        select(OperationalAssignmentRequest).where(
            OperationalAssignmentRequest.tenant_id == tenant_id,
            OperationalAssignmentRequest.teacher_absence_id == absence.id,
            OperationalAssignmentRequest.status.in_(ACTIVE_REQUEST_STATUSES),
        )
    )
    existing = [
        request
        for request in existing_result.scalars().all()
        if request.status in ACTIVE_REQUEST_STATUSES
    ]
    existing_keys = {
        (request.assignment_type, request.school_date, request.daily_session_id, request.duty_assignment_id)
        for request in existing
    }

    created: list[OperationalAssignmentRequest] = []
    for session in sessions:
        key = ("teaching_substitution", session.school_date, session.id, None)
        if key not in existing_keys:
            created.append(
                OperationalAssignmentRequest(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    assignment_type=key[0],
                    school_date=session.school_date,
                    teacher_absence_id=absence.id,
                    original_teacher_id=absence.teacher_id,
                    daily_session_id=session.id,
                    status="pending",
                    created_by_user_id=actor_user_id,
                )
            )
            existing_keys.add(key)
    for duty, duty_date in duty_targets:
        key = ("duty_reassignment", duty_date, None, duty.id)
        if key not in existing_keys:
            created.append(
                OperationalAssignmentRequest(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    assignment_type=key[0],
                    school_date=duty_date,
                    teacher_absence_id=absence.id,
                    original_teacher_id=absence.teacher_id,
                    duty_assignment_id=duty.id,
                    status="pending",
                    created_by_user_id=actor_user_id,
                )
            )
            existing_keys.add(key)

    for request in created:
        db.add(request)
        await log_action(
            db=db,
            tenant_id=tenant_id,
            action="absence_impact_request_created",
            entity_type="OperationalAssignmentRequest",
            entity_id=request.id,
            actor_id=actor_user_id,
            details={
                "absence_id": str(absence.id),
                "assignment_type": request.assignment_type,
                "school_date": request.school_date.isoformat(),
            },
        )
    await db.flush()
    await db.commit()

    existing_ids = tuple(request.id for request in existing)
    created_ids = tuple(request.id for request in created)
    return AbsenceImpactResult(
        absence_id=absence.id,
        teacher_id=absence.teacher_id,
        teaching_requests_created=sum(
            request.assignment_type == "teaching_substitution" for request in created
        ),
        duty_requests_created=sum(
            request.assignment_type == "duty_reassignment" for request in created
        ),
        existing_requests=len(existing),
        total_affected_items=len(sessions) + len(duties),
        created_request_ids=created_ids,
        existing_request_ids=existing_ids,
    )