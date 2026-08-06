from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarNotificationPlan, OperationalCalendarEvent


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
async def test_high_impact_notification_plan_requires_approval() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    event = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name="Exam Change",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 10),
        is_all_day=True,
        event_type="examination_period",
        teaching_day_effect="special_schedule",
        source_type="manual",
        review_status="approved",
        lifecycle_status="published",
        version_number=4,
        impact_scope_json={"scope_type": "whole_school"},
        is_active=True,
    )
    db.scalar = AsyncMock(return_value=event)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        mp.setattr(calendar_intake, "calculate_event_impact", AsyncMock(return_value={"affected_count": 1200, "recommended_channels": ["in_app", "email"]}))
        payload = await calendar_intake.draft_event_notification_plan(
            event.id,
            body=calendar_intake.NotificationPlanDraftRequest(
                trigger_reason="event_cancelled",
                subject="Urgent",
                proposed_message="Exam cancelled",
                channels=["in_app", "email"],
                urgency="critical",
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["approval_required"] is True
    assert payload["approval_status"] == "pending_approval"


@pytest.mark.asyncio
async def test_approve_and_cancel_plan_lifecycle() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    plan = CalendarNotificationPlan(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_id=uuid.uuid4(),
        event_version_number=1,
        trigger_reason="event_published",
        audience_scope={"scope_type": "public_information"},
        affected_count=5,
        subject="Title",
        proposed_message="Body",
        channels=["in_app"],
        reminder_settings={},
        urgency="normal",
        approval_required=True,
        approval_status="pending_approval",
        outbox_status="pending_approval",
        delivery_summary={},
        audit_reference_json={},
    )

    db.scalar = AsyncMock(return_value=plan)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        approved = await calendar_intake.approve_notification_plan(
            plan.id,
            body=calendar_intake.EventStatusReasonRequest(reason="checked"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert approved["approval_status"] == "approved"

        cancelled = await calendar_intake.cancel_notification_plan(
            plan.id,
            body=calendar_intake.EventStatusReasonRequest(reason="stop"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert cancelled["approval_status"] == "cancelled"
