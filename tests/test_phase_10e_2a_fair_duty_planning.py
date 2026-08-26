from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.timetable.fair_duty_planning import (
    DutyPlanningError,
    build_fair_duty_plan,
    calculate_teacher_teaching_load,
    plan_fair_duty_roster,
)


class Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class FakeDB:
    def __init__(self, *, version: object | None, execute_values: list[list[object]]) -> None:
        self.scalar = AsyncMock(return_value=version)
        self.execute = AsyncMock(side_effect=[Result(rows) for rows in execute_values])
        self.added: list[object] = []
        self.deleted = False
        self.commit = AsyncMock()

    def add(self, value: object) -> None:
        self.added.append(value)


def _teacher(tenant_id: uuid.UUID, suffix: str, *, active: bool = True) -> SimpleNamespace:
    user = SimpleNamespace(is_active=active)
    return SimpleNamespace(id=uuid.uuid5(uuid.NAMESPACE_URL, f"teacher:{tenant_id}:{suffix}"), tenant_id=tenant_id, user=user)


def _assignment(teacher_id: uuid.UUID, *, day: int = 0, period: int = 1, occupied: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        teacher_id=str(teacher_id),
        day_key=f"d{day}",
        period_key=f"d{day}:p{period}",
        occupied_period_keys_json=occupied or [],
    )


def _demand(tenant_id: uuid.UUID, *, start: str = "10:00", end: str = "10:30", suffix: str = "one") -> SimpleNamespace:
    slot = SimpleNamespace(id=uuid.uuid5(uuid.NAMESPACE_URL, f"slot:{suffix}"), tenant_id=tenant_id, start_time=start, end_time=end, is_active=True)
    location = SimpleNamespace(id=uuid.uuid5(uuid.NAMESPACE_URL, f"location:{suffix}"), tenant_id=tenant_id, is_active=True)
    return SimpleNamespace(slot=slot, location=location)


def test_teaching_load_uses_occupied_canonical_periods() -> None:
    teacher_id = uuid.uuid4()
    assignments = [_assignment(teacher_id, occupied=["d0:p1", "d0:p2"]), _assignment(teacher_id, day=1, period=3)]
    assert calculate_teacher_teaching_load(assignments) == {str(teacher_id): 3}


def test_teaching_conflicts_and_existing_duty_conflicts_are_excluded() -> None:
    tenant_id = uuid.uuid4()
    busy = _teacher(tenant_id, "busy")
    free = _teacher(tenant_id, "free")
    demand = _demand(tenant_id, start="08:10", end="08:30")
    timetable = [_assignment(busy.id, period=1)]
    existing = [SimpleNamespace(teacher_id=free.id, duty_slot_id=demand.slot.id, location_id=demand.location.id, day_of_week=0)]

    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0, "d1": 1, "d2": 2, "d3": 3, "d4": 4},
        teachers=[busy, free],
        slot_locations=[demand],
        timetable_assignments=timetable,
        existing_assignments=existing,
        period_times={1: ("08:00", "08:45")},
        academic_year="2026-2027",
    )
    assert all(item.day_key != "d0" for item in plan)
    assert len(plan) == 4


def test_existing_canonical_sunday_and_monday_duties_map_to_sunday_thursday_keys() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "existing")
    demand = _demand(tenant_id)
    operational_days = {"d0": 6, "d1": 0, "d2": 1, "d3": 2, "d4": 3}

    sunday_existing = SimpleNamespace(
        teacher_id=teacher.id,
        duty_slot_id=demand.slot.id,
        location_id=demand.location.id,
        day_of_week=0,
    )
    sunday_plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys=operational_days,
        teachers=[teacher],
        slot_locations=[demand],
        timetable_assignments=[],
        existing_assignments=[sunday_existing],
        academic_year="2026-2027",
    )
    assert "d0" not in {item.day_key for item in sunday_plan}
    assert "d1" in {item.day_key for item in sunday_plan}

    monday_existing = SimpleNamespace(
        teacher_id=teacher.id,
        duty_slot_id=demand.slot.id,
        location_id=demand.location.id,
        day_of_week=1,
    )
    monday_plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys=operational_days,
        teachers=[teacher],
        slot_locations=[demand],
        timetable_assignments=[],
        existing_assignments=[monday_existing],
        academic_year="2026-2027",
    )
    assert "d1" not in {item.day_key for item in monday_plan}
    assert "d0" in {item.day_key for item in monday_plan}


def test_sunday_thursday_plan_exposes_canonical_day_indices() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "canonical")
    demand = _demand(tenant_id)

    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 6, "d1": 0, "d2": 1, "d3": 2, "d4": 3},
        teachers=[teacher],
        slot_locations=[demand],
        timetable_assignments=[],
        academic_year="2026-2027",
    )

    assert [(item.day_key, item.day_of_week) for item in plan] == [
        ("d0", 0), ("d1", 1), ("d2", 2), ("d3", 3), ("d4", 4),
    ]


def test_multiple_locations_at_one_slot_are_distinct_demand() -> None:
    tenant_id = uuid.uuid4()
    teachers = [_teacher(tenant_id, "one"), _teacher(tenant_id, "two")]
    first = _demand(tenant_id, suffix="first")
    second = _demand(tenant_id, suffix="second")
    second.slot.id = first.slot.id
    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0},
        teachers=teachers,
        slot_locations=[first, second],
        timetable_assignments=[],
        academic_year="2026-2027",
    )
    assert {item.location_id for item in plan} == {first.location.id, second.location.id}


def test_lower_load_teacher_can_receive_more_duty_and_ties_are_stable() -> None:
    tenant_id = uuid.uuid4()
    high = _teacher(tenant_id, "high")
    low = _teacher(tenant_id, "low")
    other_tenant_teacher = _teacher(uuid.uuid4(), "other")
    demands = [_demand(tenant_id, suffix=f"{index}") for index in range(5)]

    first = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0, "d1": 1, "d2": 2, "d3": 3, "d4": 4},
        teachers=[high, low, other_tenant_teacher],
        slot_locations=demands,
        timetable_assignments=[_assignment(high.id, day=index, period=1) for index in range(4)],
        period_times={1: ("08:00", "08:45")},
        academic_year="2026-2027",
    )
    second = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0, "d1": 1, "d2": 2, "d3": 3, "d4": 4},
        teachers=[other_tenant_teacher, low, high],
        slot_locations=demands,
        timetable_assignments=[_assignment(high.id, day=index, period=1) for index in range(4)],
        period_times={1: ("08:00", "08:45")},
        academic_year="2026-2027",
    )
    assert [item.as_dict() for item in first] == [item.as_dict() for item in second]
    assert all(item.teacher_id != other_tenant_teacher.id for item in first)
    counts = {teacher.id: sum(item.teacher_id == teacher.id for item in first) for teacher in (high, low)}
    assert counts[low.id] >= counts[high.id]


def test_inactive_teachers_and_unavailable_slots_are_not_assigned() -> None:
    tenant_id = uuid.uuid4()
    inactive = _teacher(tenant_id, "inactive", active=False)
    demand = _demand(tenant_id)
    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0},
        teachers=[inactive],
        slot_locations=[demand],
        timetable_assignments=[],
        academic_year="2026-2027",
    )
    assert plan == []


@pytest.mark.asyncio
async def test_async_planner_reads_published_tenant_inputs_without_writes() -> None:
    tenant_id = uuid.uuid4()
    version = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, lifecycle_status="published")
    teacher = _teacher(tenant_id, "one")
    demand = _demand(tenant_id)
    assignment = _assignment(teacher.id, period=2)
    period = SimpleNamespace(sort_order=2, start_time="09:00", end_time="09:45")
    school_week = SimpleNamespace(operational_weekdays=[0, 1, 2, 3, 4])
    db = FakeDB(version=version, execute_values=[[teacher], [demand], [assignment], [], [period]])
    db.scalar = AsyncMock(side_effect=[version, school_week])

    plan = await plan_fair_duty_roster(
        db,
        tenant_id=tenant_id,
        timetable_version_id=version.id,
        academic_year="2026-2027",
    )
    assert plan
    assert db.added == []
    db.commit.assert_not_awaited()
    assert db.execute.await_count == 5


def test_sunday_thursday_configuration_excludes_friday_demand() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "sun-thu")
    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 6, "d1": 0, "d2": 1, "d3": 2, "d4": 3},
        teachers=[teacher],
        slot_locations=[_demand(tenant_id)],
        timetable_assignments=[],
        academic_year="2026-2027",
    )
    assert {item.day_of_week for item in plan} == {0, 1, 2, 3, 4}
    assert {item.day_key for item in plan} == {"d0", "d1", "d2", "d3", "d4"}


def test_monday_friday_configuration_excludes_sunday_demand() -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id, "mon-fri")
    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 0, "d1": 1, "d2": 2, "d3": 3, "d4": 4},
        teachers=[teacher],
        slot_locations=[_demand(tenant_id)],
        timetable_assignments=[],
        academic_year="2026-2027",
    )
    assert {item.day_of_week for item in plan} == {0, 1, 2, 3, 4}
    assert 6 not in {item.day_of_week for item in plan}


def test_planner_has_no_fixed_monday_friday_loop() -> None:
    from pathlib import Path

    source = Path("services/timetable/fair_duty_planning.py").read_text(encoding="utf-8")
    assert "range(5)" not in source


@pytest.mark.asyncio
async def test_async_planner_rejects_non_published_or_cross_tenant_version() -> None:
    db = FakeDB(version=None, execute_values=[])
    with pytest.raises(DutyPlanningError) as exc:
        await plan_fair_duty_roster(
            db,
            tenant_id=uuid.uuid4(),
            timetable_version_id=uuid.uuid4(),
            academic_year="2026-2027",
        )
    assert exc.value.code == "published_timetable_not_found"


@pytest.mark.asyncio
async def test_missing_school_week_config_fails_without_fabricating_weekdays() -> None:
    tenant_id = uuid.uuid4()
    version = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, lifecycle_status="published")
    db = FakeDB(version=version, execute_values=[[], [], [], [], []])
    db.scalar = AsyncMock(side_effect=[version, None])

    with pytest.raises(DutyPlanningError) as exc:
        await plan_fair_duty_roster(
            db,
            tenant_id=tenant_id,
            timetable_version_id=version.id,
            academic_year="2026-2027",
        )
    assert exc.value.code == "school_week_config_required"
