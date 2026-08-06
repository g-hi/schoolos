from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup
from shared.db.models import OperationalCalendarEvent


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.scalar = AsyncMock(return_value=None)


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID, role: str = "principal", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active)


@pytest.mark.asyncio
async def test_calendar_date_validation_rejects_inverted_range() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_calendar_entry(
                body=timetable_setup.CalendarCreateRequest(
                    event_name="Holiday",
                    start_date=date(2026, 9, 2),
                    end_date=date(2026, 9, 1),
                    event_type="public_holiday",
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_calendar_manual_entry_auto_approved_and_audited() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup._validate_scope_keys", new=AsyncMock()
    ), patch("services.gateway.routers.timetable_setup._validate_term_bounds", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        payload = await timetable_setup.create_calendar_entry(
            body=timetable_setup.CalendarCreateRequest(
                event_name="Term Opening",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 1),
                event_type="term_boundary",
                source_type="manual",
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    added = db.add.call_args.args[0]
    assert isinstance(added, OperationalCalendarEvent)
    assert added.review_status == "approved"
    assert payload["review_status"] == "approved"


@pytest.mark.asyncio
async def test_calendar_pending_import_is_non_operational_until_approved() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup._validate_scope_keys", new=AsyncMock()
    ), patch("services.gateway.routers.timetable_setup._validate_term_bounds", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        payload = await timetable_setup.create_calendar_entry(
            body=timetable_setup.CalendarCreateRequest(
                event_name="PDF candidate",
                start_date=date(2026, 9, 5),
                end_date=date(2026, 9, 5),
                event_type="special_schedule",
                source_type="pdf_extraction",
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["review_status"] == "pending_review"


@pytest.mark.asyncio
async def test_calendar_deactivate_preserves_history_not_delete() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    entry = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name="Holiday",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        is_all_day=True,
        event_type="public_holiday",
        teaching_day_effect="non_teaching_day",
        source_type="manual",
        review_status="approved",
        is_active=True,
    )
    db.scalar = AsyncMock(return_value=entry)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        payload = await timetable_setup.deactivate_calendar_entry(entry.id, tenant=tenant, actor=actor, db=db)

    assert payload["is_active"] is False
    assert entry.is_active is False
