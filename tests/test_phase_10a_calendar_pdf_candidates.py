from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarSourcePage


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return type("S", (), {"all": lambda _self: self._rows})()


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock(return_value=uuid.uuid4())
        self.execute = AsyncMock(return_value=_Result([]))


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_pages_route_is_paginated_and_returns_excerpt_not_full_text() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    row = CalendarSourcePage(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source_document_id=uuid.uuid4(),
        page_number=1,
        extracted_text="X" * 4000,
        text_excerpt="X" * 100,
        extracted_char_count=4000,
    )
    db.execute = AsyncMock(return_value=_Result([row]))
    db.scalar = AsyncMock(side_effect=[uuid.uuid4(), 1])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calendar_intake, "set_tenant_context", AsyncMock())
        payload = await calendar_intake.get_calendar_pdf_pages(
            document_id=uuid.uuid4(),
            page=1,
            page_size=10,
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["total"] == 1
    assert payload["items"][0]["text_excerpt"] == "X" * 100
    assert "extracted_text" not in payload["items"][0]
