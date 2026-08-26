from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.timetable.teacher_absences as service
from services.timetable.teacher_absences import (
    TeacherAbsenceError,
    cancel_absence,
    close_absence,
    confirm_absence,
    report_absence,
)
from shared.db.models import AuditLog, TeacherAbsence


class Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class FakeDB:
    def __init__(self, *, scalar_values: list[object] | None = None, rows: list[object] | None = None) -> None:
        self.scalar = AsyncMock(side_effect=scalar_values or [])
        self.execute = AsyncMock(return_value=Result(rows or []))
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def _teacher(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id)


def _absence(tenant_id: uuid.UUID, *, status: str = "reported") -> TeacherAbsence:
    return TeacherAbsence(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        scope_type="whole_day",
        selected_periods=None,
        reason_code="sick",
        private_note="private medical detail",
        source_type="teacher",
        reported_by_user_id=uuid.uuid4(),
        status=status,
    )


@pytest.fixture
def audit_entries(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    entries: list[dict] = []

    async def fake_log_action(*args: object, **kwargs: object) -> None:
        entries.append(kwargs)

    monkeypatch.setattr(service, "log_action", fake_log_action)
    return entries


@pytest.mark.asyncio
async def test_report_valid_whole_day_and_selected_period(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id)
    actor_id = uuid.uuid4()
    db = FakeDB(scalar_values=[teacher, SimpleNamespace(id=actor_id, tenant_id=tenant_id)])

    whole_day = await report_absence(
        db,
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        scope_type="whole_day",
        reason_code="sick",
        source_type="teacher",
        reported_by_user_id=actor_id,
    )
    assert whole_day.status == "reported"
    assert whole_day.selected_periods is None

    db.scalar = AsyncMock(return_value=teacher)
    selected = await report_absence(
        db,
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        start_date=date(2026, 9, 3),
        end_date=date(2026, 9, 3),
        scope_type="selected_periods",
        selected_periods=[1, "P3"],
        reason_code="appointment",
        source_type="system",
    )
    assert selected.selected_periods == [1, "P3"]
    assert [entry["action"] for entry in audit_entries] == ["absence_reported", "absence_reported"]
    assert "private medical detail" not in str(audit_entries)


@pytest.mark.asyncio
async def test_report_rejects_cross_tenant_teacher_and_malformed_periods() -> None:
    db = FakeDB(scalar_values=[None])
    with pytest.raises(TeacherAbsenceError) as exc:
        await report_absence(
            db,
            tenant_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            scope_type="whole_day",
            reason_code="sick",
            source_type="import",
        )
    assert exc.value.code == "teacher_not_found"

    with pytest.raises(TeacherAbsenceError) as exc:
        await report_absence(
            FakeDB(),
            tenant_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            scope_type="selected_periods",
            selected_periods=[],
            reason_code="sick",
            source_type="import",
        )
    assert exc.value.code == "absence_selected_periods_required"

    with pytest.raises(TeacherAbsenceError) as exc:
        await report_absence(
            FakeDB(),
            tenant_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            scope_type="selected_periods",
            selected_periods=[0],
            reason_code="sick",
            source_type="import",
        )
    assert exc.value.code == "absence_selected_periods_invalid"

    with pytest.raises(TeacherAbsenceError) as exc:
        await report_absence(
            FakeDB(),
            tenant_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            start_date=date(2026, 9, 2),
            end_date=date(2026, 9, 1),
            scope_type="selected_periods",
            selected_periods=[],
            reason_code="sick",
            source_type="import",
        )
    assert exc.value.code == "absence_date_range_invalid"


@pytest.mark.asyncio
async def test_report_exact_duplicate_is_idempotent_but_overlap_is_allowed(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id)
    existing = _absence(tenant_id)
    existing.teacher_id = teacher.id
    actor_id = uuid.uuid4()
    db = FakeDB(
        scalar_values=[teacher, SimpleNamespace(id=actor_id, tenant_id=tenant_id)],
        rows=[existing],
    )

    duplicate = await report_absence(
        db,
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        start_date=existing.start_date,
        end_date=existing.end_date,
        scope_type="whole_day",
        reason_code="sick",
        private_note=existing.private_note,
        source_type="teacher",
        reported_by_user_id=actor_id,
    )
    assert duplicate is existing
    assert db.added == []
    assert audit_entries == []

    db.scalar = AsyncMock(return_value=teacher)
    db.execute = AsyncMock(return_value=Result([existing]))
    overlap = await report_absence(
        db,
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        start_date=existing.start_date,
        end_date=existing.end_date,
        scope_type="whole_day",
        reason_code="training",
        source_type="teacher",
    )
    assert overlap is not existing
    assert len([value for value in db.added if isinstance(value, TeacherAbsence)]) == 1


@pytest.mark.asyncio
async def test_report_duplicate_only_matches_active_statuses(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id)
    for status in ("reported", "confirmed"):
        existing = _absence(tenant_id, status=status)
        existing.teacher_id = teacher.id
        actor_id = uuid.uuid4()
        db = FakeDB(
            scalar_values=[teacher, SimpleNamespace(id=actor_id, tenant_id=tenant_id)],
            rows=[existing],
        )
        result = await report_absence(
            db,
            tenant_id=tenant_id,
            teacher_id=teacher.id,
            start_date=existing.start_date,
            end_date=existing.end_date,
            scope_type="whole_day",
            reason_code="sick",
            private_note=existing.private_note,
            source_type="teacher",
            reported_by_user_id=actor_id,
        )
        assert result is existing
        assert db.added == []

    for status in ("cancelled", "closed"):
        existing = _absence(tenant_id, status=status)
        existing.teacher_id = teacher.id
        db = FakeDB(scalar_values=[teacher], rows=[existing])
        result = await report_absence(
            db,
            tenant_id=tenant_id,
            teacher_id=teacher.id,
            start_date=existing.start_date,
            end_date=existing.end_date,
            scope_type="whole_day",
            reason_code="sick",
            private_note=existing.private_note,
            source_type="teacher",
        )
        assert result is not existing
        assert result.status == "reported"


@pytest.mark.asyncio
async def test_confirm_preserves_reporting_provenance_and_is_idempotent(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    absence = _absence(tenant_id)
    original_reporter = absence.reported_by_user_id
    confirmer = uuid.uuid4()
    db = FakeDB(scalar_values=[absence, SimpleNamespace(id=confirmer, tenant_id=tenant_id)])

    result = await confirm_absence(db, tenant_id=tenant_id, absence_id=absence.id, confirmed_by_user_id=confirmer)
    assert result.status == "confirmed"
    assert result.reported_by_user_id == original_reporter
    assert result.confirmed_by_user_id == confirmer
    assert db.commit.await_count == 1

    db.scalar = AsyncMock(return_value=absence)
    again = await confirm_absence(db, tenant_id=tenant_id, absence_id=absence.id, confirmed_by_user_id=uuid.uuid4())
    assert again is absence
    assert db.commit.await_count == 1
    assert [entry["action"] for entry in audit_entries] == ["absence_confirmed"]


@pytest.mark.asyncio
async def test_confirm_rejects_cancelled_and_cross_tenant_absence() -> None:
    cancelled = _absence(uuid.uuid4(), status="cancelled")
    db = FakeDB(scalar_values=[cancelled])
    with pytest.raises(TeacherAbsenceError) as exc:
        await confirm_absence(db, tenant_id=cancelled.tenant_id, absence_id=cancelled.id)
    assert exc.value.code == "absence_transition_invalid"

    db = FakeDB(scalar_values=[None])
    with pytest.raises(TeacherAbsenceError) as exc:
        await cancel_absence(db, tenant_id=uuid.uuid4(), absence_id=uuid.uuid4())
    assert exc.value.code == "absence_not_found"


@pytest.mark.asyncio
async def test_cancel_reported_and_confirmed_and_is_idempotent(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    cancel_actor = uuid.uuid4()
    reported = _absence(tenant_id)
    db = FakeDB(scalar_values=[reported, SimpleNamespace(id=cancel_actor, tenant_id=tenant_id)])
    result = await cancel_absence(db, tenant_id=tenant_id, absence_id=reported.id, cancelled_by_user_id=cancel_actor)
    assert result.status == "cancelled"
    assert result.cancelled_by_user_id == cancel_actor

    confirmed = _absence(tenant_id, status="confirmed")
    db.scalar = AsyncMock(side_effect=[confirmed, SimpleNamespace(id=cancel_actor, tenant_id=tenant_id)])
    await cancel_absence(db, tenant_id=tenant_id, absence_id=confirmed.id, cancelled_by_user_id=cancel_actor)
    assert confirmed.status == "cancelled"

    db.scalar = AsyncMock(return_value=confirmed)
    await cancel_absence(db, tenant_id=tenant_id, absence_id=confirmed.id, cancelled_by_user_id=uuid.uuid4())
    assert [entry["action"] for entry in audit_entries] == ["absence_cancelled", "absence_cancelled"]


@pytest.mark.asyncio
async def test_close_only_confirmed_and_is_idempotent(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    reported = _absence(tenant_id)
    db = FakeDB(scalar_values=[reported])
    with pytest.raises(TeacherAbsenceError):
        await close_absence(db, tenant_id=tenant_id, absence_id=reported.id)

    confirmed = _absence(tenant_id, status="confirmed")
    db.scalar = AsyncMock(return_value=confirmed)
    result = await close_absence(db, tenant_id=tenant_id, absence_id=confirmed.id)
    assert result.status == "closed"

    db.scalar = AsyncMock(return_value=confirmed)
    await close_absence(db, tenant_id=tenant_id, absence_id=confirmed.id)
    assert [entry["action"] for entry in audit_entries] == ["absence_closed"]


@pytest.mark.asyncio
async def test_service_adds_only_absence_and_audit_records(audit_entries: list[dict]) -> None:
    tenant_id = uuid.uuid4()
    teacher = _teacher(tenant_id)
    db = FakeDB(scalar_values=[teacher])
    await report_absence(
        db,
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        scope_type="whole_day",
        reason_code="sick",
        source_type="import",
    )
    assert all(isinstance(value, (TeacherAbsence, AuditLog)) for value in db.added)
    assert not any(value.__class__.__name__ in {"Substitution", "Duty", "DailySession", "Timetable"} for value in db.added)
