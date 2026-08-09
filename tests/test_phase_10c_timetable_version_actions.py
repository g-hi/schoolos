from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg
from services.gateway.timetable_setup.timetable_versions import TimetableVersionError


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.commit = AsyncMock()
        self.scalar = AsyncMock(return_value=0)


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True)


@pytest.mark.asyncio
async def test_submit_route_surfaces_controlled_invalid_transition_conflict() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tg,
            "transition_submit",
            new=AsyncMock(
                side_effect=TimetableVersionError(
                    code="invalid_transition",
                    message="Only candidate versions can be submitted.",
                    status_code=409,
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await tg.submit_timetable_version(
                version_id=uuid.uuid4(),
                tenant=tenant,
                actor=actor,
                db=_Db(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "invalid_transition"


@pytest.mark.asyncio
async def test_publish_route_surfaces_same_date_overlap_conflict() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tg,
            "transition_publish",
            new=AsyncMock(
                side_effect=TimetableVersionError(
                    code="publication_overlap_same_date",
                    message="A published version already exists for the same effective date.",
                    status_code=409,
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await tg.publish_timetable_version(
                version_id=uuid.uuid4(),
                body=tg.PublishTimetableVersionRequest(effective_from="2026-10-01"),
                tenant=tenant,
                actor=actor,
                db=_Db(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "publication_overlap_same_date"
