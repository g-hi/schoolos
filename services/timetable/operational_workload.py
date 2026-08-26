"""Deterministic teacher baseline workload read model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.timetable.fair_duty_planning import calculate_teacher_teaching_load
from shared.db.models import (
    BellSchedulePeriod,
    DutyAssignment,
    DutySlot,
    Teacher,
    TimetableGenerationConfiguration,
    TimetableVersion,
    TimetableVersionAssignment,
    User,
)


@dataclass(frozen=True, slots=True)
class TeacherOperationalWorkload:
    teacher_id: uuid.UUID
    teaching_period_count: int
    teaching_minutes: int | None
    recurring_duty_count: int
    recurring_duty_minutes: int
    baseline_total_minutes: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "teacher_id": self.teacher_id,
            "teaching_period_count": self.teaching_period_count,
            "teaching_minutes": self.teaching_minutes,
            "recurring_duty_count": self.recurring_duty_count,
            "recurring_duty_minutes": self.recurring_duty_minutes,
            "baseline_total_minutes": self.baseline_total_minutes,
        }


def _time_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _duration_minutes(start: str, end: str) -> int:
    return max(0, _time_minutes(end) - _time_minutes(start))


def calculate_teaching_minutes(
    assignments: Iterable[object],
    period_times: Mapping[int, tuple[str, str]],
) -> dict[str, int | None]:
    """Sum teaching durations, returning None when any period is unresolved."""
    minutes: dict[str, int | None] = {}
    for assignment in assignments:
        teacher_id = getattr(assignment, "teacher_id", None)
        if teacher_id is None:
            continue
        key = str(teacher_id)
        if minutes.get(key) is None and key in minutes:
            continue
        total = 0
        unresolved = False
        period_keys = getattr(assignment, "occupied_period_keys_json", []) or [getattr(assignment, "period_key", "")]
        for period_key in set(period_keys):
            try:
                period_number = int(str(period_key).split(":", 1)[1].removeprefix("p"))
            except (IndexError, ValueError):
                unresolved = True
                continue
            timing = period_times.get(period_number)
            if timing is None:
                unresolved = True
            else:
                total += _duration_minutes(*timing)
        if unresolved:
            minutes[key] = None
        else:
            minutes[key] = (minutes.get(key) or 0) + total
    return minutes


def calculate_duty_minutes(assignments: Iterable[object]) -> dict[str, int]:
    """Sum recurring DutySlot durations per teacher."""
    minutes: dict[str, int] = {}
    for assignment in assignments:
        teacher_id = getattr(assignment, "teacher_id", None)
        slot = getattr(assignment, "duty_slot", None)
        if teacher_id is None or slot is None:
            continue
        total = _duration_minutes(slot.start_time, slot.end_time)
        key = str(teacher_id)
        minutes[key] = minutes.get(key, 0) + total
    return minutes


def build_operational_workload_profiles(
    *,
    teachers: Sequence[object],
    timetable_assignments: Sequence[object],
    duty_assignments: Sequence[object],
    period_times: Mapping[int, tuple[str, str]],
    tenant_id: uuid.UUID,
) -> list[TeacherOperationalWorkload]:
    """Build stable profiles from already loaded tenant-scoped rows."""
    eligible_teachers = sorted(
        (
            teacher for teacher in teachers
            if getattr(teacher, "tenant_id", None) == tenant_id
            and getattr(getattr(teacher, "user", None), "is_active", True)
        ),
        key=lambda teacher: str(teacher.id),
    )
    teacher_ids = {str(teacher.id) for teacher in eligible_teachers}
    teaching_assignments = [
        assignment for assignment in timetable_assignments
        if str(getattr(assignment, "teacher_id", "")) in teacher_ids
    ]
    duty_rows = [
        assignment for assignment in duty_assignments
        if str(getattr(assignment, "teacher_id", "")) in teacher_ids
        and getattr(getattr(assignment, "duty_slot", None), "is_active", True)
    ]
    period_counts = calculate_teacher_teaching_load(teaching_assignments)
    teaching_minutes = calculate_teaching_minutes(teaching_assignments, period_times)
    duty_counts: dict[str, int] = {}
    for assignment in duty_rows:
        key = str(assignment.teacher_id)
        duty_counts[key] = duty_counts.get(key, 0) + 1
    duty_minutes = calculate_duty_minutes(duty_rows)

    return [
        TeacherOperationalWorkload(
            teacher_id=teacher.id,
            teaching_period_count=period_counts.get(str(teacher.id), 0),
            teaching_minutes=(
                teaching_minutes[str(teacher.id)]
                if str(teacher.id) in teaching_minutes
                else 0
            ),
            recurring_duty_count=duty_counts.get(str(teacher.id), 0),
            recurring_duty_minutes=duty_minutes.get(str(teacher.id), 0),
            baseline_total_minutes=(
                None
                if teaching_minutes.get(str(teacher.id)) is None
                and str(teacher.id) in teaching_minutes
                else (teaching_minutes.get(str(teacher.id), 0) or 0)
                + duty_minutes.get(str(teacher.id), 0)
            ),
        )
        for teacher in eligible_teachers
    ]


async def load_operational_workload_profiles(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    timetable_version_id: uuid.UUID,
    academic_year: str,
    teacher_ids: set[uuid.UUID] | None = None,
) -> list[TeacherOperationalWorkload]:
    """Load a published tenant timetable and recurring duty workload read-only."""
    if teacher_ids == set():
        return []

    version = await db.scalar(
        select(TimetableVersion).where(
            TimetableVersion.id == timetable_version_id,
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.lifecycle_status == "published",
        )
    )
    if version is None:
        return []

    teacher_stmt = (
        select(Teacher)
        .join(User, User.id == Teacher.user_id)
        .options(selectinload(Teacher.user))
        .where(Teacher.tenant_id == tenant_id, User.is_active.is_(True))
    )
    if teacher_ids:
        teacher_stmt = teacher_stmt.where(Teacher.id.in_(teacher_ids))
    teachers = (await db.execute(teacher_stmt)).scalars().all()
    selected_ids = {teacher.id for teacher in teachers}

    assignments = (
        await db.execute(
            select(TimetableVersionAssignment).where(
                TimetableVersionAssignment.tenant_id == tenant_id,
                TimetableVersionAssignment.timetable_version_id == timetable_version_id,
                TimetableVersionAssignment.teacher_id.in_([str(item) for item in selected_ids])
                if selected_ids else False,
            )
        )
    ).scalars().all()
    duty_rows = (
        await db.execute(
            select(DutyAssignment)
            .join(DutySlot, DutySlot.id == DutyAssignment.duty_slot_id)
            .options(selectinload(DutyAssignment.duty_slot))
            .where(
                DutyAssignment.tenant_id == tenant_id,
                DutyAssignment.academic_year == academic_year,
                DutyAssignment.teacher_id.in_(selected_ids) if selected_ids else False,
                DutySlot.tenant_id == tenant_id,
                DutySlot.is_active.is_(True),
            )
        )
    ).scalars().all()
    duty_assignments = list(duty_rows)

    period_times: dict[int, tuple[str, str]] = {}
    configuration = None
    if version.generation_configuration_id is not None:
        configuration = await db.scalar(
            select(TimetableGenerationConfiguration).where(
                TimetableGenerationConfiguration.id == version.generation_configuration_id,
                TimetableGenerationConfiguration.tenant_id == tenant_id,
            )
        )
    if configuration is not None and configuration.bell_schedule_id is not None:
        bell_periods = (
            await db.execute(
                select(BellSchedulePeriod).where(
                    BellSchedulePeriod.tenant_id == tenant_id,
                    BellSchedulePeriod.bell_schedule_id == configuration.bell_schedule_id,
                    BellSchedulePeriod.is_active.is_(True),
                    BellSchedulePeriod.is_teaching_period.is_(True),
                )
            )
        ).scalars().all()
        period_times = {
            period.period_number: (period.start_time, period.end_time)
            for period in bell_periods
        }

    return build_operational_workload_profiles(
        teachers=teachers,
        timetable_assignments=assignments,
        duty_assignments=duty_assignments,
        period_times=period_times,
        tenant_id=tenant_id,
    )
