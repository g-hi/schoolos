from __future__ import annotations

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import AcademicYear, Campus, GradeLevel, Tenant, Term, User

router = APIRouter(prefix="/leadership/master-data", tags=["Master Data"])


class CampusCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    code: str
    description: str | None = None
    is_active: bool = True


class CampusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    code: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AcademicYearCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    start_date: date_type
    end_date: date_type
    is_current: bool = False
    is_active: bool = True


class AcademicYearUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    is_current: bool | None = None
    is_active: bool | None = None


class TermCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    academic_year_id: uuid.UUID
    name: str
    code: str
    start_date: date_type
    end_date: date_type
    sequence: int
    is_active: bool = True


class TermUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    academic_year_id: uuid.UUID | None = None
    name: str | None = None
    code: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    sequence: int | None = None
    is_active: bool | None = None


class GradeLevelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    code: str
    sequence: int
    is_active: bool = True


class GradeLevelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    code: str | None = None
    sequence: int | None = None
    is_active: bool | None = None


def _validate_date_range(start_date: date_type, end_date: date_type, *, label: str) -> None:
    if end_date <= start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} end_date must be after start_date.",
        )


def _validate_positive_sequence(sequence: int, *, label: str) -> None:
    if sequence <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} sequence must be positive.",
        )


def _validate_term_inside_year(*, year: AcademicYear, start_date: date_type, end_date: date_type) -> None:
    if start_date < year.start_date or end_date > year.end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Term dates must fall within the related academic year.",
        )


async def _clear_existing_current_academic_year(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(AcademicYear).where(
        AcademicYear.tenant_id == tenant_id,
        AcademicYear.is_current.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(AcademicYear.id != exclude_id)
    rows = (await db.execute(stmt)).scalars().all()
    for row in rows:
        row.is_current = False


def _campus_payload(item: Campus) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "code": item.code,
        "description": item.description,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _academic_year_payload(item: AcademicYear) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "is_current": item.is_current,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _term_payload(item: Term) -> dict:
    return {
        "id": str(item.id),
        "academic_year_id": str(item.academic_year_id),
        "name": item.name,
        "code": item.code,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "sequence": item.sequence,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _grade_level_payload(item: GradeLevel) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "code": item.code,
        "sequence": item.sequence,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/campuses", summary="List campuses")
async def list_campuses(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(Campus)
            .where(Campus.tenant_id == tenant.id)
            .order_by(Campus.code.asc())
        )
    ).scalars().all()
    return [_campus_payload(item) for item in rows]


@router.post("/campuses", summary="Create campus")
async def create_campus(
    body: CampusCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    normalized_code = body.code.strip().upper()
    duplicate = await db.scalar(
        select(Campus.id).where(Campus.tenant_id == tenant.id, Campus.code == normalized_code)
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campus code already exists.")

    item = Campus(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=body.name.strip(),
        code=normalized_code,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="master_data.campus.created",
        entity_type="Campus",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campus code already exists.")
    await db.refresh(item)
    return _campus_payload(item)


@router.patch("/campuses/{campus_id}", summary="Update campus")
async def update_campus(
    campus_id: uuid.UUID,
    body: CampusUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(Campus).where(Campus.id == campus_id, Campus.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campus not found.")

    if body.code is not None:
        normalized_code = body.code.strip().upper()
        duplicate = await db.scalar(
            select(Campus.id).where(
                Campus.tenant_id == tenant.id,
                Campus.code == normalized_code,
                Campus.id != item.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campus code already exists.")
        item.code = normalized_code

    if body.name is not None:
        item.name = body.name.strip()
    if body.description is not None:
        item.description = body.description

    state_change = None
    if body.is_active is not None and body.is_active != item.is_active:
        item.is_active = body.is_active
        state_change = "activated" if body.is_active else "deactivated"

    action = "master_data.campus.updated" if state_change is None else f"master_data.campus.{state_change}"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="Campus",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _campus_payload(item)


@router.get("/academic-years", summary="List academic years")
async def list_academic_years(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(AcademicYear)
            .where(AcademicYear.tenant_id == tenant.id)
            .order_by(AcademicYear.start_date.desc())
        )
    ).scalars().all()
    return [_academic_year_payload(item) for item in rows]


@router.post("/academic-years", summary="Create academic year")
async def create_academic_year(
    body: AcademicYearCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _validate_date_range(body.start_date, body.end_date, label="Academic year")

    duplicate = await db.scalar(
        select(AcademicYear.id).where(AcademicYear.tenant_id == tenant.id, AcademicYear.name == body.name.strip())
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Academic year name already exists.")

    if body.is_current:
        await _clear_existing_current_academic_year(db=db, tenant_id=tenant.id)

    item = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=body.name.strip(),
        start_date=body.start_date,
        end_date=body.end_date,
        is_current=body.is_current,
        is_active=body.is_active,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="master_data.academic_year.created",
        entity_type="AcademicYear",
        entity_id=item.id,
        actor_id=actor.id,
        details={"name": item.name, "is_current": item.is_current, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Academic year integrity conflict.")
    await db.refresh(item)
    return _academic_year_payload(item)


@router.patch("/academic-years/{academic_year_id}", summary="Update academic year")
async def update_academic_year(
    academic_year_id: uuid.UUID,
    body: AcademicYearUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(
        select(AcademicYear).where(AcademicYear.id == academic_year_id, AcademicYear.tenant_id == tenant.id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Academic year not found.")

    next_start = body.start_date if body.start_date is not None else item.start_date
    next_end = body.end_date if body.end_date is not None else item.end_date
    _validate_date_range(next_start, next_end, label="Academic year")

    if body.name is not None:
        normalized_name = body.name.strip()
        duplicate = await db.scalar(
            select(AcademicYear.id).where(
                AcademicYear.tenant_id == tenant.id,
                AcademicYear.name == normalized_name,
                AcademicYear.id != item.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Academic year name already exists.")
        item.name = normalized_name

    item.start_date = next_start
    item.end_date = next_end

    if body.is_current is True:
        await _clear_existing_current_academic_year(db=db, tenant_id=tenant.id, exclude_id=item.id)
    if body.is_current is not None:
        item.is_current = body.is_current

    state_change = None
    if body.is_active is not None and body.is_active != item.is_active:
        item.is_active = body.is_active
        state_change = "activated" if body.is_active else "deactivated"

    action = "master_data.academic_year.updated" if state_change is None else f"master_data.academic_year.{state_change}"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="AcademicYear",
        entity_id=item.id,
        actor_id=actor.id,
        details={"name": item.name, "is_current": item.is_current, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Academic year integrity conflict.")
    await db.refresh(item)
    return _academic_year_payload(item)


@router.get("/terms", summary="List terms")
async def list_terms(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(Term)
            .where(Term.tenant_id == tenant.id)
            .order_by(Term.sequence.asc(), Term.start_date.asc())
        )
    ).scalars().all()
    return [_term_payload(item) for item in rows]


@router.post("/terms", summary="Create term")
async def create_term(
    body: TermCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _validate_date_range(body.start_date, body.end_date, label="Term")
    _validate_positive_sequence(body.sequence, label="Term")

    year = await db.scalar(
        select(AcademicYear).where(
            AcademicYear.id == body.academic_year_id,
            AcademicYear.tenant_id == tenant.id,
        )
    )
    if year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="academic_year_id is not valid for this tenant.",
        )
    _validate_term_inside_year(year=year, start_date=body.start_date, end_date=body.end_date)

    normalized_code = body.code.strip().upper()
    duplicate = await db.scalar(
        select(Term.id).where(
            Term.tenant_id == tenant.id,
            Term.academic_year_id == body.academic_year_id,
            Term.code == normalized_code,
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Term code already exists for this academic year.")

    item = Term(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        name=body.name.strip(),
        code=normalized_code,
        start_date=body.start_date,
        end_date=body.end_date,
        sequence=body.sequence,
        is_active=body.is_active,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="master_data.term.created",
        entity_type="Term",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "sequence": item.sequence, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Term code already exists for this academic year.")
    await db.refresh(item)
    return _term_payload(item)


@router.patch("/terms/{term_id}", summary="Update term")
async def update_term(
    term_id: uuid.UUID,
    body: TermUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(Term).where(Term.id == term_id, Term.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found.")

    next_year_id = body.academic_year_id if body.academic_year_id is not None else item.academic_year_id
    year = await db.scalar(
        select(AcademicYear).where(AcademicYear.id == next_year_id, AcademicYear.tenant_id == tenant.id)
    )
    if year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="academic_year_id is not valid for this tenant.",
        )

    next_start = body.start_date if body.start_date is not None else item.start_date
    next_end = body.end_date if body.end_date is not None else item.end_date
    _validate_date_range(next_start, next_end, label="Term")
    _validate_term_inside_year(year=year, start_date=next_start, end_date=next_end)

    next_sequence = body.sequence if body.sequence is not None else item.sequence
    _validate_positive_sequence(next_sequence, label="Term")

    next_code = body.code.strip().upper() if body.code is not None else item.code
    duplicate = await db.scalar(
        select(Term.id).where(
            Term.tenant_id == tenant.id,
            Term.academic_year_id == next_year_id,
            Term.code == next_code,
            Term.id != item.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Term code already exists for this academic year.")

    if body.name is not None:
        item.name = body.name.strip()
    item.academic_year_id = next_year_id
    item.code = next_code
    item.start_date = next_start
    item.end_date = next_end
    item.sequence = next_sequence

    state_change = None
    if body.is_active is not None and body.is_active != item.is_active:
        item.is_active = body.is_active
        state_change = "activated" if body.is_active else "deactivated"

    action = "master_data.term.updated" if state_change is None else f"master_data.term.{state_change}"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="Term",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "sequence": item.sequence, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _term_payload(item)


@router.get("/grade-levels", summary="List grade levels")
async def list_grade_levels(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(GradeLevel)
            .where(GradeLevel.tenant_id == tenant.id)
            .order_by(GradeLevel.sequence.asc(), GradeLevel.code.asc())
        )
    ).scalars().all()
    return [_grade_level_payload(item) for item in rows]


@router.post("/grade-levels", summary="Create grade level")
async def create_grade_level(
    body: GradeLevelCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _validate_positive_sequence(body.sequence, label="Grade level")

    normalized_code = body.code.strip().upper()
    duplicate = await db.scalar(
        select(GradeLevel.id).where(GradeLevel.tenant_id == tenant.id, GradeLevel.code == normalized_code)
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Grade level code already exists.")

    item = GradeLevel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=body.name.strip(),
        code=normalized_code,
        sequence=body.sequence,
        is_active=body.is_active,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="master_data.grade_level.created",
        entity_type="GradeLevel",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "sequence": item.sequence, "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Grade level code already exists.")
    await db.refresh(item)
    return _grade_level_payload(item)


@router.patch("/grade-levels/{grade_level_id}", summary="Update grade level")
async def update_grade_level(
    grade_level_id: uuid.UUID,
    body: GradeLevelUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(
        select(GradeLevel).where(GradeLevel.id == grade_level_id, GradeLevel.tenant_id == tenant.id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade level not found.")

    next_code = body.code.strip().upper() if body.code is not None else item.code
    duplicate = await db.scalar(
        select(GradeLevel.id).where(
            GradeLevel.tenant_id == tenant.id,
            GradeLevel.code == next_code,
            GradeLevel.id != item.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Grade level code already exists.")

    next_sequence = body.sequence if body.sequence is not None else item.sequence
    _validate_positive_sequence(next_sequence, label="Grade level")

    if body.name is not None:
        item.name = body.name.strip()
    item.code = next_code
    item.sequence = next_sequence

    state_change = None
    if body.is_active is not None and body.is_active != item.is_active:
        item.is_active = body.is_active
        state_change = "activated" if body.is_active else "deactivated"

    action = "master_data.grade_level.updated" if state_change is None else f"master_data.grade_level.{state_change}"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="GradeLevel",
        entity_id=item.id,
        actor_id=actor.id,
        details={"code": item.code, "sequence": item.sequence, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _grade_level_payload(item)


@router.get("/setup-summary", summary="Master-data setup summary")
async def setup_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    campuses = int(await db.scalar(select(func.count(Campus.id)).where(Campus.tenant_id == tenant.id)) or 0)
    academic_years = int(await db.scalar(select(func.count(AcademicYear.id)).where(AcademicYear.tenant_id == tenant.id)) or 0)
    terms = int(await db.scalar(select(func.count(Term.id)).where(Term.tenant_id == tenant.id)) or 0)
    grade_levels = int(await db.scalar(select(func.count(GradeLevel.id)).where(GradeLevel.tenant_id == tenant.id)) or 0)

    return {
        "counts": {
            "campuses": campuses,
            "academic_years": academic_years,
            "terms": terms,
            "grade_levels": grade_levels,
        },
        "readiness": {
            "has_campuses": campuses > 0,
            "has_academic_years": academic_years > 0,
            "has_terms": terms > 0,
            "has_grade_levels": grade_levels > 0,
            "is_master_data_configured": all(value > 0 for value in (campuses, academic_years, terms, grade_levels)),
        },
    }
