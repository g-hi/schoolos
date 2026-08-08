from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active)


@pytest.mark.asyncio
async def test_non_principal_cannot_approve_timetable_version() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="school_admin", is_active=True)

    with pytest.raises(HTTPException) as exc:
        await tg.approve_timetable_version(
            version_id=uuid.uuid4(),
            tenant=tenant,
            actor=actor,
            db=_Db(),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_non_principal_cannot_publish_timetable_version() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="school_admin", is_active=True)

    with pytest.raises(HTTPException) as exc:
        await tg.publish_timetable_version(
            version_id=uuid.uuid4(),
            body=tg.PublishTimetableVersionRequest(effective_from="2026-09-01"),
            tenant=tenant,
            actor=actor,
            db=_Db(),
        )

    assert exc.value.status_code == 403
