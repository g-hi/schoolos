from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=is_active)


def _config(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        generation_mode="standard",
        stability_mode="balanced",
        lifecycle_status="approved",
        repair_scope_json={"scope_level": "minimum"},
    )


@pytest.mark.asyncio
async def test_problem_summary_route_returns_preview_without_solver_actions() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    config = _config(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=config)

    result_stub = SimpleNamespace(problem=SimpleNamespace(solver_eligible=True, to_dict=lambda: {"problem_id": "p1"}))

    with patch.object(tg, "set_tenant_context", new=AsyncMock()), patch.object(tg, "_run_generation_validation", new=AsyncMock(return_value={"is_valid": True, "policy_generation_allowed": True})), patch.object(tg, "build_scheduling_problem", new=AsyncMock(return_value=result_stub)), patch.object(tg, "summarize_problem", return_value={"counts": {}, "blockers": [], "warnings": []}):
        payload = await tg.preview_scheduling_problem(configuration_id=config.id, tenant=tenant, actor=actor, db=db)

    assert payload["summary"]["solver_eligible"] is True
    assert payload["explicit_non_actions"]["solver_started"] is False
    assert payload["explicit_non_actions"]["candidate_generated"] is False
    assert payload["explicit_non_actions"]["timetable_published"] is False


@pytest.mark.asyncio
async def test_problem_routes_reject_inactive_actor() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, is_active=False)
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        await tg.get_scheduling_problem_summary(configuration_id=uuid.uuid4(), tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 403
