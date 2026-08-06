from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_setup
from shared.db.models import TeachingRoom


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
async def test_room_capacity_cannot_be_negative() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_room(
                body=timetable_setup.RoomCreateRequest(
                    room_code="LAB1",
                    room_name="Lab 1",
                    room_type="science_lab",
                    capacity=-1,
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_room_uniqueness_conflict_raises_409() -> None:
    db = _Db()
    db.commit = AsyncMock(side_effect=timetable_setup.IntegrityError("dup", {}, None))
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        with pytest.raises(HTTPException) as exc:
            await timetable_setup.create_room(
                body=timetable_setup.RoomCreateRequest(
                    room_code="A-101",
                    room_name="A 101",
                    room_type="standard_classroom",
                    capacity=30,
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_inactive_room_kept_for_history_not_deleted() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    room = TeachingRoom(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        room_code="B-201",
        room_name="B 201",
        room_type="standard_classroom",
        capacity=28,
        specialist_capabilities=[],
        source_type="manual",
        review_status="approved",
        is_active=True,
    )
    db.scalar = AsyncMock(return_value=room)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        payload = await timetable_setup.deactivate_room(room.id, tenant=tenant, actor=actor, db=db)

    assert payload["is_active"] is False
    assert room.is_active is False


@pytest.mark.asyncio
async def test_specialist_capabilities_preserved_structured() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    with patch("services.gateway.routers.timetable_setup.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup.log_action", new=AsyncMock()
    ):
        payload = await timetable_setup.create_room(
            body=timetable_setup.RoomCreateRequest(
                room_code="SCI-1",
                room_name="Science Lab 1",
                room_type="science_lab",
                capacity=24,
                specialist_capabilities=["gas", "fume_hood", "lab_benches"],
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["specialist_capabilities"] == ["gas", "fume_hood", "lab_benches"]
