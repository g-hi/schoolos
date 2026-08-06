from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarEventVersion, OperationalCalendarEvent


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.execute = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_created_change_writes_immutable_version_row() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=uuid.uuid4())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        await calendar_intake.create_manual_event(
            body=calendar_intake.ManualEventCreateRequest(
                event_name="Event",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 1),
                event_type="school_event",
                scope=calendar_intake.EventScope(scope_type="public_information", public_information=True),
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    added = [call.args[0] for call in db.add.call_args_list]
    version_rows = [item for item in added if isinstance(item, CalendarEventVersion)]
    assert version_rows
    assert version_rows[0].change_type == "created"


@pytest.mark.asyncio
async def test_publish_records_published_change_type() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    event = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name="Publish",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 1),
        is_all_day=True,
        event_type="school_event",
        teaching_day_effect="no_change",
        source_type="manual",
        review_status="approved",
        lifecycle_status="approved",
        version_number=2,
        impact_scope_json={"scope_type": "public_information"},
        is_active=True,
    )
    db.scalar = AsyncMock(return_value=event)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        mp.setattr(calendar_intake, "calculate_event_impact", AsyncMock(return_value={"affected_count": 0, "recommended_channels": ["in_app"]}))
        await calendar_intake.publish_manual_event(
            event.id,
            body=calendar_intake.EventStatusReasonRequest(reason="Publish"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    added = [call.args[0] for call in db.add.call_args_list]
    version_rows = [item for item in added if isinstance(item, CalendarEventVersion)]
    assert any(row.change_type == "published" for row in version_rows)
