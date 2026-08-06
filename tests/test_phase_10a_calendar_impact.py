from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from services.gateway.calendar.impact import calculate_event_impact


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_whole_school_impact_and_privacy_note() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result([("teacher", 5), ("parent", 12)]))

    result = await calculate_event_impact(
        db=db,
        tenant_id=uuid.uuid4(),
        scope={"scope_type": "whole_school", "contains_confidential_staffing": True},
    )

    assert result["affected_count"] == 17
    assert "teacher" in result["audience_categories"]
    assert any("Confidential staffing" in note for note in result["privacy_notes"])


@pytest.mark.asyncio
async def test_selected_user_scope_reports_zero_and_unresolved() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result([]))

    result = await calculate_event_impact(
        db=db,
        tenant_id=uuid.uuid4(),
        scope={"scope_type": "selected_users", "selected_users": [str(uuid.uuid4())]},
    )

    assert result["affected_count"] == 0
    assert result["unresolved_targeting_issues"]


@pytest.mark.asyncio
async def test_staff_role_scope_breakdown() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result([("teacher", 7), ("staff", 2)]))

    result = await calculate_event_impact(
        db=db,
        tenant_id=uuid.uuid4(),
        scope={"scope_type": "staff_roles", "staff_roles": ["teacher", "staff"]},
    )

    assert result["role_breakdown"]["teacher"] == 7
    assert result["role_breakdown"]["staff"] == 2
