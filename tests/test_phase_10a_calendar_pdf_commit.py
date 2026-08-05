from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarEventCandidate, CalendarSourceDocument, ImportBatch


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return type("S", (), {"all": lambda _self: self._rows})()


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.execute = AsyncMock(return_value=_ExecuteResult([]))


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_validate_requires_approved_candidates_when_requested() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    document = CalendarSourceDocument(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=uuid.uuid4(), file_sha256="x", extraction_status="processed")
    batch = ImportBatch(
        id=document.import_batch_id,
        tenant_id=tenant.id,
        entity_type="calendar_pdf",
        file_sha256="x",
        status="parsing",
        mode="workbook",
        created_by_user_id=actor.id,
    )
    candidates = [
        CalendarEventCandidate(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            source_document_id=document.id,
            proposed_event_name="E",
            proposed_description="E",
            proposed_start_date=date(2026, 9, 1),
            proposed_end_date=date(2026, 9, 1),
            proposed_event_type="school_event",
            proposed_teaching_day_effect="no_change",
            candidate_status="proposed",
            validation_issues_json={"warnings": [], "blockers": []},
            date_parse_status="parsed",
        )
    ]

    db.scalar = AsyncMock(side_effect=[document, batch])
    db.execute = AsyncMock(return_value=_ExecuteResult(candidates))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        payload = await calendar_intake.validate_calendar_pdf_batch(
            document.id,
            body=calendar_intake.ValidatePdfBatchRequest(require_approved_only=True),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["status"] == "validation_failed"
    assert payload["blocker_count"] >= 1


@pytest.mark.asyncio
async def test_commit_requires_validated_batch_and_approved_candidates() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    document = CalendarSourceDocument(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=uuid.uuid4(), file_sha256="x", extraction_status="processed")
    batch = ImportBatch(
        id=document.import_batch_id,
        tenant_id=tenant.id,
        entity_type="calendar_pdf",
        file_sha256="x",
        status="parsing",
        mode="workbook",
        created_by_user_id=actor.id,
    )

    db.scalar = AsyncMock(side_effect=[document, batch])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.commit_calendar_pdf_batch(
                document.id,
                body=calendar_intake.CommitApprovedCandidatesRequest(),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_batch_blocks_committed_batches() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    document = CalendarSourceDocument(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=uuid.uuid4(), file_sha256="x", extraction_status="processed")
    batch = ImportBatch(
        id=document.import_batch_id,
        tenant_id=tenant.id,
        entity_type="calendar_pdf",
        file_sha256="x",
        status="committed",
        mode="workbook",
        created_by_user_id=actor.id,
        committed_at=calendar_intake._now(),
    )
    db.scalar = AsyncMock(side_effect=[document, batch])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.cancel_calendar_pdf_batch(
                document.id,
                body=calendar_intake.EventStatusReasonRequest(reason="Stop"),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc.value.status_code == 409
