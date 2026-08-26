from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import services.timetable.absence_impact as impact
from services.timetable.fair_duty_planning import build_fair_duty_plan


class Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class FakeDB:
    def __init__(self, absence: object, *, sessions=(), school_days=(), duties=(), existing=(), school_week=None):
        self.absence = absence
        self.sessions = list(sessions)
        self.school_days = list(school_days)
        self.duties = list(duties)
        self.existing = list(existing)
        self.school_week = school_week
        self.added: list[object] = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def scalar(self, statement):
        text = str(statement)
        if "teacher_absences" in text:
            return self.absence
        if "school_week_configs" in text:
            return self.school_week
        return SimpleNamespace(id=uuid.uuid4())

    async def execute(self, statement):
        text = str(statement)
        if "daily_sessions" in text and "operational_school_days" in text:
            return Result(self.sessions)
        if "academic_years" in text:
            return Result(self.school_days)
        if "duty_assignments" in text:
            return Result(self.duties)
        if "operational_assignment_requests" in text:
            return Result(self.existing)
        raise AssertionError(f"unexpected query: {text}")

    def add(self, value: object) -> None:
        self.added.append(value)
        if value.__class__.__name__ == "OperationalAssignmentRequest":
            self.existing.append(value)


def absence(tenant_id, teacher_id, *, scope_type="whole_day", status="confirmed", start=date(2026, 9, 6), end=date(2026, 9, 7)):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, teacher_id=teacher_id,
        start_date=start, end_date=end, scope_type=scope_type,
        selected_periods=None if scope_type == "whole_day" else [1, "P3"], status=status,
    )


def session(tenant_id, teacher_id, school_date, period_number):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, teacher_id=str(teacher_id),
        school_date=school_date, period_number=period_number,
    )


def school_day(school_date, academic_year="2026-2027"):
    return (
        SimpleNamespace(school_date=school_date),
        SimpleNamespace(academic_year_id=uuid.uuid4()),
        SimpleNamespace(name=academic_year),
    )


def duty(teacher_id, day_of_week, academic_year="2026-2027"):
    return SimpleNamespace(
        id=uuid.uuid4(), teacher_id=teacher_id, day_of_week=day_of_week,
        academic_year=academic_year,
    )


@pytest.fixture
def audit(monkeypatch):
    entries = []

    async def record(**kwargs):
        entries.append(kwargs)

    monkeypatch.setattr(impact, "log_action", record)
    return entries


@pytest.mark.asyncio
async def test_whole_day_resolves_sessions_and_each_duty_date(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(tenant_id, teacher_id)
    first = session(tenant_id, teacher_id, absent.start_date, 1)
    second = session(tenant_id, teacher_id, absent.end_date, 2)
    recurring = duty(teacher_id, 0)
    next_day_duty = duty(teacher_id, 1)
    db = FakeDB(
        absent, sessions=[first, second],
        school_days=[school_day(absent.start_date), school_day(absent.end_date)],
        duties=[recurring, next_day_duty], school_week=SimpleNamespace(operational_weekdays=[6, 0, 1, 2, 3]),
    )

    result = await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert result.teaching_requests_created == 2
    assert result.duty_requests_created == 2
    assert result.total_affected_items == 4
    requests = [value for value in db.added if value.__class__.__name__ == "OperationalAssignmentRequest"]
    assert {request.assignment_type for request in requests} == {"teaching_substitution", "duty_reassignment"}
    assert db.flush.await_count == 1 and db.commit.await_count == 1
    assert len(audit) == 4

    repeated = await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)
    assert repeated.teaching_requests_created == 0
    assert repeated.duty_requests_created == 0
    assert repeated.existing_requests == 4
    assert len(audit) == 4


@pytest.mark.asyncio
async def test_selected_periods_filter_teaching_and_skip_duty_resolution(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(tenant_id, teacher_id, scope_type="selected_periods", start=date(2026, 9, 7), end=date(2026, 9, 7))
    matching = session(tenant_id, teacher_id, absent.start_date, 3)
    unrelated = session(tenant_id, teacher_id, absent.start_date, 2)
    db = FakeDB(absent, sessions=[matching, unrelated])

    result = await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert result.teaching_requests_created == 1
    assert result.duty_requests_created == 0
    assert result.total_affected_items == 1
    assert db.school_week is None


@pytest.mark.parametrize(
    ("selected_periods", "period_number"),
    [([2], 2), (["2"], 2), (["P2"], 2), (["d0:p2"], 2)],
)
@pytest.mark.asyncio
async def test_each_defined_selected_period_representation_matches(audit, selected_periods, period_number):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(
        tenant_id, teacher_id, scope_type="selected_periods",
        start=date(2026, 9, 7), end=date(2026, 9, 7),
    )
    absent.selected_periods = selected_periods
    db = FakeDB(absent, sessions=[session(tenant_id, teacher_id, absent.start_date, period_number)])

    result = await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert result.teaching_requests_created == 1


@pytest.mark.asyncio
async def test_valid_but_uninterpretable_selected_period_fails_closed(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(
        tenant_id, teacher_id, scope_type="selected_periods",
        start=date(2026, 9, 7), end=date(2026, 9, 7),
    )
    absent.selected_periods = ["lunch"]
    db = FakeDB(absent, sessions=[session(tenant_id, teacher_id, absent.start_date, 1)])

    with pytest.raises(impact.AbsenceImpactError) as error:
        await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert error.value.code == "absence_selected_periods_uninterpretable"
    assert db.added == []


def test_fair_duty_planner_emits_canonical_indices_for_sunday_and_monday():
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    slot = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, start_time="08:00", end_time="08:30", is_active=True)
    location = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=True)
    links = [SimpleNamespace(slot=slot, location=location)]
    teachers = [SimpleNamespace(id=teacher_id, tenant_id=tenant_id, is_active=True, user=None)]

    plan = build_fair_duty_plan(
        tenant_id=tenant_id,
        operational_day_keys={"d0": 6, "d1": 0},
        teachers=teachers,
        slot_locations=links,
        timetable_assignments=[],
        academic_year="2026-2027",
    )

    assert [item.day_key for item in plan] == ["d0", "d1"]
    assert [item.day_of_week for item in plan] == [0, 1]


@pytest.mark.asyncio
async def test_historical_requests_do_not_block_active_request_creation(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(tenant_id, teacher_id, start=date(2026, 9, 7), end=date(2026, 9, 7))
    target = session(tenant_id, teacher_id, absent.start_date, 1)
    historical = SimpleNamespace(
        id=uuid.uuid4(), assignment_type="teaching_substitution", school_date=target.school_date,
        daily_session_id=target.id, duty_assignment_id=None, status="cancelled",
    )
    db = FakeDB(
        absent,
        sessions=[target],
        existing=[historical],
        school_week=SimpleNamespace(operational_weekdays=[0, 1, 2, 3, 4]),
    )

    result = await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert result.teaching_requests_created == 1
    assert result.existing_requests == 0


@pytest.mark.asyncio
async def test_non_confirmed_absence_is_rejected_without_mutation(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(tenant_id, teacher_id, status="reported", start=date(2026, 9, 7), end=date(2026, 9, 7))
    db = FakeDB(absent)

    with pytest.raises(impact.AbsenceImpactError) as error:
        await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert error.value.code == "absence_not_confirmed"
    assert db.added == []
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_missing_school_week_config_is_controlled(audit):
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    absent = absence(tenant_id, teacher_id, start=date(2026, 9, 7), end=date(2026, 9, 7))
    db = FakeDB(absent, school_week=None)

    with pytest.raises(impact.AbsenceImpactError) as error:
        await impact.resolve_absence_impact(db, tenant_id=tenant_id, absence_id=absent.id)

    assert error.value.code == "school_week_config_required"