from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_policies as policies


@pytest.mark.asyncio
async def test_scope_validation_rejects_missing_reference_for_teacher_scope() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await policies._validate_constraint_scope_reference(
            db=db,
            tenant_id=uuid.uuid4(),
            scope_type="teacher",
            scope_reference_id=None,
            scope_reference_code=None,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_scope_validation_rejects_out_of_tenant_reference() -> None:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await policies._validate_constraint_scope_reference(
            db=db,
            tenant_id=uuid.uuid4(),
            scope_type="class",
            scope_reference_id=uuid.uuid4(),
            scope_reference_code=None,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_scope_validation_accepts_department_code_scope() -> None:
    db = AsyncMock()
    await policies._validate_constraint_scope_reference(
        db=db,
        tenant_id=uuid.uuid4(),
        scope_type="department",
        scope_reference_id=None,
        scope_reference_code="science",
    )


def test_invalid_policy_effective_date_range_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        policies._validate_date_range(start_date=policies.date_type(2026, 9, 3), end_date=policies.date_type(2026, 9, 2))
    assert exc.value.status_code == 422
