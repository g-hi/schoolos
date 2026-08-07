from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock()
        self.execute = AsyncMock()
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()


def _tenant() -> SimpleNamespace:
    tid = uuid.uuid4()
    return SimpleNamespace(id=tid)


def _actor(*, tenant_id: uuid.UUID, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=is_active)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "baseline_id"),
    [
        ("standard", None),
        ("customized", None),
        ("repair", uuid.uuid4()),
    ],
)
async def test_generation_modes_supported(mode: str, baseline_id: uuid.UUID | None) -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    body = tg.GenerationConfigurationCreateRequest(
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        bell_schedule_id=None,
        name="Mode Test",
        description=None,
        generation_mode=mode,
        stability_mode="balanced",
        baseline_reference_type="timetable_version" if baseline_id else None,
        baseline_reference_id=baseline_id,
        objective_priorities=[],
        repair_scope={},
        effective_context={},
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()), patch.object(tg, "_require_active_context", new=AsyncMock()), patch.object(tg, "_validate_bell_schedule_scope", new=AsyncMock()), patch.object(tg, "_replace_objectives", new=AsyncMock(return_value=[])), patch.object(tg, "log_action", new=AsyncMock()):
        payload = await tg.create_generation_configuration(body=body, tenant=tenant, actor=actor, db=db)

    assert payload["generation_mode"] == mode


@pytest.mark.asyncio
async def test_repair_mode_requires_baseline() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    body = tg.GenerationConfigurationCreateRequest(
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        bell_schedule_id=None,
        name="Repair Missing Baseline",
        generation_mode="repair",
        stability_mode="balanced",
        baseline_reference_type=None,
        baseline_reference_id=None,
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await tg.create_generation_configuration(body=body, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_unsupported_generation_mode_rejected() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    body = tg.GenerationConfigurationCreateRequest(
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        bell_schedule_id=None,
        name="Bad Mode",
        generation_mode="invalid-mode",
        stability_mode="balanced",
        baseline_reference_type=None,
        baseline_reference_id=None,
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await tg.create_generation_configuration(body=body, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("strength", ["hard", "strong", "normal", "low"])
async def test_teacher_preference_strengths_supported(strength: str) -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    teacher_id = uuid.uuid4()

    db.scalar = AsyncMock(return_value=SimpleNamespace(id=teacher_id, tenant_id=tenant.id))

    body = tg.TeacherPreferenceCreateRequest(
        teacher_id=teacher_id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        preference_type="avoid_selected_periods",
        strength=strength,
        weekdays=[1, 2],
        period_numbers=[2, 3],
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()), patch.object(tg, "_require_active_context", new=AsyncMock()), patch.object(tg, "log_action", new=AsyncMock()):
        payload = await tg.create_teacher_preference(body=body, tenant=tenant, actor=actor, db=db)

    assert payload["strength"] == strength


@pytest.mark.asyncio
async def test_invalid_teacher_preference_strength_rejected() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    body = tg.TeacherPreferenceCreateRequest(
        teacher_id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        preference_type="avoid_selected_periods",
        strength="invalid-strength",
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await tg.create_teacher_preference(body=body, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_department_lock_target_is_rejected() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    body = tg.GenerationLockCreateRequest(
        lock_state="locked",
        target_type="department",
        target_reference_code="science",
    )

    with patch.object(tg, "set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await tg.create_generation_lock(configuration_id=uuid.uuid4(), body=body, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422
