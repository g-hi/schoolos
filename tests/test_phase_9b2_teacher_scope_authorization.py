from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.authorization.teacher_scope import (
    teacher_has_homeroom_scope,
    teacher_has_subject_scope,
    teacher_has_weekly_report_class_scope,
)


@pytest.mark.asyncio
async def test_homeroom_uses_canonical_match_when_history_exists() -> None:
    db = AsyncMock()
    canonical_assignment_id = uuid.uuid4()
    db.scalar.side_effect = [uuid.uuid4(), canonical_assignment_id]

    decision = await teacher_has_homeroom_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), class_teacher_id=None),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "canonical"
    assert decision.matched_assignment_id == canonical_assignment_id


@pytest.mark.asyncio
async def test_homeroom_blocks_legacy_fallback_when_canonical_history_exists() -> None:
    teacher_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), None]

    decision = await teacher_has_homeroom_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=teacher_id,
        klass=SimpleNamespace(id=uuid.uuid4(), class_teacher_id=teacher_id),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "canonical"
    assert decision.canonical_history_exists is True


@pytest.mark.asyncio
async def test_homeroom_legacy_fallback_only_when_no_canonical_history() -> None:
    teacher_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar.side_effect = [None]

    decision = await teacher_has_homeroom_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=teacher_id,
        klass=SimpleNamespace(id=uuid.uuid4(), class_teacher_id=teacher_id),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "legacy"
    assert decision.canonical_history_exists is False


@pytest.mark.asyncio
async def test_subject_uses_canonical_match_when_history_exists() -> None:
    db = AsyncMock()
    canonical_assignment_id = uuid.uuid4()
    db.scalar.side_effect = [uuid.uuid4(), canonical_assignment_id]

    decision = await teacher_has_subject_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027"),
        subject_id=uuid.uuid4(),
        timetable_entry_id=uuid.uuid4(),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "canonical"
    assert decision.matched_assignment_id == canonical_assignment_id


@pytest.mark.asyncio
async def test_subject_blocks_legacy_fallback_when_canonical_history_exists() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), None]

    decision = await teacher_has_subject_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027"),
        subject_id=uuid.uuid4(),
        timetable_entry_id=uuid.uuid4(),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "canonical"
    assert decision.canonical_history_exists is True


@pytest.mark.asyncio
async def test_subject_legacy_fallback_only_when_no_canonical_history() -> None:
    db = AsyncMock()
    timetable_entry_id = uuid.uuid4()
    db.scalar.side_effect = [None, timetable_entry_id]

    decision = await teacher_has_subject_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027"),
        subject_id=uuid.uuid4(),
        timetable_entry_id=timetable_entry_id,
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "legacy"
    assert decision.canonical_history_exists is False
    assert decision.matched_timetable_entry_id == timetable_entry_id


@pytest.mark.asyncio
async def test_weekly_report_no_canonical_history_allows_class_teacher_fallback() -> None:
    teacher_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar.side_effect = [None]

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=teacher_id,
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=teacher_id),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "legacy"
    assert decision.reason == "matched_legacy_class_teacher"


@pytest.mark.asyncio
async def test_weekly_report_no_canonical_history_allows_active_timetable_fallback() -> None:
    db = AsyncMock()
    timetable_entry_id = uuid.uuid4()
    db.scalar.side_effect = [None, timetable_entry_id]

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=uuid.uuid4()),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is True
    assert decision.source == "legacy"
    assert decision.reason == "matched_legacy_timetable"


@pytest.mark.asyncio
async def test_weekly_report_canonical_inactive_homeroom_blocks_class_teacher_fallback() -> None:
    teacher_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), None]

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=teacher_id,
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=teacher_id),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "canonical"
    assert decision.reason == "canonical_history_without_active_homeroom"


@pytest.mark.asyncio
async def test_weekly_report_canonical_inactive_homeroom_blocks_timetable_fallback() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), None]

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=uuid.uuid4()),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "canonical"
    assert decision.reason == "canonical_history_without_active_homeroom"


@pytest.mark.asyncio
async def test_weekly_report_canonical_subject_teacher_history_does_not_grant_class_wide_access() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), None]

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=uuid.uuid4()),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "canonical"
    assert decision.reason == "canonical_history_without_active_homeroom"


@pytest.mark.asyncio
async def test_weekly_report_cross_tenant_timetable_evidence_denied() -> None:
    tenant_id = uuid.uuid4()

    async def scalar_side_effect(statement):
        compiled = statement.compile()
        text = str(compiled)
        if "FROM teacher_assignments" in text:
            return None
        if "FROM timetable_entries" in text:
            # A row from another tenant must not match because the query is tenant-scoped.
            assert "timetable_entries.tenant_id" in text
            params = compiled.params
            assert any(value == tenant_id for key, value in params.items() if key.startswith("tenant_id"))
            return None
        return None

    db = AsyncMock()
    db.scalar.side_effect = scalar_side_effect

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=tenant_id,
        teacher_id=uuid.uuid4(),
        klass=SimpleNamespace(id=uuid.uuid4(), academic_year="2026-2027", class_teacher_id=uuid.uuid4()),
        effective_date=date(2026, 7, 23),
    )

    assert decision.authorized is False
    assert decision.source == "none"