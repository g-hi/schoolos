from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import OperationalCalendarEvent


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


def _user(*, tenant_id: uuid.UUID, role: str = "principal", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active)


@pytest.mark.asyncio
async def test_manual_event_starts_as_draft_non_operational() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=uuid.uuid4())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        payload = await calendar_intake.create_manual_event(
            body=calendar_intake.ManualEventCreateRequest(
                event_name="Term Opening",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 1),
                event_type="term_boundary",
                scope=calendar_intake.EventScope(scope_type="public_information", public_information=True),
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["lifecycle_status"] == "draft"
    assert payload["review_status"] == "pending_review"


@pytest.mark.asyncio
async def test_submit_approve_publish_are_separate_actions() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    event = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name="Event",
        start_date=date(2026, 9, 2),
        end_date=date(2026, 9, 2),
        is_all_day=True,
        event_type="school_event",
        teaching_day_effect="no_change",
        source_type="manual",
        review_status="pending_review",
        lifecycle_status="draft",
        version_number=1,
        impact_scope_json={"scope_type": "public_information"},
        is_active=True,
    )

    async def _scalar(_stmt):
        return event

    db.scalar = AsyncMock(side_effect=_scalar)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        mp.setattr(calendar_intake, "calculate_event_impact", AsyncMock(return_value={"affected_count": 0, "recommended_channels": ["in_app"]}))
        await calendar_intake.submit_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Ready"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "pending_review"

        await calendar_intake.approve_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Approved"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "approved"

        await calendar_intake.publish_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Publish"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "published"


@pytest.mark.asyncio
async def test_reschedule_cancel_restore_archive_lifecycle() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    event = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name="Event",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        is_all_day=True,
        event_type="school_event",
        teaching_day_effect="no_change",
        source_type="manual",
        review_status="approved",
        lifecycle_status="published",
        version_number=2,
        impact_scope_json={"scope_type": "public_information"},
        is_active=True,
    )
    db.scalar = AsyncMock(return_value=event)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        mp.setattr(calendar_intake, "calculate_event_impact", AsyncMock(return_value={"affected_count": 0, "recommended_channels": ["in_app"]}))
        await calendar_intake.reschedule_manual_event(
            event.id,
            body=calendar_intake.EventRescheduleRequest(new_start_date=date(2026, 10, 2), new_end_date=date(2026, 10, 2), reason="Move"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert event.lifecycle_status == "rescheduled"

        await calendar_intake.cancel_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Cancel"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "cancelled"

        await calendar_intake.restore_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Restore"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "approved"

        await calendar_intake.archive_manual_event(event.id, body=calendar_intake.EventStatusReasonRequest(reason="Archive"), tenant=tenant, actor=actor, db=db)
        assert event.lifecycle_status == "archived"
        assert event.is_active is False


def test_non_leadership_roles_rejected_by_role_dependency_contract() -> None:
    dep = calendar_intake.resolve_authenticated_leadership
    assert dep is not None


def test_inactive_or_cross_tenant_actor_rejected() -> None:
    tenant = _tenant()
    inactive = _user(tenant_id=tenant.id, is_active=False)
    with pytest.raises(HTTPException):
        calendar_intake._ensure_actor_tenant(inactive, tenant)

    wrong = _user(tenant_id=uuid.uuid4(), is_active=True)
    with pytest.raises(HTTPException):
        calendar_intake._ensure_actor_tenant(wrong, tenant)


@pytest.mark.asyncio
async def test_scope_references_cannot_cross_tenant() -> None:
    db = _Db()
    tenant = _tenant()
    # Empty execute result simulates class IDs not found under tenant scope.
    db.execute = AsyncMock(return_value=type("R", (), {"scalars": lambda self: type("S", (), {"all": lambda _self: []})()})())

    with pytest.raises(HTTPException) as exc:
        await calendar_intake._validate_scope(
            db=db,
            tenant_id=tenant.id,
            scope=calendar_intake.EventScope(scope_type="classes", classes=[uuid.uuid4()]),
        )

    assert exc.value.status_code == 422
