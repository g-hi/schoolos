from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup
from shared.db.models import Class, WeeklyTeachingRequirement


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
async def test_positive_sessions_required() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_teaching_requirement(
                body=timetable_setup.TeachingRequirementCreateRequest(
                    campus_id=uuid.uuid4(),
                    academic_year_id=uuid.uuid4(),
                    term_id=uuid.uuid4(),
                    class_id=uuid.uuid4(),
                    subject_id=uuid.uuid4(),
                    sessions_per_week=0,
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_active_requirement_prevented() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    body = timetable_setup.TeachingRequirementCreateRequest(
        campus_id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        sessions_per_week=5,
    )

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup._validate_requirement_scope", new=AsyncMock(return_value=(Class(id=body.class_id, tenant_id=tenant.id, grade="8", section="A", academic_year="2026-2027", is_active=True), object()))
    ):
        db.scalar = AsyncMock(return_value=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_teaching_requirement(body=body, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_tenant_scope_mismatch_rejected() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    body = timetable_setup.TeachingRequirementCreateRequest(
        campus_id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        sessions_per_week=5,
        specialist_room_type="science_lab",
    )

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup._validate_requirement_scope(db=db, tenant_id=tenant.id, body=body)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_inactive_room_requirement_rejected() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    req = WeeklyTeachingRequirement(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        teacher_id=None,
        sessions_per_week=4,
        periods_per_session=1,
        min_daily_sessions=0,
        max_daily_sessions=2,
        double_period_mode="none",
        specialist_room_type=None,
        preferred_period_numbers=[],
        forbidden_period_numbers=[],
        has_fixed_sessions=False,
        fixed_session_rules=[],
        priority=100,
        source_type="manual",
        review_status="approved",
        is_active=True,
    )
    db.scalar = AsyncMock(side_effect=[req, None])

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.update_teaching_requirement(
                requirement_id=req.id,
                body=timetable_setup.TeachingRequirementUpdateRequest(specialist_room_type="science_lab"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422
