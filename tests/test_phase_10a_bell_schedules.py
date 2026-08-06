from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup
from shared.db.models import BellSchedule, BellSchedulePeriod


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
async def test_bell_schedule_effective_date_validation() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_bell_schedule(
                body=timetable_setup.BellScheduleCreateRequest(
                    name="Ramadan",
                    effective_start_date=date(2026, 10, 10),
                    effective_end_date=date(2026, 10, 1),
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_period_overlap_rejected() -> None:
    db = _Db()
    tenant = _tenant()

    existing_period = BellSchedulePeriod(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        bell_schedule_id=uuid.uuid4(),
        period_number=1,
        label="P1",
        start_time="08:00",
        end_time="08:45",
        is_teaching_period=True,
        is_break=False,
        is_lunch=False,
        is_active=True,
    )

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return SimpleNamespace(all=lambda: self._rows)

    db.execute = AsyncMock(return_value=_Result([existing_period]))

    with pytest.raises(HTTPException) as exc:
        await timetable_setup._validate_period_overlap(
            db=db,
            tenant_id=tenant.id,
            bell_schedule_id=existing_period.bell_schedule_id,
            period_id=None,
            start_time="08:30",
            end_time="09:00",
            is_active=True,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_break_period_forces_non_teaching() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    schedule = BellSchedule(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Normal",
        schedule_type="normal",
        source_type="manual",
        review_status="approved",
        is_active=True,
    )
    db.scalar = AsyncMock(side_effect=[schedule, None])

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup._validate_period_overlap", new=AsyncMock()
    ), patch("services.gateway.routers.timetable_setup.log_action", new=AsyncMock()):
        payload = await timetable_setup.create_schedule_period(
            schedule_id=schedule.id,
            body=timetable_setup.BellSchedulePeriodCreateRequest(
                period_number=2,
                label="Break",
                start_time="09:30",
                end_time="09:45",
                is_teaching_period=True,
                is_break=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["is_break"] is True
    assert payload["is_teaching_period"] is False


@pytest.mark.asyncio
async def test_duplicate_period_number_rejected() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    schedule = BellSchedule(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Normal",
        schedule_type="normal",
        source_type="manual",
        review_status="approved",
        is_active=True,
    )
    db.scalar = AsyncMock(side_effect=[schedule, uuid.uuid4()])

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_schedule_period(
                schedule_id=schedule.id,
                body=timetable_setup.BellSchedulePeriodCreateRequest(
                    period_number=1,
                    label="P1",
                    start_time="08:00",
                    end_time="08:40",
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 409
