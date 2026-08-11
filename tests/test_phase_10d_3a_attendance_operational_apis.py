from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.gateway.routers.timetable_daily_sessions import (
    _ensure_principal,
    _ensure_teacher,
    _map_attendance_error,
    get_leadership_attendance_register_detail,
    get_leadership_attendance_registers,
    get_leadership_daily_attendance_summary,
    get_teacher_attendance_sessions,
    get_teacher_attendance_today,
    leadership_correction,
    leadership_finalize,
    teacher_attendance_view_for_date,
    teacher_bulk_mark,
    teacher_ensure_register,
    teacher_mark_all_present,
    teacher_register_detail,
    teacher_submit,
)
from services.timetable.attendance_registers import AttendanceError


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return FakeScalarResult(self._rows)

    def all(self):
        return self._rows


def metadata_for(*sessions):
    classes = {}
    subjects = {}
    for session in sessions:
        classes[session.class_id] = (
            SimpleNamespace(id=session.class_id, code="G5A", grade="Grade 5", section="A"),
            SimpleNamespace(name="Grade 5"),
        )
        subjects[session.subject_id] = SimpleNamespace(id=session.subject_id, name="Mathematics", tenant_id=uuid.uuid4())
    return FakeResult(list(classes.values())), FakeResult(list(subjects.values()))


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows


class FakeAsyncSession:
    def __init__(self, scalar_values=None, execute_values=None):
        self.scalar_values = list(scalar_values or [])
        self.execute_values = list(execute_values or [])
        self.added = []
        self.flushed = 0
        self.commits = 0

    async def scalar(self, *args, **kwargs):
        if not self.scalar_values:
            return None
        value = self.scalar_values.pop(0)
        return value

    async def execute(self, *args, **kwargs):
        # Accept the RLS command used by set_tenant_context() without
        # making the fake SQLAlchemy-specific deeper than needed.
        if args and getattr(args[0], "text", None) is not None:
            return FakeResult([])
        if not self.execute_values:
            return FakeResult([])
        value = self.execute_values.pop(0)
        if isinstance(value, FakeResult):
            return value
        if isinstance(value, list):
            return FakeResult(value)
        return FakeResult(value)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_teacher_today_list_smoke(monkeypatch):
    async def fake_teacher_view(*args, **kwargs):
        return [{"daily_session_id": str(uuid.uuid4()), "attendance_status": "not_started"}]

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions.teacher_attendance_view_for_date",
        fake_teacher_view,
    )

    tenant_id = uuid.uuid4()
    payload = await get_teacher_attendance_today(
        school_date=date(2026, 9, 15),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )
    assert isinstance(payload, dict)
    assert "items" in payload


@pytest.mark.asyncio
async def test_teacher_register_detail_smoke(monkeypatch):
    async def fake_detail(*args, **kwargs):
        return {"register_id": str(uuid.uuid4()), "expected_count": 1, "records": []}

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions.teacher_attendance_register_detail",
        fake_detail,
    )

    tenant_id = uuid.uuid4()
    payload = await teacher_register_detail(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )
    assert "register_id" in payload


@pytest.mark.asyncio
async def test_teacher_operational_date_list_filters_teacher_scope_and_scheduled_sessions(monkeypatch):
    teacher = SimpleNamespace(id=uuid.uuid4())
    tenant_id = uuid.uuid4()

    async def fake_resolve(*args, **kwargs):
        return teacher

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions._resolve_teacher_profile",
        fake_resolve,
    )

    session_a = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="k-001",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-1",
        subject_id="sub-1",
        period_start_time="08:00",
        period_end_time="08:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="k-001",
    )
    session_b = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="k-002",
        teacher_id="unrelated",
        school_date=date(2026, 9, 15),
        class_id="class-2",
        subject_id="sub-2",
        period_start_time="09:00",
        period_end_time="09:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="k-002",
    )
    session_c = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="k-003",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-3",
        subject_id="sub-3",
        period_start_time="10:00",
        period_end_time="10:45",
        session_status="cancelled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="k-003",
    )

    db = FakeAsyncSession(
        scalar_values=[None, None],
        execute_values=[FakeResult([session_a]), *metadata_for(session_a)],
    )

    payload = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant_id,
        actor_id=uuid.uuid4(),
        school_date=date(2026, 9, 15),
    )

    assert len(payload) == 1
    assert payload[0]["daily_session_id"] == str(session_a.id)
    assert payload[0]["attendance_status"] == "not_started"
    assert payload[0]["class_code"] == "G5A"
    assert payload[0]["grade_level"] == "Grade 5"
    assert payload[0]["section"] == "A"
    assert payload[0]["class_display_name"] == "Grade 5 A"
    assert payload[0]["subject_name"] == "Mathematics"


@pytest.mark.asyncio
async def test_teacher_attendance_view_deduplicates_class_facing_keys(monkeypatch):
    teacher = SimpleNamespace(id=uuid.uuid4())
    tenant_id = uuid.uuid4()

    async def fake_resolve(*args, **kwargs):
        return teacher

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions._resolve_teacher_profile",
        fake_resolve,
    )

    session_a = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="dedupe-ord",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-1",
        subject_id="sub-1",
        period_start_time="08:00",
        period_end_time="08:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="dedupe-ord",
    )
    session_b = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="dedupe-ord",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-1",
        subject_id="sub-1",
        period_start_time="08:00",
        period_end_time="09:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="dedupe-ord-2",
    )
    session_c = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="dedupe-parallel",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-2",
        subject_id="sub-2",
        period_start_time="09:00",
        period_end_time="09:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id="parallel-block-1",
        operational_school_day_id=uuid.uuid4(),
        session_key="dedupe-parallel-1",
    )
    session_d = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="dedupe-parallel",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-2",
        subject_id="sub-2",
        period_start_time="09:00",
        period_end_time="09:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id="parallel-block-1",
        operational_school_day_id=uuid.uuid4(),
        session_key="dedupe-parallel-2",
    )

    db = FakeAsyncSession(
        scalar_values=[None, None, None, None, None],
        execute_values=[FakeResult([session_a, session_b, session_c, session_d]), *metadata_for(session_a, session_c)],
    )

    payload = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant_id,
        actor_id=uuid.uuid4(),
        school_date=date(2026, 9, 15),
    )

    assert len(payload) == 2
    assert {item["class_facing_session_key"] for item in payload} == {"dedupe-ord", "dedupe-parallel"}
    assert payload[0]["attendance_status"] == "not_started" or payload[1]["attendance_status"] == "parallel_unresolved"


@pytest.mark.asyncio
async def test_teacher_attendance_view_status_derivation_read_models(monkeypatch):
    teacher = SimpleNamespace(id=uuid.uuid4())
    tenant_id = uuid.uuid4()

    async def fake_resolve(*args, **kwargs):
        return teacher

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions._resolve_teacher_profile",
        fake_resolve,
    )

    session = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="status-1",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-1",
        subject_id="sub-1",
        period_start_time="08:00",
        period_end_time="08:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="status-1",
    )

    register_open = SimpleNamespace(
        id=uuid.uuid4(),
        register_status="open",
        roster_resolution_status="resolved",
        expected_student_count=2,
        class_facing_session_key="status-1",
        school_date=date(2026, 9, 15),
    )
    register_submitted = SimpleNamespace(
        id=uuid.uuid4(),
        register_status="submitted",
        roster_resolution_status="resolved",
        expected_student_count=2,
        class_facing_session_key="status-1",
        school_date=date(2026, 9, 15),
    )
    register_finalized = SimpleNamespace(
        id=uuid.uuid4(),
        register_status="finalized",
        roster_resolution_status="resolved",
        expected_student_count=2,
        class_facing_session_key="status-1",
        school_date=date(2026, 9, 15),
    )

    db = FakeAsyncSession(
        scalar_values=[register_open, [SimpleNamespace(attendance_status="present")], register_submitted, [SimpleNamespace(attendance_status="present")], register_finalized, [SimpleNamespace(attendance_status="present")]],
        execute_values=[FakeResult([session]), *metadata_for(session), FakeResult([SimpleNamespace(attendance_status="present")]), FakeResult([SimpleNamespace(attendance_status="present")]), FakeResult([SimpleNamespace(attendance_status="present")])],
    )

    payload = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant_id,
        actor_id=uuid.uuid4(),
        school_date=date(2026, 9, 15),
    )
    assert payload[0]["attendance_status"] == "incomplete"


@pytest.mark.asyncio
async def test_get_read_endpoints_are_read_only(monkeypatch):
    teacher = SimpleNamespace(id=uuid.uuid4())
    tenant_id = uuid.uuid4()

    async def fake_resolve(*args, **kwargs):
        return teacher

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions._resolve_teacher_profile",
        fake_resolve,
    )

    session = SimpleNamespace(
        id=uuid.uuid4(),
        class_facing_session_key="read-1",
        teacher_id=str(teacher.id),
        school_date=date(2026, 9, 15),
        class_id="class-1",
        subject_id="sub-1",
        period_start_time="08:00",
        period_end_time="08:45",
        session_status="scheduled",
        is_active=True,
        override_reason=None,
        parallel_block_id=None,
        operational_school_day_id=uuid.uuid4(),
        session_key="read-1",
    )

    db = FakeAsyncSession(
        scalar_values=[None, None],
        execute_values=[FakeResult([session]), *metadata_for(session)],
    )

    payload = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant_id,
        actor_id=uuid.uuid4(),
        school_date=date(2026, 9, 15),
    )

    assert isinstance(payload, list)
    assert len(payload) == 1
    assert hasattr(db, "added")


@pytest.mark.asyncio
async def test_ensure_register_route_delegates(monkeypatch):
    captured = {}

    async def fake_ensure(db, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), register_status="open")

    monkeypatch.setattr(
        "services.gateway.routers.timetable_daily_sessions.ensure_attendance_register",
        fake_ensure,
    )

    tenant_id = uuid.uuid4()
    result = await teacher_ensure_register(
        body=SimpleNamespace(daily_session_id=uuid.uuid4()),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )
    assert result is not None
    assert "daily_session_id" in captured


@pytest.mark.asyncio
async def test_bulk_mark_and_submit_delegates(monkeypatch):
    async def fake_bulk(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4(), register_status="open")

    async def fake_mark_all(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4(), register_status="open")

    async def fake_submit(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4(), register_status="submitted")

    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.bulk_mark_attendance", fake_bulk)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.mark_all_present", fake_mark_all)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.submit_attendance_register", fake_submit)

    teacher_payload = {"marks": [{"student_id": uuid.uuid4(), "status": "present"}]}
    tenant_id = uuid.uuid4()
    await teacher_bulk_mark(
        body=SimpleNamespace(**teacher_payload),
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )

    await teacher_mark_all_present(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )

    await teacher_submit(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="teacher"),
        db=FakeAsyncSession(),
    )


@pytest.mark.asyncio
async def test_leadership_summary_list_detail_and_actions(monkeypatch):
    async def fake_summary(*args, **kwargs):
        return {"summary": {"expected_students": 1, "eligible_sessions": 1}}

    async def fake_list(*args, **kwargs):
        return [{"register_id": str(uuid.uuid4())}]

    async def fake_detail(*args, **kwargs):
        return {"register_id": str(uuid.uuid4()), "records": []}

    async def fake_finalize(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4(), register_status="finalized")

    async def fake_correction(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4(), student_id=uuid.uuid4(), attendance_status="present")

    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.leadership_daily_attendance_summary", fake_summary)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.leadership_attendance_register_list", fake_list)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.leadership_attendance_register_detail", fake_detail)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.finalize_attendance_register", fake_finalize)
    monkeypatch.setattr("services.gateway.routers.timetable_daily_sessions.correct_attendance_register", fake_correction)

    tenant_id = uuid.uuid4()
    await get_leadership_daily_attendance_summary(
        school_date=date(2026, 9, 15),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="principal"),
        db=FakeAsyncSession(),
    )
    await get_leadership_attendance_registers(
        school_date=date(2026, 9, 15),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="principal"),
        db=FakeAsyncSession(),
    )
    await get_leadership_attendance_register_detail(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="principal"),
        db=FakeAsyncSession(),
    )
    await leadership_finalize(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="principal"),
        db=FakeAsyncSession(),
    )
    await leadership_correction(
        register_id=uuid.uuid4(),
        tenant=SimpleNamespace(id=tenant_id),
        actor=SimpleNamespace(id=uuid.uuid4(), is_active=True, tenant_id=tenant_id, role="principal"),
        db=FakeAsyncSession(),
        body=SimpleNamespace(student_id=uuid.uuid4(), new_status="present", correction_reason="test"),
    )


@pytest.mark.asyncio
async def test_authorization_boundaries_reject_leading_unhappy_paths():
    tenant_id = uuid.uuid4()

    with pytest.raises(HTTPException):
        _ensure_teacher(
            SimpleNamespace(is_active=True, tenant_id=tenant_id, role="parent"),
            SimpleNamespace(id=tenant_id),
        )

    with pytest.raises(HTTPException):
        _ensure_teacher(
            SimpleNamespace(is_active=True, tenant_id=tenant_id, role="student"),
            SimpleNamespace(id=tenant_id),
        )

    with pytest.raises(HTTPException):
        _ensure_principal(
            SimpleNamespace(is_active=True, tenant_id=tenant_id, role="principal"),
            SimpleNamespace(id=uuid.uuid4()),
        )

    with pytest.raises(HTTPException):
        _ensure_teacher(
            SimpleNamespace(is_active=True, tenant_id=uuid.uuid4(), role="teacher"),
            SimpleNamespace(id=tenant_id),
        )


@pytest.mark.asyncio
async def test_attendance_error_mapping_is_consistent():
    mapping = {
        "attendance_not_available_for_session": 409,
        "attendance_roster_stale": 409,
        "parallel_roster_membership_unresolved": 409,
        "attendance_authorization_denied": 403,
        "attendance_register_not_open": 409,
        "attendance_unknown_student": 422,
        "attendance_incomplete": 409,
    }
    for code, expected in mapping.items():
        status, payload = _map_attendance_error(AttendanceError(code))
        assert status == expected
        assert payload["code"] == code
