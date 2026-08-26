"""Deterministic TeacherAbsence lifecycle service for Phase 10E-1B."""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.db.models import Teacher, TeacherAbsence, User


class TeacherAbsenceError(Exception):
    """Controlled, HTTP-independent errors for absence lifecycle operations."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


_VALID_SCOPE_TYPES = {"whole_day", "selected_periods"}


def _validate_selected_periods(
    *, scope_type: str, selected_periods: list[Any] | None
) -> list[Any] | None:
    if scope_type not in _VALID_SCOPE_TYPES:
        raise TeacherAbsenceError("absence_scope_invalid")
    if scope_type == "whole_day":
        if selected_periods is not None:
            raise TeacherAbsenceError("absence_selected_periods_not_allowed")
        return None
    if not isinstance(selected_periods, list) or not selected_periods:
        raise TeacherAbsenceError("absence_selected_periods_required")

    normalized: list[Any] = []
    seen: set[tuple[str, object]] = set()
    for period in selected_periods:
        if isinstance(period, bool) or not isinstance(period, (int, str)):
            raise TeacherAbsenceError("absence_selected_periods_invalid")
        if isinstance(period, int):
            if period <= 0:
                raise TeacherAbsenceError("absence_selected_periods_invalid")
            key = ("int", period)
        else:
            value = period.strip()
            if not value or len(value) > 120:
                raise TeacherAbsenceError("absence_selected_periods_invalid")
            key = ("str", value)
            period = value
        if key in seen:
            raise TeacherAbsenceError("absence_selected_periods_invalid")
        seen.add(key)
        normalized.append(period)
    return normalized


async def _load_teacher(
    db: AsyncSession, *, tenant_id: uuid.UUID, teacher_id: uuid.UUID
) -> Teacher:
    teacher = await db.scalar(
        select(Teacher).where(Teacher.id == teacher_id, Teacher.tenant_id == tenant_id)
    )
    if teacher is None:
        raise TeacherAbsenceError("teacher_not_found")
    return teacher


async def _validate_actor(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID | None
) -> None:
    if actor_id is None:
        return
    actor = await db.scalar(
        select(User).where(User.id == actor_id, User.tenant_id == tenant_id)
    )
    if actor is None:
        raise TeacherAbsenceError("actor_not_found")


async def _load_absence(
    db: AsyncSession, *, tenant_id: uuid.UUID, absence_id: uuid.UUID
) -> TeacherAbsence:
    absence = await db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.id == absence_id,
            TeacherAbsence.tenant_id == tenant_id,
        )
    )
    if absence is None:
        raise TeacherAbsenceError("absence_not_found")
    return absence


async def report_absence(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    start_date: date_type,
    end_date: date_type,
    scope_type: str,
    selected_periods: list[Any] | None = None,
    reason_code: str,
    private_note: str | None = None,
    source_type: str,
    reported_by_user_id: uuid.UUID | None = None,
) -> TeacherAbsence:
    """Create a reported absence, returning an exact duplicate idempotently."""
    if start_date > end_date:
        raise TeacherAbsenceError("absence_date_range_invalid")
    normalized_periods = _validate_selected_periods(
        scope_type=scope_type, selected_periods=selected_periods
    )
    await _load_teacher(db, tenant_id=tenant_id, teacher_id=teacher_id)
    await _validate_actor(
        db, tenant_id=tenant_id, actor_id=reported_by_user_id
    )

    candidates = await db.execute(
        select(TeacherAbsence).where(
            TeacherAbsence.tenant_id == tenant_id,
            TeacherAbsence.teacher_id == teacher_id,
            TeacherAbsence.start_date == start_date,
            TeacherAbsence.end_date == end_date,
            TeacherAbsence.status.in_(("reported", "confirmed")),
        )
    )
    for existing in candidates.scalars().all():
        if (
            existing.status in {"reported", "confirmed"}
            and
            existing.scope_type == scope_type
            and existing.selected_periods == normalized_periods
            and existing.reason_code == reason_code
            and existing.private_note == private_note
            and existing.source_type == source_type
        ):
            return existing

    absence = TeacherAbsence(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        start_date=start_date,
        end_date=end_date,
        scope_type=scope_type,
        selected_periods=normalized_periods,
        reason_code=reason_code,
        private_note=private_note,
        source_type=source_type,
        reported_by_user_id=reported_by_user_id,
        status="reported",
        reported_at=datetime.now(timezone.utc),
    )
    db.add(absence)
    await db.flush()
    await log_action(
        db=db,
        tenant_id=tenant_id,
        action="absence_reported",
        entity_type="TeacherAbsence",
        entity_id=absence.id,
        actor_id=reported_by_user_id,
        details={
            "teacher_id": str(teacher_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "scope_type": scope_type,
            "source_type": source_type,
            "status": absence.status,
        },
    )
    await db.commit()
    return absence


async def confirm_absence(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    absence_id: uuid.UUID,
    confirmed_by_user_id: uuid.UUID | None = None,
) -> TeacherAbsence:
    """Confirm a reported absence; repeated confirmation is idempotent."""
    absence = await _load_absence(db, tenant_id=tenant_id, absence_id=absence_id)
    if absence.status == "confirmed":
        return absence
    if absence.status != "reported":
        raise TeacherAbsenceError("absence_transition_invalid")
    await _validate_actor(
        db, tenant_id=tenant_id, actor_id=confirmed_by_user_id
    )
    absence.status = "confirmed"
    absence.confirmed_by_user_id = confirmed_by_user_id
    absence.confirmed_at = datetime.now(timezone.utc)
    await db.flush()
    await log_action(
        db=db,
        tenant_id=tenant_id,
        action="absence_confirmed",
        entity_type="TeacherAbsence",
        entity_id=absence.id,
        actor_id=confirmed_by_user_id,
        details={"status": absence.status},
    )
    await db.commit()
    return absence


async def cancel_absence(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    absence_id: uuid.UUID,
    cancelled_by_user_id: uuid.UUID | None = None,
) -> TeacherAbsence:
    """Cancel a reported or confirmed absence; repeated cancellation is idempotent."""
    absence = await _load_absence(db, tenant_id=tenant_id, absence_id=absence_id)
    if absence.status == "cancelled":
        return absence
    if absence.status not in {"reported", "confirmed"}:
        raise TeacherAbsenceError("absence_transition_invalid")
    await _validate_actor(
        db, tenant_id=tenant_id, actor_id=cancelled_by_user_id
    )
    absence.status = "cancelled"
    absence.cancelled_by_user_id = cancelled_by_user_id
    absence.cancelled_at = datetime.now(timezone.utc)
    await db.flush()
    await log_action(
        db=db,
        tenant_id=tenant_id,
        action="absence_cancelled",
        entity_type="TeacherAbsence",
        entity_id=absence.id,
        actor_id=cancelled_by_user_id,
        details={"status": absence.status},
    )
    await db.commit()
    return absence


async def close_absence(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    absence_id: uuid.UUID,
) -> TeacherAbsence:
    """Close only a confirmed absence; repeated close is idempotent."""
    absence = await _load_absence(db, tenant_id=tenant_id, absence_id=absence_id)
    if absence.status == "closed":
        return absence
    if absence.status != "confirmed":
        raise TeacherAbsenceError("absence_transition_invalid")
    absence.status = "closed"
    await db.flush()
    await log_action(
        db=db,
        tenant_id=tenant_id,
        action="absence_closed",
        entity_type="TeacherAbsence",
        entity_id=absence.id,
        actor_id=None,
        details={"status": absence.status},
    )
    await db.commit()
    return absence
