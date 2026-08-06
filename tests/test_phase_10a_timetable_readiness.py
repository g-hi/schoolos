from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from services.gateway.timetable_setup import readiness


def _count_stub(values: list[int]):
    iterator = iter(values)

    async def _inner(db, stmt):
        del db, stmt
        return next(iterator)

    return _inner


@pytest.mark.asyncio
async def test_empty_tenant_has_blockers() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=type("Result", (), {"scalars": lambda self: type("S", (), {"all": lambda _: []})()})())

    # Keep counts zero for all scalar checks.
    values = [0] * 16
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_timetable_input_readiness(db, tenant_id)

    assert result["blocker_count"] > 0
    assert result["is_generation_ready"] is False


@pytest.mark.asyncio
async def test_manual_complete_setup_can_clear_blockers() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return type("S", (), {"all": lambda _self: self._rows})()

        def all(self):
            return self._rows

    db.execute = AsyncMock(side_effect=[_Result([]), _Result([])])

    # Non-zero values for blocker checks, no duplicates/conflicts.
    values = [3, 0, 1, 1, 5, 2, 6, 4, 0, 0, 0, 0, 0, 1, 1, 4]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_timetable_input_readiness(db, tenant_id)

    assert result["blocker_count"] == 0
    assert result["is_generation_ready"] is True


@pytest.mark.asyncio
async def test_pending_calendar_is_warning_not_operational() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return type("S", (), {"all": lambda _self: self._rows})()

        def all(self):
            return self._rows

    db.execute = AsyncMock(side_effect=[_Result([]), _Result([])])

    values = [1, 2, 1, 1, 5, 0, 4, 0, 0, 0, 0, 0, 1, 0, 1, 4]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_timetable_input_readiness(db, tenant_id)

    pending = [item for item in result["checks"] if item["check_key"] == "calendar_pending_review"][0]
    assert pending["severity"] == "warning"
    assert pending["status"] == "attention"


@pytest.mark.asyncio
async def test_other_tenant_records_not_counted_by_contract() -> None:
    tenant_id = uuid.uuid4()
    captured_tenant_ids: list[uuid.UUID] = []
    db = AsyncMock()

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return type("S", (), {"all": lambda _self: self._rows})()

        def all(self):
            return self._rows

    async def _exec(stmt):
        params = stmt.compile().params
        for key, value in params.items():
            if key.startswith("tenant_id") and isinstance(value, uuid.UUID):
                captured_tenant_ids.append(value)
        return _Result([])

    db.execute = AsyncMock(side_effect=_exec)

    async def _count_with_capture(_db, stmt):
        params = stmt.compile().params
        for key, value in params.items():
            if key.startswith("tenant_id") and isinstance(value, uuid.UUID):
                captured_tenant_ids.append(value)
        return 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_with_capture)
        await readiness.compute_timetable_input_readiness(db, tenant_id)

    assert captured_tenant_ids
    assert all(value == tenant_id for value in captured_tenant_ids)
