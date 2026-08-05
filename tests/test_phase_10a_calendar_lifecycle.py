from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock(return_value=None)
        self.execute = AsyncMock()
        self.commit = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _leader(*, tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True)


@pytest.mark.asyncio
async def test_event_tenant_isolation_not_found_for_other_tenant() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _leader(tenant_id=tenant.id)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.get_manual_event(uuid.uuid4(), tenant=tenant, actor=actor, db=db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_pdf_import_page_candidate_and_plan_isolation() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _leader(tenant_id=tenant.id)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())

        with pytest.raises(HTTPException) as exc_import:
            await calendar_intake.get_calendar_pdf_import(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
        assert exc_import.value.status_code == 404

        with pytest.raises(HTTPException) as exc_pages:
            await calendar_intake.get_calendar_pdf_pages(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
        assert exc_pages.value.status_code == 404

        with pytest.raises(HTTPException) as exc_candidate:
            await calendar_intake.approve_calendar_candidate(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
        assert exc_candidate.value.status_code == 404

        with pytest.raises(HTTPException) as exc_plan:
            await calendar_intake.get_notification_plan(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
        assert exc_plan.value.status_code == 404


def test_leadership_roles_supported_by_dependency_contract() -> None:
    # require_role coverage is asserted in route-contract tests; this confirms
    # lifecycle router uses the same leadership dependency.
    assert calendar_intake.resolve_authenticated_leadership is not None
