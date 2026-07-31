from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    Campus,
    Class,
    GradeLevel,
    Subject,
    SubjectOffering,
    Teacher,
    Tenant,
    User,
)

router = APIRouter(prefix="/leadership/academic-structure", tags=["Academic Structure"])


class ClassCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID
    academic_year_id: uuid.UUID
    grade_level_id: uuid.UUID
    code: str
    section: str
    class_teacher_id: uuid.UUID | None = None
    is_active: bool


class ClassUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    section: str | None = None
    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    grade_level_id: uuid.UUID | None = None
    class_teacher_id: uuid.UUID | None = None
    is_active: bool | None = None


class SubjectOfferingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID
    academic_year_id: uuid.UUID
    grade_level_id: uuid.UUID
    subject_id: uuid.UUID
    is_active: bool


class SubjectOfferingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campus_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    grade_level_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    is_active: bool | None = None


def _clean_required_text(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must not be blank.")
    return cleaned


async def _resolve_active_campus(*, db: AsyncSession, tenant_id: uuid.UUID, campus_id: uuid.UUID) -> Campus:
    campus = await db.scalar(
        select(Campus).where(
            Campus.id == campus_id,
            Campus.tenant_id == tenant_id,
            Campus.is_active.is_(True),
        )
    )
    if campus is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campus not found or inactive.")
    return campus


async def _resolve_active_academic_year(*, db: AsyncSession, tenant_id: uuid.UUID, academic_year_id: uuid.UUID) -> AcademicYear:
    academic_year = await db.scalar(
        select(AcademicYear).where(
            AcademicYear.id == academic_year_id,
            AcademicYear.tenant_id == tenant_id,
            AcademicYear.is_active.is_(True),
        )
    )
    if academic_year is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Academic year not found or inactive.")
    return academic_year


async def _resolve_active_grade_level(*, db: AsyncSession, tenant_id: uuid.UUID, grade_level_id: uuid.UUID) -> GradeLevel:
    grade_level = await db.scalar(
        select(GradeLevel).where(
            GradeLevel.id == grade_level_id,
            GradeLevel.tenant_id == tenant_id,
            GradeLevel.is_active.is_(True),
        )
    )
    if grade_level is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Grade level not found or inactive.")
    return grade_level


async def _resolve_subject(*, db: AsyncSession, tenant_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
    subject = await db.scalar(
        select(Subject).where(
            Subject.id == subject_id,
            Subject.tenant_id == tenant_id,
        )
    )
    if subject is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject not found.")
    return subject


async def _resolve_teacher(*, db: AsyncSession, tenant_id: uuid.UUID, teacher_id: uuid.UUID) -> Teacher:
    teacher = await db.scalar(
        select(Teacher).where(
            Teacher.id == teacher_id,
            Teacher.tenant_id == tenant_id,
        )
    )
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class teacher not found.")
    return teacher


def _class_payload(
    *,
    item: Class,
    campus: Campus | None,
    academic_year: AcademicYear | None,
    grade_level: GradeLevel | None,
    teacher_user: User | None,
) -> dict:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "academic_year_id": str(item.academic_year_id) if item.academic_year_id else None,
        "grade_level_id": str(item.grade_level_id) if item.grade_level_id else None,
        "class_teacher_id": str(item.class_teacher_id) if item.class_teacher_id else None,
        "code": item.code,
        "is_active": item.is_active,
        "grade": item.grade,
        "section": item.section,
        "academic_year": item.academic_year,
        "campus_name": campus.name if campus else None,
        "academic_year_name": academic_year.name if academic_year else None,
        "grade_level_name": grade_level.name if grade_level else None,
        "class_teacher_name": teacher_user.name if teacher_user else None,
        "updated_at": item.updated_at,
    }


def _offering_payload(
    *,
    item: SubjectOffering,
    campus: Campus,
    academic_year: AcademicYear,
    grade_level: GradeLevel,
    subject: Subject,
) -> dict:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": str(item.campus_id),
        "academic_year_id": str(item.academic_year_id),
        "grade_level_id": str(item.grade_level_id),
        "subject_id": str(item.subject_id),
        "is_active": item.is_active,
        "campus_name": campus.name,
        "academic_year_name": academic_year.name,
        "grade_level_name": grade_level.name,
        "subject_name": subject.name,
        "subject_code": subject.code,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _guard_duplicate_class_section(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID | None,
    campus_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    grade_level_id: uuid.UUID,
    section: str,
) -> None:
    query = select(Class.id).where(
        Class.tenant_id == tenant_id,
        Class.campus_id == campus_id,
        Class.academic_year_id == academic_year_id,
        Class.grade_level_id == grade_level_id,
        Class.section == section,
        Class.is_active.is_(True),
    )
    if class_id is not None:
        query = query.where(Class.id != class_id)
    duplicate = await db.scalar(query)
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Canonical class section already exists.")


async def _guard_duplicate_class_code(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID | None,
    academic_year_id: uuid.UUID,
    code: str,
) -> None:
    query = select(Class.id).where(
        Class.tenant_id == tenant_id,
        Class.academic_year_id == academic_year_id,
        Class.code == code,
        Class.is_active.is_(True),
    )
    if class_id is not None:
        query = query.where(Class.id != class_id)
    duplicate = await db.scalar(query)
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class code already exists in this academic year.")


@router.get("/classes", summary="List classes")
async def list_classes(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(Class, Campus, AcademicYear, GradeLevel, User)
            .outerjoin(Campus, Campus.id == Class.campus_id)
            .outerjoin(AcademicYear, AcademicYear.id == Class.academic_year_id)
            .outerjoin(GradeLevel, GradeLevel.id == Class.grade_level_id)
            .outerjoin(Teacher, Teacher.id == Class.class_teacher_id)
            .outerjoin(User, User.id == Teacher.user_id)
            .where(Class.tenant_id == tenant.id)
            .order_by(Class.academic_year.desc(), Class.grade.asc(), Class.section.asc())
        )
    ).all()
    return [
        _class_payload(item=item, campus=campus, academic_year=year, grade_level=level, teacher_user=teacher_user)
        for item, campus, year, level, teacher_user in rows
    ]


@router.post("/classes", summary="Create canonical class")
async def create_class(
    body: ClassCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    code = _clean_required_text(body.code, label="code")
    section = _clean_required_text(body.section, label="section")

    campus = await _resolve_active_campus(db=db, tenant_id=tenant.id, campus_id=body.campus_id)
    academic_year = await _resolve_active_academic_year(db=db, tenant_id=tenant.id, academic_year_id=body.academic_year_id)
    grade_level = await _resolve_active_grade_level(db=db, tenant_id=tenant.id, grade_level_id=body.grade_level_id)

    if body.class_teacher_id is not None:
        await _resolve_teacher(db=db, tenant_id=tenant.id, teacher_id=body.class_teacher_id)

    if body.is_active:
        await _guard_duplicate_class_section(
            db=db,
            tenant_id=tenant.id,
            class_id=None,
            campus_id=campus.id,
            academic_year_id=academic_year.id,
            grade_level_id=grade_level.id,
            section=section,
        )
        await _guard_duplicate_class_code(
            db=db,
            tenant_id=tenant.id,
            class_id=None,
            academic_year_id=academic_year.id,
            code=code,
        )

    item = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=grade_level.name,
        section=section,
        academic_year=academic_year.name,
        class_teacher_id=body.class_teacher_id,
        campus_id=campus.id,
        academic_year_id=academic_year.id,
        grade_level_id=grade_level.id,
        code=code,
        is_active=body.is_active,
    )
    db.add(item)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="academic_structure.class.created",
        entity_type="Class",
        entity_id=item.id,
        actor_id=actor.id,
        details={"campus_id": str(item.campus_id), "academic_year_id": str(item.academic_year_id), "grade_level_id": str(item.grade_level_id), "is_active": item.is_active},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class uniqueness conflict.")

    teacher_user = None
    if body.class_teacher_id is not None:
        teacher_user = await db.scalar(
            select(User)
            .join(Teacher, Teacher.user_id == User.id)
            .where(Teacher.id == body.class_teacher_id, Teacher.tenant_id == tenant.id)
        )

    await db.refresh(item)
    return _class_payload(item=item, campus=campus, academic_year=academic_year, grade_level=grade_level, teacher_user=teacher_user)


@router.patch("/classes/{class_id}", summary="Update class")
async def update_class(
    class_id: uuid.UUID,
    body: ClassUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(Class).where(Class.id == class_id, Class.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")

    next_code = item.code
    next_section = item.section
    next_campus_id = item.campus_id
    next_academic_year_id = item.academic_year_id
    next_grade_level_id = item.grade_level_id
    next_teacher_id = item.class_teacher_id
    next_is_active = item.is_active

    if "code" in body.model_fields_set:
        if body.code is None:
            next_code = None
        else:
            next_code = _clean_required_text(body.code, label="code")

    if "section" in body.model_fields_set:
        if body.section is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="section must not be null.")
        next_section = _clean_required_text(body.section, label="section")

    if "campus_id" in body.model_fields_set:
        next_campus_id = body.campus_id
    if "academic_year_id" in body.model_fields_set:
        next_academic_year_id = body.academic_year_id
    if "grade_level_id" in body.model_fields_set:
        next_grade_level_id = body.grade_level_id
    if "class_teacher_id" in body.model_fields_set:
        next_teacher_id = body.class_teacher_id
    if "is_active" in body.model_fields_set and body.is_active is not None:
        next_is_active = body.is_active

    ids = (next_campus_id, next_academic_year_id, next_grade_level_id)
    all_none = all(value is None for value in ids)
    all_set = all(value is not None for value in ids)
    if not all_none and not all_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Canonical scope must provide campus_id, academic_year_id and grade_level_id together.",
        )

    if next_teacher_id is not None:
        await _resolve_teacher(db=db, tenant_id=tenant.id, teacher_id=next_teacher_id)

    campus = None
    academic_year = None
    grade_level = None

    if all_set:
        campus = await _resolve_active_campus(db=db, tenant_id=tenant.id, campus_id=next_campus_id)
        academic_year = await _resolve_active_academic_year(db=db, tenant_id=tenant.id, academic_year_id=next_academic_year_id)
        grade_level = await _resolve_active_grade_level(db=db, tenant_id=tenant.id, grade_level_id=next_grade_level_id)

        if next_is_active:
            await _guard_duplicate_class_section(
                db=db,
                tenant_id=tenant.id,
                class_id=item.id,
                campus_id=next_campus_id,
                academic_year_id=next_academic_year_id,
                grade_level_id=next_grade_level_id,
                section=next_section,
            )
            if next_code is not None:
                await _guard_duplicate_class_code(
                    db=db,
                    tenant_id=tenant.id,
                    class_id=item.id,
                    academic_year_id=next_academic_year_id,
                    code=next_code,
                )

    previous_active = item.is_active

    item.code = next_code
    item.section = next_section
    item.campus_id = next_campus_id
    item.academic_year_id = next_academic_year_id
    item.grade_level_id = next_grade_level_id
    item.class_teacher_id = next_teacher_id
    item.is_active = next_is_active

    if all_set and campus and academic_year and grade_level:
        item.grade = grade_level.name
        item.academic_year = academic_year.name
        item.section = next_section

    state_change = None
    if next_is_active != previous_active:
        state_change = "activated" if next_is_active else "deactivated"

    action = "academic_structure.class.updated" if state_change is None else f"academic_structure.class.{state_change}"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="Class",
        entity_id=item.id,
        actor_id=actor.id,
        details={
            "campus_id": str(item.campus_id) if item.campus_id else None,
            "academic_year_id": str(item.academic_year_id) if item.academic_year_id else None,
            "grade_level_id": str(item.grade_level_id) if item.grade_level_id else None,
            "is_active": item.is_active,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class uniqueness conflict.")

    teacher_user = None
    if item.class_teacher_id is not None:
        teacher_user = await db.scalar(
            select(User)
            .join(Teacher, Teacher.user_id == User.id)
            .where(Teacher.id == item.class_teacher_id, Teacher.tenant_id == tenant.id)
        )

    if campus is None and item.campus_id is not None:
        campus = await db.scalar(select(Campus).where(Campus.id == item.campus_id))
    if academic_year is None and item.academic_year_id is not None:
        academic_year = await db.scalar(select(AcademicYear).where(AcademicYear.id == item.academic_year_id))
    if grade_level is None and item.grade_level_id is not None:
        grade_level = await db.scalar(select(GradeLevel).where(GradeLevel.id == item.grade_level_id))

    await db.refresh(item)
    return _class_payload(item=item, campus=campus, academic_year=academic_year, grade_level=grade_level, teacher_user=teacher_user)


@router.get("/subject-offerings", summary="List subject offerings")
async def list_subject_offerings(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(SubjectOffering, Campus, AcademicYear, GradeLevel, Subject)
            .join(Campus, Campus.id == SubjectOffering.campus_id)
            .join(AcademicYear, AcademicYear.id == SubjectOffering.academic_year_id)
            .join(GradeLevel, GradeLevel.id == SubjectOffering.grade_level_id)
            .join(Subject, Subject.id == SubjectOffering.subject_id)
            .where(SubjectOffering.tenant_id == tenant.id)
            .order_by(AcademicYear.start_date.desc(), GradeLevel.sequence.asc(), Subject.code.asc())
        )
    ).all()

    return [
        _offering_payload(item=item, campus=campus, academic_year=year, grade_level=level, subject=subject)
        for item, campus, year, level, subject in rows
    ]


@router.post("/subject-offerings", summary="Create subject offering")
async def create_subject_offering(
    body: SubjectOfferingCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    campus = await _resolve_active_campus(db=db, tenant_id=tenant.id, campus_id=body.campus_id)
    academic_year = await _resolve_active_academic_year(db=db, tenant_id=tenant.id, academic_year_id=body.academic_year_id)
    grade_level = await _resolve_active_grade_level(db=db, tenant_id=tenant.id, grade_level_id=body.grade_level_id)
    subject = await _resolve_subject(db=db, tenant_id=tenant.id, subject_id=body.subject_id)

    duplicate = await db.scalar(
        select(SubjectOffering.id).where(
            SubjectOffering.tenant_id == tenant.id,
            SubjectOffering.campus_id == body.campus_id,
            SubjectOffering.academic_year_id == body.academic_year_id,
            SubjectOffering.grade_level_id == body.grade_level_id,
            SubjectOffering.subject_id == body.subject_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subject offering already exists for this scope.")

    item = SubjectOffering(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=body.campus_id,
        academic_year_id=body.academic_year_id,
        grade_level_id=body.grade_level_id,
        subject_id=body.subject_id,
        is_active=body.is_active,
    )
    db.add(item)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="academic_structure.subject_offering.created",
        entity_type="SubjectOffering",
        entity_id=item.id,
        actor_id=actor.id,
        details={
            "campus_id": str(item.campus_id),
            "academic_year_id": str(item.academic_year_id),
            "grade_level_id": str(item.grade_level_id),
            "subject_id": str(item.subject_id),
            "is_active": item.is_active,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subject offering uniqueness conflict.")

    await db.refresh(item)
    return _offering_payload(item=item, campus=campus, academic_year=academic_year, grade_level=grade_level, subject=subject)


@router.patch("/subject-offerings/{offering_id}", summary="Update subject offering")
async def update_subject_offering(
    offering_id: uuid.UUID,
    body: SubjectOfferingUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(
        select(SubjectOffering).where(
            SubjectOffering.id == offering_id,
            SubjectOffering.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject offering not found.")

    next_campus_id = body.campus_id if "campus_id" in body.model_fields_set else item.campus_id
    next_academic_year_id = body.academic_year_id if "academic_year_id" in body.model_fields_set else item.academic_year_id
    next_grade_level_id = body.grade_level_id if "grade_level_id" in body.model_fields_set else item.grade_level_id
    next_subject_id = body.subject_id if "subject_id" in body.model_fields_set else item.subject_id
    next_is_active = body.is_active if body.is_active is not None else item.is_active

    campus = await _resolve_active_campus(db=db, tenant_id=tenant.id, campus_id=next_campus_id)
    academic_year = await _resolve_active_academic_year(db=db, tenant_id=tenant.id, academic_year_id=next_academic_year_id)
    grade_level = await _resolve_active_grade_level(db=db, tenant_id=tenant.id, grade_level_id=next_grade_level_id)
    subject = await _resolve_subject(db=db, tenant_id=tenant.id, subject_id=next_subject_id)

    duplicate = await db.scalar(
        select(SubjectOffering.id).where(
            SubjectOffering.tenant_id == tenant.id,
            SubjectOffering.campus_id == next_campus_id,
            SubjectOffering.academic_year_id == next_academic_year_id,
            SubjectOffering.grade_level_id == next_grade_level_id,
            SubjectOffering.subject_id == next_subject_id,
            SubjectOffering.id != item.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subject offering already exists for this scope.")

    previous_active = item.is_active
    item.campus_id = next_campus_id
    item.academic_year_id = next_academic_year_id
    item.grade_level_id = next_grade_level_id
    item.subject_id = next_subject_id
    item.is_active = next_is_active

    state_change = None
    if next_is_active != previous_active:
        state_change = "activated" if next_is_active else "deactivated"
    action = "academic_structure.subject_offering.updated" if state_change is None else f"academic_structure.subject_offering.{state_change}"

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="SubjectOffering",
        entity_id=item.id,
        actor_id=actor.id,
        details={
            "campus_id": str(item.campus_id),
            "academic_year_id": str(item.academic_year_id),
            "grade_level_id": str(item.grade_level_id),
            "subject_id": str(item.subject_id),
            "is_active": item.is_active,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subject offering uniqueness conflict.")

    await db.refresh(item)
    return _offering_payload(item=item, campus=campus, academic_year=academic_year, grade_level=grade_level, subject=subject)


@router.get("/summary", summary="Academic-structure summary")
async def summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    total_classes = int(await db.scalar(select(func.count(Class.id)).where(Class.tenant_id == tenant.id)) or 0)
    canonical_classes = int(
        await db.scalar(
            select(func.count(Class.id)).where(
                Class.tenant_id == tenant.id,
                Class.campus_id.is_not(None),
                Class.academic_year_id.is_not(None),
                Class.grade_level_id.is_not(None),
            )
        )
        or 0
    )
    legacy_classes = int(
        await db.scalar(
            select(func.count(Class.id)).where(
                Class.tenant_id == tenant.id,
                Class.campus_id.is_(None),
                Class.academic_year_id.is_(None),
                Class.grade_level_id.is_(None),
            )
        )
        or 0
    )
    active_canonical_classes = int(
        await db.scalar(
            select(func.count(Class.id)).where(
                Class.tenant_id == tenant.id,
                Class.campus_id.is_not(None),
                Class.academic_year_id.is_not(None),
                Class.grade_level_id.is_not(None),
                Class.is_active.is_(True),
            )
        )
        or 0
    )

    subject_offerings = int(
        await db.scalar(select(func.count(SubjectOffering.id)).where(SubjectOffering.tenant_id == tenant.id)) or 0
    )
    active_subject_offerings = int(
        await db.scalar(
            select(func.count(SubjectOffering.id)).where(
                SubjectOffering.tenant_id == tenant.id,
                SubjectOffering.is_active.is_(True),
            )
        )
        or 0
    )

    return {
        "counts": {
            "total_classes": total_classes,
            "canonical_classes": canonical_classes,
            "legacy_classes": legacy_classes,
            "active_canonical_classes": active_canonical_classes,
            "subject_offerings": subject_offerings,
            "active_subject_offerings": active_subject_offerings,
        }
    }
