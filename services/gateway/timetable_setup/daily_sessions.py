"""Phase 10D - Daily Sessions Materialization Service.

Converts "what does the published weekly timetable say?" into
"what is actually scheduled to happen on this specific school date?"

Combines:
  effective published timetable version (resolved by date, not by caller choice)
  + Phase 10A living calendar (holiday/non-teaching overrides)
  + effective bell schedule/profile (resolved by date)
  -> OperationalSchoolDay
  -> DailySession records

IMMUTABILITY GUARANTEE
----------------------
CASE 1 - day does not exist: create OSD and sessions. status="created".
CASE 2 - day exists, same fingerprint: return unchanged. status="already_materialized".
CASE 3 - day exists, different fingerprint: raise school_day_stale. NO mutations.

PARALLEL STRUCTURE
------------------
All parallel structure is derived from canonical parallel_block_id /
parallel_child_id fields. No subject-name heuristics are used.

BELL PROFILES
-------------
Date-specific bell schedules (e.g. short, exam) take priority over the
default bell schedule. Clock-time changes do NOT require timetable regeneration.

UNAVAILABLE PERIODS
-------------------
If the effective bell profile does not contain a logical period required by
an assignment: session_status="cancelled", override_reason="logical_period_unavailable".
Such sessions have NULL clock times and must not be attendance-eligible.

MULTI-PERIOD SESSIONS
---------------------
periods_per_session > 1 produces ONE DailySession.
start_time = first occupied period start_time.
end_time   = last occupied period end_time.
If any required period in the span is absent from the bell profile, the
session is cancelled (logical_period_unavailable).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.timetable_versions import resolve_effective_version
from shared.db.models import (
    BellSchedule,
    BellSchedulePeriod,
    DailySession,
    OperationalCalendarEvent,
    OperationalSchoolDay,
    SchoolWeekConfig,
    Timetable,
    TimetableVersion,
    TimetableVersionAssignment,
)


class DailySessionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class MaterializationOutcome:
    """Result of a materialize_operational_day call.

    status values:
      "created"              - new OSD + DailySessions written.
      "already_materialized" - existing snapshot returned unchanged.
    """
    osd: OperationalSchoolDay
    session_count: int
    status: str  # "created" | "already_materialized"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O - unit-testable without a database)
# ---------------------------------------------------------------------------


def compute_source_fingerprint(
    timetable_id: uuid.UUID,
    timetable_version_id: uuid.UUID,
    day_key: str | None,
    bell_schedule_id: uuid.UUID | None,
    calendar_override_event_id: uuid.UUID | None,
) -> str:
    """Deterministic fingerprint of all canonical inputs that define an OSD.

    A fingerprint change signals the day is stale:
    - timetable_id: the operational scope
    - timetable_version_id: the effective published assignment source
    - day_key: weekday column resolved from operational_weekdays
    - bell_schedule_id: the effective bell profile providing clock times
    - calendar_override_event_id: the canonical calendar event that caused
      a non-teaching override (None if the day is a normal operational day)

    The fingerprint NEVER includes timestamps, actors, or runtime values.
    Equivalent canonical source always produces an equivalent fingerprint.
    """
    raw = (
        f"{timetable_id}:{timetable_version_id}:"
        f"{day_key or ''}:{bell_schedule_id or ''}:{calendar_override_event_id or ''}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_class_facing_session_key(
    school_date: date_type,
    class_id: str,
    period_key: str,
    parallel_block_id: str | None,
) -> str:
    """Deterministic class-facing slot identity (SHA-256 hex, 64 chars).

    All parallel children belonging to the same block, date, and period share
    the same class_facing_session_key. No subject-name inspection is performed.
    Attendance must use this key to avoid creating duplicate class registers
    for parallel teacher-specific children.
    """
    raw = f"{school_date.isoformat()}|{class_id}|{period_key}|{parallel_block_id or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def resolve_day_key(school_date: date_type, operational_weekdays: list[int]) -> str | None:
    """Map a calendar date to its timetable day_key ('d0', 'd1', ...).

    Returns None when the date falls on a non-operational weekday.
    """
    weekday = school_date.weekday()  # 0=Monday, 6=Sunday
    try:
        idx = operational_weekdays.index(weekday)
    except ValueError:
        return None
    return f"d{idx}"


def period_number_from_period_key(period_key: str) -> int | None:
    """Extract the period number from 'd0:p3' -> 3. None for malformed keys."""
    try:
        num = int(period_key.split(":")[1][1:])
        return num if num > 0 else None
    except (IndexError, ValueError, AttributeError):
        return None


def resolve_session_times(
    primary_period_key: str,
    occupied_period_keys: list[str],
    bell_periods: dict[int, BellSchedulePeriod],
) -> tuple[str | None, str | None, uuid.UUID | None, bool]:
    """Resolve clock times for a session spanning one or more logical periods.

    Returns (start_time, end_time, first_bell_period_id, all_periods_available).

    Multi-period: start_time = first period start, end_time = last period end.
    If any required period is absent: all_periods_available=False, times=None.
    """
    # Collect all occupied period numbers, falling back to primary key alone
    keys = occupied_period_keys if occupied_period_keys else [primary_period_key]
    numbers = sorted(filter(None, (period_number_from_period_key(k) for k in keys)))
    if not numbers:
        return None, None, None, False

    first_p = numbers[0]
    last_p = numbers[-1]
    first_bp = bell_periods.get(first_p)
    last_bp = bell_periods.get(last_p)

    if first_bp is None or last_bp is None:
        return None, None, None, False

    return first_bp.start_time, last_bp.end_time, first_bp.id, True


def session_to_dict(session: DailySession) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "timetable_version_assignment_id": (
            str(session.timetable_version_assignment_id)
            if session.timetable_version_assignment_id else None
        ),
        "school_date": session.school_date.isoformat(),
        "class_id": session.class_id,
        "subject_id": session.subject_id,
        "teacher_id": session.teacher_id,
        "room_id": session.room_id,
        "period_number": session.period_number,
        "period_start_time": session.period_start_time,
        "period_end_time": session.period_end_time,
        "periods_span": session.periods_span,
        "parallel_block_id": session.parallel_block_id,
        "parallel_child_id": session.parallel_child_id,
        "session_key": session.session_key,
        "class_facing_session_key": session.class_facing_session_key,
        "session_status": session.session_status,
        "override_reason": session.override_reason,
    }


def operational_day_to_dict(osd: OperationalSchoolDay, *, session_count: int) -> dict[str, Any]:
    return {
        "id": str(osd.id),
        "timetable_id": str(osd.timetable_id),
        "timetable_version_id": str(osd.timetable_version_id),
        "campus_id": str(osd.campus_id) if osd.campus_id else None,
        "school_date": osd.school_date.isoformat(),
        "day_of_week": osd.day_of_week,
        "timetable_day_key": osd.timetable_day_key,
        "bell_schedule_id": str(osd.bell_schedule_id) if osd.bell_schedule_id else None,
        "is_teaching_day": osd.is_teaching_day,
        "non_teaching_reason": osd.non_teaching_reason,
        "materialization_status": osd.materialization_status,
        "materialized_at": osd.materialized_at.isoformat() if osd.materialized_at else None,
        "source_fingerprint": osd.source_fingerprint,
        "session_count": session_count,
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def _resolve_calendar_override(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    school_date: date_type,
) -> OperationalCalendarEvent | None:
    """Return the highest-priority published calendar event that overrides this
    date to non_teaching_day using the Phase 10A living calendar.
    """
    return await db.scalar(
        select(OperationalCalendarEvent).where(
            OperationalCalendarEvent.tenant_id == tenant_id,
            OperationalCalendarEvent.is_active.is_(True),
            OperationalCalendarEvent.lifecycle_status == "published",
            OperationalCalendarEvent.start_date <= school_date,
            OperationalCalendarEvent.end_date >= school_date,
            OperationalCalendarEvent.teaching_day_effect == "non_teaching_day",
        ).limit(1)
    )


async def _resolve_bell_schedule_for_date(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID | None,
    school_date: date_type,
) -> BellSchedule | None:
    """Return the most date-specific approved active bell schedule for the date.

    Date-specific schedules (with effective_start_date covering the date) take
    priority over the generic default schedule. This supports short-day, exam,
    and special profiles without requiring timetable regeneration.
    """
    q = select(BellSchedule).where(
        BellSchedule.tenant_id == tenant_id,
        BellSchedule.is_active.is_(True),
        BellSchedule.review_status == "approved",
        or_(
            # Date-specific: effective date range covers the target date
            (
                BellSchedule.effective_start_date.is_not(None)
                & (BellSchedule.effective_start_date <= school_date)
                & or_(
                    BellSchedule.effective_end_date.is_(None),
                    BellSchedule.effective_end_date >= school_date,
                )
            ),
            # Generic default fallback
            BellSchedule.is_default.is_(True),
        ),
    )
    if academic_year_id is not None:
        q = q.where(BellSchedule.academic_year_id == academic_year_id)

    # Date-specific (non-null effective_start_date) sorts before generic default
    q = q.order_by(BellSchedule.effective_start_date.desc().nullslast()).limit(1)
    return await db.scalar(q)


async def _load_bell_periods(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bell_schedule_id: uuid.UUID,
) -> dict[int, BellSchedulePeriod]:
    rows = (
        await db.execute(
            select(BellSchedulePeriod).where(
                BellSchedulePeriod.tenant_id == tenant_id,
                BellSchedulePeriod.bell_schedule_id == bell_schedule_id,
                BellSchedulePeriod.is_active.is_(True),
                BellSchedulePeriod.is_teaching_period.is_(True),
            )
        )
    ).scalars().all()
    return {bp.period_number: bp for bp in rows}


async def _count_sessions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operational_school_day_id: uuid.UUID,
) -> int:
    result = await db.scalar(
        select(func.count()).select_from(DailySession).where(
            DailySession.tenant_id == tenant_id,
            DailySession.operational_school_day_id == operational_school_day_id,
            DailySession.is_active.is_(True),
        )
    )
    return result or 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def materialize_operational_day(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    timetable_id: uuid.UUID,
    school_date: date_type,
) -> MaterializationOutcome:
    """Materialize an OperationalSchoolDay and its DailySession records.

    The effective published timetable version is selected automatically by date
    using the existing Phase 10C effective-version resolver. The caller cannot
    choose an arbitrary published version.

    IMMUTABILITY CONTRACT
    ---------------------
    - First call: creates OSD + sessions. status="created".
    - Same canonical inputs (same fingerprint): returns existing. status="already_materialized".
    - Changed canonical inputs (different fingerprint): raises school_day_stale. NO writes.
    """
    # 1. Load the Timetable (scope: tenant + academic_year + term + campus).
    timetable = await db.scalar(
        select(Timetable).where(
            Timetable.id == timetable_id,
            Timetable.tenant_id == tenant_id,
        )
    )
    if timetable is None:
        raise DailySessionError("timetable_not_found", "Timetable not found.", 404)

    # 2. Resolve the effective published timetable version for this date.
    #    Reuses Phase 10C effective-date semantics. Caller cannot choose a version.
    version: TimetableVersion | None = await resolve_effective_version(
        db, tenant_id=tenant_id, timetable_id=timetable_id, on_date=school_date
    )
    if version is None:
        raise DailySessionError(
            "no_effective_timetable",
            f"No published timetable version is effective for {school_date.isoformat()} "
            f"on timetable {timetable_id}.",
            409,
        )

    # 3. Resolve the timetable day_key from the school date.
    swc = await db.scalar(
        select(SchoolWeekConfig).where(
            SchoolWeekConfig.tenant_id == tenant_id,
            SchoolWeekConfig.is_active.is_(True),
            SchoolWeekConfig.is_default.is_(True),
        )
    )
    operational_weekdays: list[int] = list(swc.operational_weekdays) if swc else [0, 1, 2, 3, 4]
    day_key = resolve_day_key(school_date, operational_weekdays)
    is_teaching_day = day_key is not None
    non_teaching_reason: str | None = None if is_teaching_day else "not_operational_weekday"
    calendar_override_event_id: uuid.UUID | None = None

    # 4. Check Phase 10A living calendar for a non-teaching override on this date.
    #    A Monday explicitly marked no-school by the calendar is NOT a teaching day
    #    even though Monday is normally operational.
    if is_teaching_day:
        cal_override = await _resolve_calendar_override(
            db, tenant_id=tenant_id, school_date=school_date
        )
        if cal_override is not None:
            is_teaching_day = False
            non_teaching_reason = "calendar_non_teaching"
            calendar_override_event_id = cal_override.id

    # 5. Resolve the effective bell schedule for this date.
    #    Date-specific profiles (short, exam, special) take priority over the default.
    bell_schedule = await _resolve_bell_schedule_for_date(
        db,
        tenant_id=tenant_id,
        academic_year_id=timetable.academic_year_id,
        school_date=school_date,
    )
    bell_schedule_id: uuid.UUID | None = bell_schedule.id if bell_schedule else None

    # 6. Compute source fingerprint from all canonical inputs.
    current_fingerprint = compute_source_fingerprint(
        timetable_id, version.id, day_key, bell_schedule_id, calendar_override_event_id
    )

    # 7. Check for an existing OperationalSchoolDay (keyed by timetable scope + date).
    existing_osd = await db.scalar(
        select(OperationalSchoolDay).where(
            OperationalSchoolDay.tenant_id == tenant_id,
            OperationalSchoolDay.timetable_id == timetable_id,
            OperationalSchoolDay.school_date == school_date,
        )
    )

    if existing_osd is not None:
        stored_fp = existing_osd.source_fingerprint
        if stored_fp is not None and stored_fp == current_fingerprint:
            # CASE 2: Identical canonical inputs - return existing snapshot unchanged.
            session_count = await _count_sessions(
                db, tenant_id=tenant_id, operational_school_day_id=existing_osd.id
            )
            return MaterializationOutcome(
                osd=existing_osd, session_count=session_count, status="already_materialized"
            )

        # CASE 3: Fingerprint absent or changed - refuse to mutate historical rows.
        raise DailySessionError(
            "school_day_stale",
            f"Operational day for {school_date} was materialized from a different "
            f"source snapshot (stored={stored_fp!r}, current={current_fingerprint!r}). "
            "Controlled reconciliation must be performed explicitly.",
            status_code=409,
        )

    # CASE 1: First-time materialization.
    now = datetime.now(UTC)
    osd = OperationalSchoolDay(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        timetable_id=timetable_id,
        timetable_version_id=version.id,
        campus_id=timetable.campus_id,
        school_date=school_date,
        day_of_week=school_date.weekday(),
        timetable_day_key=day_key if is_teaching_day else None,
        bell_schedule_id=bell_schedule_id,
        is_teaching_day=is_teaching_day,
        non_teaching_reason=non_teaching_reason,
        calendar_override_event_id=calendar_override_event_id,
        materialization_status="complete",
        materialized_at=now,
        source_fingerprint=current_fingerprint,
        is_active=True,
    )
    db.add(osd)
    await db.flush()

    session_count = 0

    if is_teaching_day and day_key is not None:
        # 8. Load bell periods for clock-time enrichment.
        #    Structurally absent periods get NULL times (never fabricated).
        bell_periods: dict[int, BellSchedulePeriod] = {}
        if bell_schedule_id is not None:
            bell_periods = await _load_bell_periods(
                db, tenant_id=tenant_id, bell_schedule_id=bell_schedule_id
            )

        # 9. Load all assignments for this timetable day (tenant-scoped).
        assignments = (
            await db.execute(
                select(TimetableVersionAssignment).where(
                    TimetableVersionAssignment.tenant_id == tenant_id,
                    TimetableVersionAssignment.timetable_version_id == version.id,
                    TimetableVersionAssignment.day_key == day_key,
                )
            )
        ).scalars().all()

        # 10. Create one DailySession per assignment.
        #     Multi-period: ONE session, start=first period, end=last period.
        #     Parallel: block/child IDs passed through unchanged (no subject heuristics).
        #     Malformed period_key: skip the assignment.
        #     Missing bell period: session_status="cancelled", override_reason="logical_period_unavailable".
        for assignment in assignments:
            period_number = period_number_from_period_key(assignment.period_key)
            if period_number is None:
                continue  # Skip malformed period_key

            occupied_keys = list(assignment.occupied_period_keys_json or [])
            class_facing_key = compute_class_facing_session_key(
                school_date, assignment.class_id, assignment.period_key, assignment.parallel_block_id
            )

            start_time, end_time, bell_period_id, all_available = resolve_session_times(
                assignment.period_key, occupied_keys, bell_periods
            )

            if all_available:
                s_status = "scheduled"
                o_reason = None
            else:
                # Logical period not in effective bell profile.
                # Do NOT fabricate clock time. Mark as unavailable.
                s_status = "cancelled"
                o_reason = "logical_period_unavailable"
                start_time = None
                end_time = None
                bell_period_id = None

            session = DailySession(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                operational_school_day_id=osd.id,
                timetable_version_assignment_id=assignment.id,
                school_date=school_date,
                class_id=assignment.class_id,
                subject_id=assignment.subject_id,
                teacher_id=assignment.teacher_id,
                room_id=assignment.room_id,
                bell_period_id=bell_period_id,
                period_number=period_number,
                period_start_time=start_time,
                period_end_time=end_time,
                periods_span=assignment.periods_per_session,
                parallel_block_id=assignment.parallel_block_id,
                parallel_child_id=assignment.parallel_child_id,
                session_key=assignment.assignment_key,
                class_facing_session_key=class_facing_key,
                session_status=s_status,
                override_reason=o_reason,
                is_active=True,
            )
            db.add(session)
            session_count += 1

    await db.commit()
    return MaterializationOutcome(osd=osd, session_count=session_count, status="created")


async def load_operational_day_with_sessions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    timetable_id: uuid.UUID,
    school_date: date_type,
) -> tuple[OperationalSchoolDay, list[DailySession]] | None:
    """Load an already-materialized OperationalSchoolDay with its sessions.

    Returns None when no OSD exists for the given scope.
    """
    osd = await db.scalar(
        select(OperationalSchoolDay).where(
            OperationalSchoolDay.tenant_id == tenant_id,
            OperationalSchoolDay.timetable_id == timetable_id,
            OperationalSchoolDay.school_date == school_date,
        )
    )
    if osd is None:
        return None
    sessions = (
        await db.execute(
            select(DailySession)
            .where(
                DailySession.tenant_id == tenant_id,
                DailySession.operational_school_day_id == osd.id,
                DailySession.is_active.is_(True),
            )
            .order_by(DailySession.period_number.asc(), DailySession.class_id.asc())
        )
    ).scalars().all()
    return osd, list(sessions)
