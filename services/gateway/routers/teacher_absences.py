"""Protected TeacherAbsence APIs for Phase 10E-1C."""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.timetable.teacher_absences import (
    TeacherAbsenceError,
    cancel_absence,
    close_absence,
    confirm_absence,
    report_absence,
)
from shared.auth.dependencies import resolve_authenticated_leadership, resolve_authenticated_teacher
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Teacher, TeacherAbsence, Tenant, User


teacher_router = APIRouter(prefix="/teacher/operations/absences", tags=["Teacher Absences"])
leadership_router = APIRouter(prefix="/leadership/operations/absences", tags=["Teacher Absences"])


class TeacherAbsenceReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date_type
    end_date: date_type
    scope_type: str
    selected_periods: list[Any] | None = None
    reason_code: str = Field(min_length=1, max_length=50)
    private_note: str | None = None


class LeadershipAbsenceReportRequest(TeacherAbsenceReportRequest):
    teacher_id: uuid.UUID


class TeacherAbsenceResponse(BaseModel):
    id: uuid.UUID
    teacher_id: uuid.UUID
    start_date: date_type
    end_date: date_type
    scope_type: str
    selected_periods: list[Any] | None
    reason_code: str
    private_note: str | None
    status: str
    source_type: str
    reported_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TeacherAbsenceListResponse(BaseModel):
    items: list[TeacherAbsenceResponse]
    page: int
    page_size: int


def _assert_tenant_user(*, actor: User, tenant: Tenant) -> None:
    if not actor.is_active or actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _map_absence_error(exc: TeacherAbsenceError) -> HTTPException:
    if exc.code in {"absence_not_found", "teacher_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "actor_not_found":
        code = status.HTTP_403_FORBIDDEN
    elif exc.code == "absence_transition_invalid":
        code = status.HTTP_409_CONFLICT
    elif exc.code.startswith("absence_"):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail={"code": exc.code, "message": "Absence operation could not be completed."})


def _serialize_absence(absence: TeacherAbsence) -> dict[str, Any]:
    return {
        "id": absence.id,
        "teacher_id": absence.teacher_id,
        "start_date": absence.start_date,
        "end_date": absence.end_date,
        "scope_type": absence.scope_type,
        "selected_periods": absence.selected_periods,
        "reason_code": absence.reason_code,
        "private_note": absence.private_note,
        "status": absence.status,
        "source_type": absence.source_type,
        "reported_at": absence.reported_at,
        "confirmed_at": absence.confirmed_at,
        "cancelled_at": absence.cancelled_at,
        "created_at": absence.created_at,
        "updated_at": absence.updated_at,
    }


async def _teacher_profile(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Teacher:
    teacher = await db.scalar(
        select(Teacher).where(Teacher.tenant_id == tenant_id, Teacher.user_id == user_id)
    )
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher profile not found.")
    return teacher


async def _load_scoped_absence(
    db: AsyncSession, *, tenant_id: uuid.UUID, absence_id: uuid.UUID, teacher_id: uuid.UUID | None = None
) -> TeacherAbsence:
    stmt = select(TeacherAbsence).where(
        TeacherAbsence.id == absence_id,
        TeacherAbsence.tenant_id == tenant_id,
    )
    if teacher_id is not None:
        stmt = stmt.where(TeacherAbsence.teacher_id == teacher_id)
    absence = await db.scalar(stmt)
    if absence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Absence not found.")
    return absence


def _list_statement(
    *, tenant_id: uuid.UUID, teacher_id: uuid.UUID | None, status_filter: str | None,
    date_from: date_type | None, date_to: date_type | None,
):
    stmt = select(TeacherAbsence).where(TeacherAbsence.tenant_id == tenant_id)
    if teacher_id is not None:
        stmt = stmt.where(TeacherAbsence.teacher_id == teacher_id)
    if status_filter is not None:
        stmt = stmt.where(TeacherAbsence.status == status_filter)
    if date_from is not None:
        stmt = stmt.where(TeacherAbsence.end_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(TeacherAbsence.start_date <= date_to)
    return stmt.order_by(TeacherAbsence.start_date.desc(), TeacherAbsence.id.desc())


@teacher_router.post("", response_model=TeacherAbsenceResponse, status_code=status.HTTP_201_CREATED)
async def report_teacher_absence(
    body: TeacherAbsenceReportRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> TeacherAbsence:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    teacher = await _teacher_profile(db, tenant_id=tenant.id, user_id=actor.id)
    try:
        return await report_absence(
            db,
            tenant_id=tenant.id,
            teacher_id=teacher.id,
            start_date=body.start_date,
            end_date=body.end_date,
            scope_type=body.scope_type,
            selected_periods=body.selected_periods,
            reason_code=body.reason_code,
            private_note=body.private_note,
            source_type="teacher",
            reported_by_user_id=actor.id,
        )
    except TeacherAbsenceError as exc:
        raise _map_absence_error(exc) from exc


@teacher_router.get("", response_model=TeacherAbsenceListResponse)
async def list_teacher_absences(
    status_filter: str | None = Query(None, alias="status"),
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    teacher = await _teacher_profile(db, tenant_id=tenant.id, user_id=actor.id)
    result = await db.execute(_list_statement(tenant_id=tenant.id, teacher_id=teacher.id, status_filter=status_filter, date_from=date_from, date_to=date_to).offset((page - 1) * page_size).limit(page_size))
    return {"items": [_serialize_absence(row) for row in result.scalars().all()], "page": page, "page_size": page_size}


@teacher_router.get("/{absence_id}", response_model=TeacherAbsenceResponse)
async def get_teacher_absence(
    absence_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    teacher = await _teacher_profile(db, tenant_id=tenant.id, user_id=actor.id)
    return _serialize_absence(await _load_scoped_absence(db, tenant_id=tenant.id, absence_id=absence_id, teacher_id=teacher.id))


@leadership_router.post("", response_model=TeacherAbsenceResponse, status_code=status.HTTP_201_CREATED)
async def report_leadership_absence(
    body: LeadershipAbsenceReportRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> TeacherAbsence:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    try:
        return await report_absence(
            db,
            tenant_id=tenant.id,
            teacher_id=body.teacher_id,
            start_date=body.start_date,
            end_date=body.end_date,
            scope_type=body.scope_type,
            selected_periods=body.selected_periods,
            reason_code=body.reason_code,
            private_note=body.private_note,
            source_type="leadership",
            reported_by_user_id=actor.id,
        )
    except TeacherAbsenceError as exc:
        raise _map_absence_error(exc) from exc


@leadership_router.get("", response_model=TeacherAbsenceListResponse)
async def list_leadership_absences(
    teacher_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    result = await db.execute(_list_statement(tenant_id=tenant.id, teacher_id=teacher_id, status_filter=status_filter, date_from=date_from, date_to=date_to).offset((page - 1) * page_size).limit(page_size))
    return {"items": [_serialize_absence(row) for row in result.scalars().all()], "page": page, "page_size": page_size}


@leadership_router.get("/{absence_id}", response_model=TeacherAbsenceResponse)
async def get_leadership_absence(
    absence_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    return _serialize_absence(await _load_scoped_absence(db, tenant_id=tenant.id, absence_id=absence_id))


async def _transition(
    operation: Any,
    *, absence_id: uuid.UUID, tenant: Tenant, actor: User, db: AsyncSession,
) -> TeacherAbsence:
    _assert_tenant_user(actor=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    try:
        if operation is confirm_absence:
            return await operation(db, tenant_id=tenant.id, absence_id=absence_id, confirmed_by_user_id=actor.id)
        if operation is cancel_absence:
            return await operation(db, tenant_id=tenant.id, absence_id=absence_id, cancelled_by_user_id=actor.id)
        return await operation(db, tenant_id=tenant.id, absence_id=absence_id)
    except TeacherAbsenceError as exc:
        raise _map_absence_error(exc) from exc


@leadership_router.post("/{absence_id}/confirm", response_model=TeacherAbsenceResponse)
async def confirm_leadership_absence(absence_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)) -> TeacherAbsence:
    return await _transition(confirm_absence, absence_id=absence_id, tenant=tenant, actor=actor, db=db)


@leadership_router.post("/{absence_id}/cancel", response_model=TeacherAbsenceResponse)
async def cancel_leadership_absence(absence_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)) -> TeacherAbsence:
    return await _transition(cancel_absence, absence_id=absence_id, tenant=tenant, actor=actor, db=db)


@leadership_router.post("/{absence_id}/close", response_model=TeacherAbsenceResponse)
async def close_leadership_absence(absence_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)) -> TeacherAbsence:
    return await _transition(close_absence, absence_id=absence_id, tenant=tenant, actor=actor, db=db)
