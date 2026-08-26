from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.timetable.operational_workload import (
    TeacherOperationalWorkload,
    build_operational_workload_profiles,
    calculate_duty_minutes,
    calculate_teaching_minutes,
    load_operational_workload_profiles,
)
from services.timetable.fair_duty_planning import calculate_teacher_teaching_load


class Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class FakeDB:
    def __init__(self, *, scalar_values: list[object], execute_values: list[list[object]]) -> None:
        self.scalar = AsyncMock(side_effect=scalar_values)
        self.execute = AsyncMock(side_effect=[Result(rows) for rows in execute_values])
        self.add = AsyncMock()
        self.delete = AsyncMock()
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    def add(self, value: object) -> None:
        return None


def _teacher(tenant_id: uuid.UUID, suffix: str, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"teacher:{tenant_id}:{suffix}"),
        tenant_id=tenant_id,
        user=SimpleNamespace(is_active=active),
    )


def _teaching(teacher_id: uuid.UUID, *, periods: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        teacher_id=str(teacher_id),
        period_key=periods[0],
        occupied_period_keys_json=periods,
    )


def _duty(teacher_id: uuid.UUID, *, start: str = "10:00", end: str = "10:30") -> SimpleNamespace:
    return SimpleNamespace(
        teacher_id=teacher_id,
        duty_slot=SimpleNamespace(start_time=start, end_time=end),
    )


def _loaded_duty(teacher_id: uuid.UUID, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        teacher_id=teacher_id,
        duty_slot=SimpleNamespace(start_time="10:00", end_time="10:30", is_active=active),
    )


def test_teaching_count_and_minutes_use_published_canonical_periods() -> None:
    teacher_id = uuid.uuid4()
    assignment = _teaching(teacher_id, periods=["d0:p1", "d0:p2"])
    period_times = {1: ("08:00", "08:45"), 2: ("08:50", "09:35")}
    assert calculate_teacher_teaching_load([assignment]) == {str(teacher_id): 2}
    assert calculate_teaching_minutes([assignment], period_times) == {str(teacher_id): 90}


def test_multi_period_assignment_is_not_double_counted() -> None:
    teacher_id = uuid.uuid4()
    assignment = _teaching(teacher_id, periods=["d0:p1", "d0:p2", "d0:p2"])
    assert calculate_teacher_teaching_load([assignment]) == {str(teacher_id): 2}
    assert calculate_teaching_minutes(
        [assignment], {1: ("08:00", "08:45"), 2: ("08:50", "09:35")}
    ) == {str(teacher_id): 90}


def test_unresolved_teaching_timing_does_not_invent_duration() -> None:
    teacher_id = uuid.uuid4()
    assignment = _teaching(teacher_id, periods=["d0:p1"])
    assert calculate_teaching_minutes([assignment], {}) == {str(teacher_id): None}


def test_teacher_with_no_teaching_assignments_has_zero_teaching_minutes() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "no-teaching")
    profiles = build_operational_workload_profiles(
        teachers=[teacher],
        timetable_assignments=[],
        duty_assignments=[_duty(teacher.id)],
        period_times={},
        tenant_id=tenant_id,
    )
    assert profiles[0].teaching_period_count == 0
    assert profiles[0].teaching_minutes == 0
    assert profiles[0].baseline_total_minutes == 30


def test_partially_resolved_multi_period_teaching_is_unknown() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "partial")
    profiles = build_operational_workload_profiles(
        teachers=[teacher],
        timetable_assignments=[_teaching(teacher.id, periods=["d0:p1", "d0:p2"])],
        duty_assignments=[_duty(teacher.id)],
        period_times={1: ("08:00", "08:45")},
        tenant_id=tenant_id,
    )
    assert profiles[0].teaching_period_count == 2
    assert profiles[0].teaching_minutes is None
    assert profiles[0].recurring_duty_minutes == 30
    assert profiles[0].baseline_total_minutes is None


def test_duty_count_minutes_and_total_are_objective_facts() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "one")
    duties = [_duty(teacher.id, start="10:00", end="10:30"), _duty(teacher.id, start="12:00", end="12:45")]
    profiles = build_operational_workload_profiles(
        teachers=[teacher],
        timetable_assignments=[_teaching(teacher.id, periods=["d0:p1"])],
        duty_assignments=duties,
        period_times={1: ("08:00", "08:45")},
        tenant_id=tenant_id,
    )
    assert profiles == [TeacherOperationalWorkload(teacher.id, 1, 45, 2, 75, 120)]
    assert calculate_duty_minutes(duties) == {str(teacher.id): 75}


def test_profiles_are_tenant_scoped_active_and_stably_ordered() -> None:
    tenant_id = uuid.uuid4()
    first = _teacher(tenant_id, "first")
    second = _teacher(tenant_id, "second", active=False)
    other = _teacher(uuid.uuid4(), "other")
    profiles = build_operational_workload_profiles(
        teachers=[other, second, first],
        timetable_assignments=[_teaching(first.id, periods=["d0:p1"]), _teaching(other.id, periods=["d0:p1"])],
        duty_assignments=[_duty(first.id), _duty(other.id)],
        period_times={1: ("08:00", "08:45")},
        tenant_id=tenant_id,
    )
    assert [profile.teacher_id for profile in profiles] == [first.id]


@pytest.mark.asyncio
async def test_loader_uses_published_tenant_subset_and_performs_no_writes() -> None:
    tenant_id = uuid.uuid4()
    version = SimpleNamespace(id=uuid.uuid4(), generation_configuration_id=uuid.uuid4())
    configuration = SimpleNamespace(bell_schedule_id=uuid.uuid4())
    teacher = _teacher(tenant_id, "selected")
    assignment = _teaching(teacher.id, periods=["d0:p1"])
    duty = _loaded_duty(teacher.id)
    period = SimpleNamespace(period_number=1, start_time="08:00", end_time="08:45")
    db = FakeDB(
        scalar_values=[version, configuration],
        execute_values=[[teacher], [assignment], [duty], [period]],
    )

    profiles = await load_operational_workload_profiles(
        db,
        tenant_id=tenant_id,
        timetable_version_id=version.id,
        academic_year="2026-2027",
        teacher_ids={teacher.id, uuid.uuid4()},
    )
    assert profiles[0].teaching_minutes == 45
    assert profiles[0].recurring_duty_minutes == 30
    assert profiles[0].baseline_total_minutes == 75
    assert db.add.await_count == 0
    assert db.delete.await_count == 0
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert all("teacher_id" in statement or "duty_assignments" not in statement for statement in statements)


@pytest.mark.asyncio
async def test_empty_teacher_subset_returns_without_loading_school() -> None:
    db = FakeDB(scalar_values=[], execute_values=[])
    assert await load_operational_workload_profiles(
        db,
        tenant_id=uuid.uuid4(),
        timetable_version_id=uuid.uuid4(),
        academic_year="2026-2027",
        teacher_ids=set(),
    ) == []
    assert db.scalar.await_count == 0
    assert db.execute.await_count == 0


def test_inactive_duty_slot_is_excluded_from_workload() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "inactive-slot")
    profiles = build_operational_workload_profiles(
        teachers=[teacher],
        timetable_assignments=[],
        duty_assignments=[_loaded_duty(teacher.id, active=False)],
        period_times={},
        tenant_id=tenant_id,
    )
    assert profiles[0].recurring_duty_count == 0
    assert profiles[0].recurring_duty_minutes == 0
    assert profiles[0].baseline_total_minutes == 0


@pytest.mark.asyncio
async def test_loader_rejects_unpublished_or_cross_tenant_version_without_writes() -> None:
    db = FakeDB(scalar_values=[None], execute_values=[])
    assert await load_operational_workload_profiles(
        db,
        tenant_id=uuid.uuid4(),
        timetable_version_id=uuid.uuid4(),
        academic_year="2026-2027",
    ) == []
    db.add.assert_not_awaited()
    db.commit.assert_not_awaited()
