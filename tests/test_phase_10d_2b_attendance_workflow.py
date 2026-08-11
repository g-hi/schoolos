from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import services.timetable.attendance_registers as attendance
from services.timetable.attendance_registers import AttendanceError, bulk_mark_attendance, correct_attendance_register, finalize_attendance_register, mark_all_present, submit_attendance_register


class FakeDB:
    def __init__(self) -> None:
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_bulk_mark_attendance_unknown_student_rejected(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    records = {
        student_id: SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)
    }

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        return None

    async def fake_load_records(db, *, tenant_id, register_id):
        return records

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": uuid.uuid4(), "status": "present"}],
        )
    assert exc.value.code == "attendance_unknown_student"


@pytest.mark.asyncio
async def test_bulk_mark_attendance_rejects_negative_late_minutes(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    record = SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        return None

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": student_id, "status": "late", "minutes_late": -1}],
        )
    assert exc.value.code == "attendance_late_minutes_invalid"


@pytest.mark.asyncio
async def test_mark_all_present_only_changes_unmarked(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()
    other = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    record1 = SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)
    record2 = SimpleNamespace(student_id=other, attendance_status="absent", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        return None

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record1, other: record2}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    await mark_all_present(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())

    assert record1.attendance_status == "present"
    assert record2.attendance_status == "absent"


@pytest.mark.asyncio
async def test_submit_attendance_register_blocked_by_incomplete_status(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    record = SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        return None

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await submit_attendance_register(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())
    assert exc.value.code == "attendance_incomplete"


@pytest.mark.asyncio
async def test_submit_attendance_register_moves_to_submitted(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    record = SimpleNamespace(student_id=student_id, attendance_status="present", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        return None

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    result = await submit_attendance_register(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())
    assert result.register_status == "submitted"


@pytest.mark.asyncio
async def test_finalize_requires_leadership_actor(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="submitted",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id):
        return False

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_leadership_actor", fake_authorize)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await finalize_attendance_register(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())
    assert exc.value.code == "attendance_authorization_denied"


@pytest.mark.asyncio
async def test_scheduled_teacher_can_mark_attendance(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    osd_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=osd_id,
        class_facing_session_key="cfsk-scheduled",
        tenant_id=tenant_id,
    )
    actor = SimpleNamespace(id=actor_id, tenant_id=tenant_id, role="teacher")
    teacher = SimpleNamespace(id=teacher_id, tenant_id=tenant_id, user_id=actor_id)
    session = SimpleNamespace(teacher_id=teacher_id)
    record = SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)

    class FakeExecResult:
        def __init__(self, rows):
            self._rows = rows
        def scalars(self):
            return SimpleNamespace(all=lambda: self._rows)

    class FakeDB:
        def __init__(self):
            self.scalar_values = iter([register, actor, teacher])
        async def scalar(self, *args, **kwargs):
            return next(self.scalar_values)
        async def execute(self, *args, **kwargs):
            return FakeExecResult([session])
        async def flush(self):
            return None

    db = FakeDB()

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    result = await bulk_mark_attendance(
        db,
        tenant_id=tenant_id,
        register_id=register_id,
        actor_id=actor_id,
        marks=[{"student_id": student_id, "status": "present"}],
    )

    assert result.id == register_id
    assert record.attendance_status == "present"


@pytest.mark.asyncio
async def test_unrelated_teacher_is_rejected(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    osd_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    student_id = uuid.uuid4()
    teacher_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=osd_id,
        class_facing_session_key="cfsk-unrelated",
        tenant_id=tenant_id,
    )
    actor = SimpleNamespace(id=actor_id, tenant_id=tenant_id, role="teacher")
    teacher = SimpleNamespace(id=teacher_id, tenant_id=tenant_id, user_id=actor_id)
    session = SimpleNamespace(teacher_id=uuid.uuid4())
    record = SimpleNamespace(student_id=student_id, attendance_status="unmarked", minutes_late=None)

    class FakeExecResult:
        def __init__(self, rows):
            self._rows = rows
        def scalars(self):
            return SimpleNamespace(all=lambda: self._rows)

    class FakeDB:
        def __init__(self):
            self.scalar_values = iter([register, actor, teacher])
        async def scalar(self, *args, **kwargs):
            return next(self.scalar_values)
        async def execute(self, *args, **kwargs):
            return FakeExecResult([session])
        async def flush(self):
            return None

    db = FakeDB()

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=actor_id,
            marks=[{"student_id": student_id, "status": "present"}],
        )
    assert exc.value.code == "attendance_authorization_denied"


@pytest.mark.asyncio
async def test_cross_tenant_actor_or_resource_is_rejected(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-cross",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id, register):
        raise AttendanceError("attendance_authorization_denied")

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_attendance_actor", fake_authorize)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": uuid.uuid4(), "status": "present"}],
        )
    assert exc.value.code == "attendance_authorization_denied"


@pytest.mark.asyncio
async def test_teacher_edit_rejected_after_register_submitted(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="submitted",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-editsub",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": uuid.uuid4(), "status": "present"}],
        )
    assert exc.value.code == "attendance_register_not_open"


@pytest.mark.asyncio
async def test_teacher_edit_rejected_after_register_finalized(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="finalized",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-editfinal",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": uuid.uuid4(), "status": "present"}],
        )
    assert exc.value.code == "attendance_register_not_open"


@pytest.mark.asyncio
async def test_finalize_open_register_rejected(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-open-final",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_leadership_authorize(db, *, tenant_id, actor_id):
        return True

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_leadership_actor", fake_leadership_authorize)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await finalize_attendance_register(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())
    assert exc.value.code == "attendance_register_not_submitted"


@pytest.mark.asyncio
async def test_ordinary_teacher_cannot_finalize(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="submitted",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-ordinary-final",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_leadership_authorize(db, *, tenant_id, actor_id):
        return False

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_leadership_actor", fake_leadership_authorize)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await finalize_attendance_register(db, tenant_id=tenant_id, register_id=register_id, actor_id=uuid.uuid4())
    assert exc.value.code == "attendance_authorization_denied"


@pytest.mark.asyncio
async def test_parallel_unresolved_register_cannot_be_marked(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="open",
        roster_resolution_status="parallel_unresolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-parallel",
        tenant_id=tenant_id,
    )

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)

    db = FakeDB()
    with pytest.raises(AttendanceError) as exc:
        await bulk_mark_attendance(
            db,
            tenant_id=tenant_id,
            register_id=register_id,
            actor_id=uuid.uuid4(),
            marks=[{"student_id": uuid.uuid4(), "status": "present"}],
        )
    assert exc.value.code == "parallel_roster_membership_unresolved"


@pytest.mark.asyncio
async def test_leadership_correction_audit_contains_required_payload(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="submitted",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="cfsk-correction-audit",
        tenant_id=tenant_id,
    )
    record = SimpleNamespace(student_id=student_id, attendance_status="absent", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id):
        return True

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    captured = {}

    async def fake_log_action(db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_leadership_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    await correct_attendance_register(
        db,
        tenant_id=tenant_id,
        register_id=register_id,
        actor_id=actor_id,
        student_id=student_id,
        new_status="present",
        correction_reason="late paperwork",
    )

    assert captured["details"]["before"] == "absent"
    assert captured["details"]["after"] == "present"
    assert captured["details"]["reason"] == "late paperwork"
    assert captured["actor_id"] == actor_id


@pytest.mark.asyncio
async def test_phase_10d_2b_migration_revision_and_head(monkeypatch):
    from pathlib import Path

    migration = Path("alembic/versions/9a2e3d7c04b1_phase_10d_2b_attendance_workflow.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "9a2e3d7c04b1"' in text
    assert 'down_revision: Union[str, None] = "b7c3d9e1f4a2"' in text

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads == ["9a2e3d7c04b1"]

    revision = script.get_revision("9a2e3d7c04b1")
    assert revision is not None
    assert revision.revision == "9a2e3d7c04b1"
    assert revision.down_revision == "b7c3d9e1f4a2"


@pytest.mark.asyncio
async def test_correct_attendance_register_enforces_reason_and_updates(monkeypatch):
    tenant_id = uuid.uuid4()
    register_id = uuid.uuid4()
    student_id = uuid.uuid4()

    register = SimpleNamespace(
        id=register_id,
        register_status="submitted",
        roster_resolution_status="resolved",
        operational_school_day_id=uuid.uuid4(),
        class_facing_session_key="fcs-key",
        tenant_id=tenant_id,
    )
    record = SimpleNamespace(student_id=student_id, attendance_status="absent", minutes_late=None)

    async def fake_load_register(db, *, tenant_id, register_id):
        return register

    async def fake_authorize(db, *, tenant_id, actor_id):
        return True

    async def fake_load_records(db, *, tenant_id, register_id):
        return {student_id: record}

    async def fake_log_action(*args, **kwargs):
        return None

    monkeypatch.setattr(attendance, "_load_register", fake_load_register)
    monkeypatch.setattr(attendance, "_authorize_leadership_actor", fake_authorize)
    monkeypatch.setattr(attendance, "_load_register_records", fake_load_records)
    monkeypatch.setattr(attendance, "log_action", fake_log_action)

    db = FakeDB()
    result = await correct_attendance_register(
        db,
        tenant_id=tenant_id,
        register_id=register_id,
        actor_id=uuid.uuid4(),
        student_id=student_id,
        new_status="present",
        correction_reason="ad hoc correction",
    )

    assert record.attendance_status == "present"
    assert result.attendance_status == "present"
