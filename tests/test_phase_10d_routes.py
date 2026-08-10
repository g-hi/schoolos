"""Tests for Phase 10D daily-sessions API routes."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_daily_sessions as tds
from services.gateway.timetable_setup.daily_sessions import (
    DailySessionError,
    MaterializationOutcome,
)


def _tenant() -> SimpleNamespace:
    tid = uuid.uuid4()
    return SimpleNamespace(id=tid)


def _principal(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="principal",
        is_active=True,
    )


def _non_principal(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="teacher",
        is_active=True,
    )


def _db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _osd(*, tenant_id: uuid.UUID, version_id: uuid.UUID, school_date: date) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        timetable_id=uuid.uuid4(),
        timetable_version_id=version_id,
        campus_id=None,
        school_date=school_date,
        day_of_week=school_date.weekday(),
        timetable_day_key="d0",
        bell_schedule_id=None,
        is_teaching_day=True,
        non_teaching_reason=None,
        materialization_status="complete",
        materialized_at=datetime(2026, 9, 7, 8, 0, 0, tzinfo=timezone.utc),
        source_fingerprint="a" * 64,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /materialize
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_materialize_created_returns_200_with_status() -> None:
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()
    version_id = uuid.uuid4()
    school_date = date(2026, 9, 7)
    osd = _osd(tenant_id=tenant.id, version_id=version_id, school_date=school_date)
    outcome = MaterializationOutcome(osd=osd, session_count=5, status="created")

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(tds, "materialize_operational_day", new=AsyncMock(return_value=outcome)),
        patch.object(tds, "log_action", new=AsyncMock()),
    ):
        result = await tds.materialize_daily_sessions(
            body=tds.MaterializeRequest(
                timetable_id=version_id,
                school_date=school_date,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert result["status"] == "created"
    assert result["school_date"] == school_date.isoformat()
    assert result["session_count"] == 5
    assert result["is_teaching_day"] is True


@pytest.mark.asyncio
async def test_materialize_already_materialized_returns_200_with_status() -> None:
    """Same inputs as before -> already_materialized, no audit log written."""
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()
    version_id = uuid.uuid4()
    school_date = date(2026, 9, 7)
    osd = _osd(tenant_id=tenant.id, version_id=version_id, school_date=school_date)
    outcome = MaterializationOutcome(osd=osd, session_count=5, status="already_materialized")

    log_mock = AsyncMock()

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(tds, "materialize_operational_day", new=AsyncMock(return_value=outcome)),
        patch.object(tds, "log_action", new=log_mock),
    ):
        result = await tds.materialize_daily_sessions(
            body=tds.MaterializeRequest(
                timetable_id=version_id,
                school_date=school_date,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert result["status"] == "already_materialized"
    assert result["session_count"] == 5
    # Audit log must NOT be written for idempotent re-calls
    log_mock.assert_not_called()


@pytest.mark.asyncio
async def test_materialize_stale_returns_409_with_code() -> None:
    """Changed inputs -> 409 school_day_stale, existing sessions untouched."""
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tds,
            "materialize_operational_day",
            new=AsyncMock(
                side_effect=DailySessionError("school_day_stale", "Stale.", 409)
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await tds.materialize_daily_sessions(
                body=tds.MaterializeRequest(
                    timetable_id=uuid.uuid4(),
                    school_date=date(2026, 9, 7),
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "school_day_stale"


@pytest.mark.asyncio
async def test_materialize_raises_403_for_non_principal() -> None:
    tenant = _tenant()
    actor = _non_principal(tenant_id=tenant.id)
    db = _db()

    with pytest.raises(HTTPException) as exc_info:
        await tds.materialize_daily_sessions(
            body=tds.MaterializeRequest(
                timetable_id=uuid.uuid4(),
                school_date=date(2026, 9, 7),
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_materialize_propagates_version_not_found_as_404() -> None:
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tds,
            "materialize_operational_day",
            new=AsyncMock(
                side_effect=DailySessionError("version_not_found", "Not found.", 404)
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await tds.materialize_daily_sessions(
                body=tds.MaterializeRequest(
                    timetable_id=uuid.uuid4(),
                    school_date=date(2026, 9, 7),
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "version_not_found"


@pytest.mark.asyncio
async def test_materialize_propagates_version_not_published_as_409() -> None:
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tds,
            "materialize_operational_day",
            new=AsyncMock(
                side_effect=DailySessionError(
                    "version_not_published",
                    "Must be published.",
                    409,
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await tds.materialize_daily_sessions(
                body=tds.MaterializeRequest(
                    timetable_id=uuid.uuid4(),
                    school_date=date(2026, 9, 7),
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "version_not_published"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# GET /
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.asyncio
async def test_get_daily_sessions_returns_404_when_not_materialized() -> None:
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(tds, "load_operational_day_with_sessions", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await tds.get_daily_sessions(
                timetable_id=uuid.uuid4(),
                school_date=date(2026, 9, 7),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "operational_day_not_found"


@pytest.mark.asyncio
async def test_get_daily_sessions_returns_sessions_list() -> None:
    tenant = _tenant()
    actor = _principal(tenant_id=tenant.id)
    db = _db()
    version_id = uuid.uuid4()
    school_date = date(2026, 9, 7)
    osd = _osd(tenant_id=tenant.id, version_id=version_id, school_date=school_date)

    def _session(period: int, class_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            timetable_version_assignment_id=None,
            school_date=school_date,
            class_id=class_id,
            subject_id="sub_x",
            teacher_id="teacher_y",
            room_id=None,
            period_number=period,
            period_start_time="08:00",
            period_end_time="08:50",
            periods_span=1,
            parallel_block_id=None,
            parallel_child_id=None,
            session_key=f"{class_id}|d0:p{period}",
            class_facing_session_key="a" * 64,
            session_status="scheduled",
            override_reason=None,
        )

    sessions = [_session(1, "class_7a"), _session(1, "class_7b")]

    with (
        patch.object(tds, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tds,
            "load_operational_day_with_sessions",
            new=AsyncMock(return_value=(osd, sessions)),
        ),
    ):
        result = await tds.get_daily_sessions(
            timetable_id=version_id,
            school_date=school_date,
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert result["operational_school_day"]["school_date"] == school_date.isoformat()
    assert result["operational_school_day"]["session_count"] == 2
    assert len(result["sessions"]) == 2
    assert result["sessions"][0]["class_id"] == "class_7a"
    assert result["sessions"][1]["class_id"] == "class_7b"


@pytest.mark.asyncio
async def test_get_daily_sessions_raises_403_for_non_principal() -> None:
    tenant = _tenant()
    actor = _non_principal(tenant_id=tenant.id)
    db = _db()

    with pytest.raises(HTTPException) as exc_info:
        await tds.get_daily_sessions(
            timetable_id=uuid.uuid4(),
            school_date=date(2026, 9, 7),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert exc_info.value.status_code == 403


def _tenant() -> SimpleNamespace:
    tid = uuid.uuid4()
    return SimpleNamespace(id=tid)


def _principal(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="principal",
        is_active=True,
    )
