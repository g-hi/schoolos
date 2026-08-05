from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarEventCandidate


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.execute = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_edit_candidate_marks_edited() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    candidate = CalendarEventCandidate(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        proposed_event_name="Old",
        proposed_description="Old",
        proposed_start_date=date(2026, 9, 1),
        proposed_end_date=date(2026, 9, 1),
        proposed_event_type="school_event",
        proposed_teaching_day_effect="no_change",
        candidate_status="proposed",
        date_parse_status="parsed",
        validation_issues_json={"warnings": [], "blockers": []},
    )
    db.scalar = AsyncMock(return_value=candidate)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        payload = await calendar_intake.edit_calendar_candidate(
            candidate_id=candidate.id,
            body=calendar_intake.CandidateEditRequest(proposed_event_name="New"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["proposed_event_name"] == "New"
    assert payload["candidate_status"] == "edited"


@pytest.mark.asyncio
async def test_approve_candidate_rejects_blocker_rows() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    candidate = CalendarEventCandidate(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        proposed_event_name="Broken",
        proposed_description="Broken",
        proposed_start_date=date(2026, 9, 3),
        proposed_end_date=date(2026, 9, 1),
        proposed_event_type="school_event",
        proposed_teaching_day_effect="no_change",
        candidate_status="edited",
        date_parse_status="invalid_range",
        validation_issues_json={"warnings": [], "blockers": ["invalid_range"]},
    )
    db.scalar = AsyncMock(return_value=candidate)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.approve_calendar_candidate(candidate.id, tenant=tenant, actor=actor, db=db)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reject_candidate_sets_reason_and_reviewer() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    candidate = CalendarEventCandidate(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        proposed_event_name="Candidate",
        proposed_description="Candidate",
        proposed_start_date=date(2026, 9, 1),
        proposed_end_date=date(2026, 9, 1),
        proposed_event_type="school_event",
        proposed_teaching_day_effect="no_change",
        candidate_status="proposed",
        date_parse_status="parsed",
        validation_issues_json={"warnings": [], "blockers": []},
    )
    db.scalar = AsyncMock(return_value=candidate)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        payload = await calendar_intake.reject_calendar_candidate(
            candidate.id,
            body=calendar_intake.EventStatusReasonRequest(reason="Needs human correction"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["candidate_status"] == "rejected"
    assert payload["uncertainty_note"] == "Needs human correction"
