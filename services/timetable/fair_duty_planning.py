"""Deterministic baseline duty planning from published timetable data."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.db.models import (
    DutyAssignment,
    DutySlotLocation,
    Period,
    SchoolWeekConfig,
    Teacher,
    TimetableVersion,
    TimetableVersionAssignment,
)


class DutyPlanningError(Exception):
    """Controlled, HTTP-independent errors for baseline duty planning."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class DutyPlanItem:
    """One recurring teacher/location/day assignment in a candidate plan."""

    teacher_id: uuid.UUID
    duty_slot_id: uuid.UUID
    location_id: uuid.UUID
    day_key: str
    day_of_week: int
    academic_year: str
    teaching_load: int
    duty_count_before: int
    fairness_score: tuple[int, int, int, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "teacher_id": self.teacher_id,
            "duty_slot_id": self.duty_slot_id,
            "location_id": self.location_id,
            "day_key": self.day_key,
            "day_of_week": self.day_of_week,
            "academic_year": self.academic_year,
            "teaching_load": self.teaching_load,
            "duty_count_before": self.duty_count_before,
            "fairness_score": self.fairness_score,
        }


def _period_number(period_key: str | None) -> int | None:
    try:
        value = int(str(period_key).split(":", 1)[1].removeprefix("p"))
    except (AttributeError, IndexError, ValueError):
        return None
    return value if value > 0 else None


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _overlap(start: str, end: str, other_start: str, other_end: str) -> bool:
    return _minutes(start) < _minutes(other_end) and _minutes(end) > _minutes(other_start)


def _teacher_is_active(teacher: object) -> bool:
    user = getattr(teacher, "user", None)
    return bool(getattr(teacher, "is_active", getattr(user, "is_active", True)))


def _assignment_periods(assignment: object) -> list[str]:
    occupied = list(getattr(assignment, "occupied_period_keys_json", []) or [])
    return occupied or [str(getattr(assignment, "period_key", ""))]


def calculate_teacher_teaching_load(
    assignments: Iterable[object],
) -> dict[str, int]:
    """Count occupied canonical timetable periods per teacher."""
    load: dict[str, int] = {}
    for assignment in assignments:
        teacher_id = getattr(assignment, "teacher_id", None)
        if teacher_id is None:
            continue
        valid_periods = {
            period_key
            for period_key in _assignment_periods(assignment)
            if _period_number(period_key) is not None
        }
        load[str(teacher_id)] = load.get(str(teacher_id), 0) + len(valid_periods)
    return load


def build_fair_duty_plan(
    *,
    tenant_id: uuid.UUID,
    operational_day_keys: Mapping[str, int],
    teachers: Sequence[object],
    slot_locations: Sequence[object],
    timetable_assignments: Sequence[object],
    existing_assignments: Sequence[object] = (),
    period_times: Mapping[int, tuple[str, str]] | None = None,
    academic_year: str,
) -> list[DutyPlanItem]:
    """Build a deterministic, validated in-memory recurring duty candidate."""
    period_times = period_times or {}
    active_teachers = sorted(
        (
            teacher
            for teacher in teachers
            if _teacher_is_active(teacher)
            and getattr(teacher, "tenant_id", None) == tenant_id
        ),
        key=lambda teacher: str(teacher.id),
    ) if teachers else []
    teaching_load = calculate_teacher_teaching_load(timetable_assignments)

    teaching_busy: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for assignment in timetable_assignments:
        teacher_id = getattr(assignment, "teacher_id", None)
        day_key = str(getattr(assignment, "day_key", ""))
        if teacher_id is None or day_key not in operational_day_keys:
            continue
        for period_key in _assignment_periods(assignment):
            number = _period_number(period_key)
            if number in period_times:
                teaching_busy.setdefault((str(teacher_id), day_key), []).append(period_times[number])

    existing_teacher_duties: dict[str, int] = {}
    existing_slot_busy: set[tuple[str, uuid.UUID, str]] = set()
    existing_duty_busy: dict[tuple[str, str], list[tuple[str, str]]] = {}
    existing_slot_usage: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
    weekday_to_day_key = {weekday: day_key for day_key, weekday in operational_day_keys.items()}
    for assignment in existing_assignments:
        teacher_id = getattr(assignment, "teacher_id", None)
        slot_id = getattr(assignment, "duty_slot_id", None)
        day = getattr(assignment, "day_of_week", None)
        if teacher_id is None or day is None:
            continue
        teacher_key = str(teacher_id)
        try:
            day_key = weekday_to_day_key[int(day)]
        except (KeyError, TypeError, ValueError):
            continue
        existing_teacher_duties[teacher_key] = existing_teacher_duties.get(teacher_key, 0) + 1
        location_id = getattr(assignment, "location_id", None)
        if slot_id is not None and location_id is not None:
            existing_slot_usage.add((slot_id, location_id, day_key))
            existing_slot_busy.add((teacher_key, slot_id, day_key))
        duty_slot = getattr(assignment, "duty_slot", None)
        if duty_slot is not None and getattr(duty_slot, "start_time", None) and getattr(duty_slot, "end_time", None):
            existing_duty_busy.setdefault((teacher_key, day_key), []).append(
                (duty_slot.start_time, duty_slot.end_time)
            )

    result: list[DutyPlanItem] = []
    assigned_slot_busy: set[tuple[str, uuid.UUID, str]] = set(existing_slot_busy)
    assigned_duty_busy: dict[tuple[str, str], list[tuple[str, str]]] = {}
    assigned_slot_usage: set[tuple[uuid.UUID, uuid.UUID, str]] = set(existing_slot_usage)
    assigned_counts = dict(existing_teacher_duties)

    for day_key, day_of_week in operational_day_keys.items():
        for link in sorted(
            slot_locations,
            key=lambda item: (
                str(getattr(getattr(item, "slot", None), "start_time", "")),
                str(getattr(getattr(item, "slot", None), "id", "")),
                str(getattr(getattr(item, "location", None), "id", "")),
            ),
        ):
            slot = getattr(link, "slot", None)
            location = getattr(link, "location", None)
            if (
                slot is None
                or location is None
                or getattr(slot, "tenant_id", tenant_id) != tenant_id
                or getattr(location, "tenant_id", tenant_id) != tenant_id
                or not getattr(slot, "is_active", True)
                or not getattr(location, "is_active", True)
            ):
                continue
            slot_id = slot.id
            location_id = location.id
            if (slot_id, location_id, day_key) in assigned_slot_usage:
                continue

            eligible: list[tuple[tuple[int, int, int, str], object]] = []
            for teacher in active_teachers:
                teacher_id = str(teacher.id)
                if (teacher_id, slot_id, day_key) in existing_slot_busy:
                    continue
                if any(
                    _overlap(slot.start_time, slot.end_time, start, end)
                    for start, end in existing_duty_busy.get((teacher_id, day_key), [])
                ):
                    continue
                if any(
                    _overlap(slot.start_time, slot.end_time, start, end)
                    for start, end in assigned_duty_busy.get((teacher_id, day_key), [])
                ):
                    continue
                if (teacher_id, slot_id, day_key) in assigned_slot_busy:
                    continue
                if any(
                    _overlap(slot.start_time, slot.end_time, start, end)
                    for start, end in teaching_busy.get((teacher_id, day_key), [])
                ):
                    continue
                count = assigned_counts.get(teacher_id, 0)
                load = teaching_load.get(teacher_id, 0)
                score = (load + count, count, load, teacher_id)
                eligible.append((score, teacher))

            if not eligible:
                continue
            score, teacher = min(eligible, key=lambda item: item[0])
            teacher_id = str(teacher.id)
            count_before = assigned_counts.get(teacher_id, 0)
            item = DutyPlanItem(
                teacher_id=teacher.id,
                duty_slot_id=slot_id,
                location_id=location_id,
                day_key=day_key,
                day_of_week=day_of_week,
                academic_year=academic_year,
                teaching_load=teaching_load.get(teacher_id, 0),
                duty_count_before=count_before,
                fairness_score=score,
            )
            result.append(item)
            assigned_slot_busy.add((teacher_id, slot_id, day_key))
            assigned_duty_busy.setdefault((teacher_id, day_key), []).append(
                (slot.start_time, slot.end_time)
            )
            assigned_slot_usage.add((slot_id, location_id, day_key))
            assigned_counts[teacher_id] = count_before + 1

    return result


async def plan_fair_duty_roster(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    timetable_version_id: uuid.UUID,
    academic_year: str,
) -> list[DutyPlanItem]:
    """Load tenant-scoped published inputs and return a non-persistent duty plan."""
    version = await db.scalar(
        select(TimetableVersion).where(
            TimetableVersion.id == timetable_version_id,
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.lifecycle_status == "published",
        )
    )
    if version is None:
        raise DutyPlanningError("published_timetable_not_found")

    teachers = (
        await db.execute(
            select(Teacher).options(selectinload(Teacher.user)).where(
                Teacher.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    links = (
        await db.execute(
            select(DutySlotLocation)
            .where(DutySlotLocation.tenant_id == tenant_id)
            .options(selectinload(DutySlotLocation.slot), selectinload(DutySlotLocation.location))
        )
    ).scalars().all()
    timetable_assignments = (
        await db.execute(
            select(TimetableVersionAssignment).where(
                TimetableVersionAssignment.tenant_id == tenant_id,
                TimetableVersionAssignment.timetable_version_id == timetable_version_id,
            )
        )
    ).scalars().all()
    school_week = await db.scalar(
        select(SchoolWeekConfig).where(
            SchoolWeekConfig.tenant_id == tenant_id,
            SchoolWeekConfig.is_active.is_(True),
            SchoolWeekConfig.is_default.is_(True),
        )
    )
    existing_assignments = (
        await db.execute(
            select(DutyAssignment).where(
                DutyAssignment.tenant_id == tenant_id,
                DutyAssignment.academic_year == academic_year,
            )
        )
    ).scalars().all()
    periods = (
        await db.execute(select(Period).where(Period.tenant_id == tenant_id))
    ).scalars().all()
    period_times = {period.sort_order: (period.start_time, period.end_time) for period in periods}
    if school_week is not None:
        operational_day_keys = {
            f"d{index}": weekday
            for index, weekday in enumerate(school_week.operational_weekdays or [])
        }
    else:
        raise DutyPlanningError("school_week_config_required")

    return build_fair_duty_plan(
        teachers=teachers,
        tenant_id=tenant_id,
        operational_day_keys=operational_day_keys,
        slot_locations=links,
        timetable_assignments=timetable_assignments,
        existing_assignments=existing_assignments,
        period_times=period_times,
        academic_year=academic_year,
    )
