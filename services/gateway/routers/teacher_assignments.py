from __future__ import annotations

import uuid
from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import AcademicYear, Class, GradeLevel, Subject, SubjectOffering, Teacher, TeacherAssignment, TeacherSubject, Tenant, User

router = APIRouter(prefix="/leadership/teacher-assignments", tags=["Teacher Assignments"])


class TeacherAssignmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID
    teacher_id: uuid.UUID
    class_id: uuid.UUID
    subject_offering_id: uuid.UUID | None = None
    assignment_type: Literal["homeroom", "subject_teacher"]
    start_date: date_type
    end_date: date_type | None = None
    is_active: bool = True


class TeacherAssignmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date_type | None = None
    end_date: date_type | None = None
    is_active: bool | None = None


def _assignment_payload(
    *,
    assignment: TeacherAssignment,
    teacher_user: User,
    klass: Class,
    grade_level: GradeLevel | None,
    academic_year: AcademicYear,
    subject_offering: SubjectOffering | None,
    subject: Subject | None,
) -> dict:
    return {
        "id": str(assignment.id),
        "tenant_id": str(assignment.tenant_id),
        "academic_year_id": str(assignment.academic_year_id),
        "teacher_id": str(assignment.teacher_id),
        "class_id": str(assignment.class_id),
        "subject_offering_id": str(assignment.subject_offering_id) if assignment.subject_offering_id else None,
        "assignment_type": assignment.assignment_type,
        "start_date": assignment.start_date,
        "end_date": assignment.end_date,
        "is_active": assignment.is_active,
        "teacher_name": teacher_user.name,
        "class_code": klass.code,
        "class_grade_level_name": grade_level.name if grade_level else None,
        "class_section": klass.section,
        "academic_year_name": academic_year.name,
        "subject_offering": {
            "id": str(subject_offering.id),
            "subject_id": str(subject_offering.subject_id),
        }
        if subject_offering
        else None,
        "subject_id": str(subject.id) if subject else None,
        "subject_code": subject.code if subject else None,
        "subject_name": subject.name if subject else None,
    }


async def _load_teacher_context(*, db: AsyncSession, tenant_id: uuid.UUID, teacher_id: uuid.UUID) -> tuple[Teacher, User]:
    result = await db.execute(
        select(Teacher, User)
        .join(User, User.id == Teacher.user_id)
        .where(
            Teacher.id == teacher_id,
            Teacher.tenant_id == tenant_id,
            User.tenant_id == tenant_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    teacher, user = row
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher user is inactive.")
    return teacher, user


async def _load_academic_year(*, db: AsyncSession, tenant_id: uuid.UUID, academic_year_id: uuid.UUID) -> AcademicYear:
    academic_year = await db.scalar(
        select(AcademicYear).where(
            AcademicYear.id == academic_year_id,
            AcademicYear.tenant_id == tenant_id,
        )
    )
    if academic_year is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Academic year not found.")
    if not academic_year.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Academic year is inactive.")
    return academic_year


async def _load_class(*, db: AsyncSession, tenant_id: uuid.UUID, class_id: uuid.UUID) -> Class:
    klass = await db.scalar(
        select(Class).where(
            Class.id == class_id,
            Class.tenant_id == tenant_id,
        )
    )
    if klass is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")
    if not klass.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class is inactive.")
    if klass.campus_id is None or klass.academic_year_id is None or klass.grade_level_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class must be canonical.")
    return klass


async def _load_grade_level(*, db: AsyncSession, tenant_id: uuid.UUID, grade_level_id: uuid.UUID) -> GradeLevel:
    grade_level = await db.scalar(
        select(GradeLevel).where(
            GradeLevel.id == grade_level_id,
            GradeLevel.tenant_id == tenant_id,
        )
    )
    if grade_level is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade level not found.")
    return grade_level


async def _load_subject_offering(*, db: AsyncSession, tenant_id: uuid.UUID, subject_offering_id: uuid.UUID) -> tuple[SubjectOffering, Subject]:
    result = await db.execute(
        select(SubjectOffering, Subject)
        .join(Subject, Subject.id == SubjectOffering.subject_id)
        .where(
            SubjectOffering.id == subject_offering_id,
            SubjectOffering.tenant_id == tenant_id,
            Subject.tenant_id == tenant_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject offering not found.")
    offering, subject = row
    if not offering.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject offering is inactive.")
    return offering, subject


async def _load_teacher_subject_qualification(*, db: AsyncSession, teacher_id: uuid.UUID, subject_id: uuid.UUID) -> TeacherSubject | None:
    return await db.scalar(
        select(TeacherSubject).where(
            TeacherSubject.teacher_id == teacher_id,
            TeacherSubject.subject_id == subject_id,
        )
    )


async def _load_assignment(*, db: AsyncSession, tenant_id: uuid.UUID, assignment_id: uuid.UUID) -> TeacherAssignment:
    assignment = await db.scalar(
        select(TeacherAssignment).where(
            TeacherAssignment.id == assignment_id,
            TeacherAssignment.tenant_id == tenant_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher assignment not found.")
    return assignment


def _validate_dates_within_year(*, academic_year: AcademicYear, start_date: date_type, end_date: date_type | None) -> None:
    if start_date < academic_year.start_date or start_date > academic_year.end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date must fall within the academic year.")
    if end_date is not None and (end_date < academic_year.start_date or end_date > academic_year.end_date):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_date must fall within the academic year.")
    if end_date is not None and end_date < start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_date cannot be earlier than start_date.")


async def _ensure_no_active_homeroom_conflict(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    class_id: uuid.UUID,
    exclude_assignment_id: uuid.UUID | None = None,
) -> None:
    stmt = select(TeacherAssignment.id).where(
        TeacherAssignment.tenant_id == tenant_id,
        TeacherAssignment.academic_year_id == academic_year_id,
        TeacherAssignment.class_id == class_id,
        TeacherAssignment.assignment_type == "homeroom",
        TeacherAssignment.is_active.is_(True),
    )
    if exclude_assignment_id is not None:
        stmt = stmt.where(TeacherAssignment.id != exclude_assignment_id)
    duplicate = await db.scalar(stmt)
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active homeroom assignment already exists for this class.")


async def _ensure_no_active_subject_teacher_conflict(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_offering_id: uuid.UUID,
    exclude_assignment_id: uuid.UUID | None = None,
) -> None:
    stmt = select(TeacherAssignment.id).where(
        TeacherAssignment.tenant_id == tenant_id,
        TeacherAssignment.academic_year_id == academic_year_id,
        TeacherAssignment.teacher_id == teacher_id,
        TeacherAssignment.class_id == class_id,
        TeacherAssignment.subject_offering_id == subject_offering_id,
        TeacherAssignment.assignment_type == "subject_teacher",
        TeacherAssignment.is_active.is_(True),
    )
    if exclude_assignment_id is not None:
        stmt = stmt.where(TeacherAssignment.id != exclude_assignment_id)
    duplicate = await db.scalar(stmt)
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active subject-teacher assignment already exists for this scope.")


@router.get("", summary="List teacher assignments")
async def list_teacher_assignments(
    academic_year_id: uuid.UUID | None = Query(default=None),
    teacher_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    assignment_type: Literal["homeroom", "subject_teacher"] | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    stmt = (
        select(TeacherAssignment, Teacher, User, Class, GradeLevel, AcademicYear, SubjectOffering, Subject)
        .join(Teacher, Teacher.id == TeacherAssignment.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .join(Class, Class.id == TeacherAssignment.class_id)
        .outerjoin(GradeLevel, GradeLevel.id == Class.grade_level_id)
        .join(AcademicYear, AcademicYear.id == TeacherAssignment.academic_year_id)
        .outerjoin(SubjectOffering, SubjectOffering.id == TeacherAssignment.subject_offering_id)
        .outerjoin(Subject, Subject.id == SubjectOffering.subject_id)
        .where(TeacherAssignment.tenant_id == tenant.id)
    )
    if academic_year_id is not None:
        stmt = stmt.where(TeacherAssignment.academic_year_id == academic_year_id)
    if teacher_id is not None:
        stmt = stmt.where(TeacherAssignment.teacher_id == teacher_id)
    if class_id is not None:
        stmt = stmt.where(TeacherAssignment.class_id == class_id)
    if assignment_type is not None:
        stmt = stmt.where(TeacherAssignment.assignment_type == assignment_type)
    if is_active is not None:
        stmt = stmt.where(TeacherAssignment.is_active.is_(is_active))

    rows = (await db.execute(stmt.order_by(TeacherAssignment.created_at.desc()))).all()
    return [
        _assignment_payload(
            assignment=assignment,
            teacher_user=teacher_user,
            klass=klass,
            grade_level=grade_level,
            academic_year=academic_year,
            subject_offering=subject_offering,
            subject=subject,
        )
        for assignment, teacher, teacher_user, klass, grade_level, academic_year, subject_offering, subject in rows
    ]


@router.post("", summary="Create teacher assignment")
async def create_teacher_assignment(
    body: TeacherAssignmentCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    teacher, teacher_user = await _load_teacher_context(db=db, tenant_id=tenant.id, teacher_id=body.teacher_id)
    academic_year = await _load_academic_year(db=db, tenant_id=tenant.id, academic_year_id=body.academic_year_id)
    klass = await _load_class(db=db, tenant_id=tenant.id, class_id=body.class_id)
    grade_level = await _load_grade_level(db=db, tenant_id=tenant.id, grade_level_id=klass.grade_level_id)

    if klass.academic_year_id != academic_year.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class academic year must match the assignment academic year.")
    _validate_dates_within_year(academic_year=academic_year, start_date=body.start_date, end_date=body.end_date)

    assignment_type = body.assignment_type
    subject_offering = None
    subject = None

    if assignment_type == "homeroom":
        if body.subject_offering_id is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Homeroom assignments must not reference a subject offering.")
        if klass.class_teacher_id is not None and klass.class_teacher_id != teacher.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class already has a different homeroom teacher.")
        await _ensure_no_active_homeroom_conflict(
            db=db,
            tenant_id=tenant.id,
            academic_year_id=academic_year.id,
            class_id=klass.id,
        )
    else:
        if body.subject_offering_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject-teacher assignments require a subject offering.")
        subject_offering, subject = await _load_subject_offering(db=db, tenant_id=tenant.id, subject_offering_id=body.subject_offering_id)
        if subject_offering.academic_year_id != academic_year.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject offering academic year must match the assignment academic year.")
        if subject_offering.academic_year_id != klass.academic_year_id or subject_offering.campus_id != klass.campus_id or subject_offering.grade_level_id != klass.grade_level_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject offering scope must match the class canonical scope.")
        qualification = await _load_teacher_subject_qualification(db=db, teacher_id=teacher.id, subject_id=subject.id)
        if qualification is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher is not qualified for this subject offering.")
        await _ensure_no_active_subject_teacher_conflict(
            db=db,
            tenant_id=tenant.id,
            academic_year_id=academic_year.id,
            teacher_id=teacher.id,
            class_id=klass.id,
            subject_offering_id=subject_offering.id,
        )

    assignment = TeacherAssignment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=academic_year.id,
        teacher_id=teacher.id,
        class_id=klass.id,
        subject_offering_id=subject_offering.id if subject_offering else None,
        assignment_type=assignment_type,
        start_date=body.start_date,
        end_date=body.end_date,
        is_active=body.is_active,
    )
    db.add(assignment)

    if assignment.assignment_type == "homeroom":
        klass.class_teacher_id = teacher.id

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="teacher_assignment.created",
        entity_type="TeacherAssignment",
        entity_id=assignment.id,
        actor_id=actor.id,
        details={
            "assignment_type": assignment.assignment_type,
            "academic_year_id": str(assignment.academic_year_id),
            "teacher_id": str(assignment.teacher_id),
            "class_id": str(assignment.class_id),
            "subject_offering_id": str(assignment.subject_offering_id) if assignment.subject_offering_id else None,
            "is_active": assignment.is_active,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Teacher assignment uniqueness conflict.")

    await db.refresh(assignment)
    await db.refresh(klass)
    return _assignment_payload(
        assignment=assignment,
        teacher_user=teacher_user,
        klass=klass,
        grade_level=grade_level,
        academic_year=academic_year,
        subject_offering=subject_offering,
        subject=subject,
    )


@router.patch("/{assignment_id}", summary="Update teacher assignment")
async def update_teacher_assignment(
    assignment_id: uuid.UUID,
    body: TeacherAssignmentUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    assignment = await _load_assignment(db=db, tenant_id=tenant.id, assignment_id=assignment_id)
    teacher, teacher_user = await _load_teacher_context(db=db, tenant_id=tenant.id, teacher_id=assignment.teacher_id)
    academic_year = await _load_academic_year(db=db, tenant_id=tenant.id, academic_year_id=assignment.academic_year_id)
    klass = await _load_class(db=db, tenant_id=tenant.id, class_id=assignment.class_id)
    grade_level = await _load_grade_level(db=db, tenant_id=tenant.id, grade_level_id=klass.grade_level_id)
    subject_offering = None
    subject = None

    if assignment.subject_offering_id is not None:
        subject_offering, subject = await _load_subject_offering(db=db, tenant_id=tenant.id, subject_offering_id=assignment.subject_offering_id)

    next_start_date = body.start_date if body.start_date is not None else assignment.start_date
    next_end_date = body.end_date if body.end_date is not None or "end_date" in body.model_fields_set else assignment.end_date
    next_is_active = body.is_active if body.is_active is not None else assignment.is_active

    _validate_dates_within_year(academic_year=academic_year, start_date=next_start_date, end_date=next_end_date)

    if assignment.assignment_type == "subject_teacher" and subject_offering and subject is not None:
        if subject_offering.academic_year_id != academic_year.id or subject_offering.campus_id != klass.campus_id or subject_offering.grade_level_id != klass.grade_level_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Subject offering scope must match the class canonical scope.")
        qualification = await _load_teacher_subject_qualification(db=db, teacher_id=teacher.id, subject_id=subject.id)
        if qualification is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher is not qualified for this subject offering.")

    if assignment.assignment_type == "homeroom":
        if next_is_active:
            if klass.class_teacher_id is not None and klass.class_teacher_id != teacher.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class already has a different homeroom teacher.")
            klass.class_teacher_id = teacher.id
        elif klass.class_teacher_id == teacher.id:
            klass.class_teacher_id = None

    if next_is_active and assignment.assignment_type == "homeroom":
        await _ensure_no_active_homeroom_conflict(
            db=db,
            tenant_id=tenant.id,
            academic_year_id=assignment.academic_year_id,
            class_id=klass.id,
            exclude_assignment_id=assignment.id,
        )
    if next_is_active and assignment.assignment_type == "subject_teacher" and subject_offering is not None:
        await _ensure_no_active_subject_teacher_conflict(
            db=db,
            tenant_id=tenant.id,
            academic_year_id=assignment.academic_year_id,
            teacher_id=teacher.id,
            class_id=klass.id,
            subject_offering_id=subject_offering.id,
            exclude_assignment_id=assignment.id,
        )

    previous_active = assignment.is_active
    assignment.start_date = next_start_date
    assignment.end_date = next_end_date
    assignment.is_active = next_is_active

    if previous_active != assignment.is_active:
        action = "teacher_assignment.activated" if assignment.is_active else "teacher_assignment.deactivated"
    else:
        action = "teacher_assignment.updated"

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=action,
        entity_type="TeacherAssignment",
        entity_id=assignment.id,
        actor_id=actor.id,
        details={
            "assignment_type": assignment.assignment_type,
            "academic_year_id": str(assignment.academic_year_id),
            "teacher_id": str(assignment.teacher_id),
            "class_id": str(assignment.class_id),
            "subject_offering_id": str(assignment.subject_offering_id) if assignment.subject_offering_id else None,
            "is_active": assignment.is_active,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Teacher assignment uniqueness conflict.")

    await db.refresh(assignment)
    await db.refresh(klass)
    if assignment.subject_offering_id is not None and subject_offering is None:
        subject_offering, subject = await _load_subject_offering(db=db, tenant_id=tenant.id, subject_offering_id=assignment.subject_offering_id)

    return _assignment_payload(
        assignment=assignment,
        teacher_user=teacher_user,
        klass=klass,
        grade_level=grade_level,
        academic_year=academic_year,
        subject_offering=subject_offering,
        subject=subject,
    )


@router.get("/summary", summary="Teacher assignment summary")
async def teacher_assignment_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    total_assignments = int(await db.scalar(select(func.count(TeacherAssignment.id)).where(TeacherAssignment.tenant_id == tenant.id)) or 0)
    active_assignments = int(await db.scalar(select(func.count(TeacherAssignment.id)).where(TeacherAssignment.tenant_id == tenant.id, TeacherAssignment.is_active.is_(True))) or 0)
    inactive_assignments = int(await db.scalar(select(func.count(TeacherAssignment.id)).where(TeacherAssignment.tenant_id == tenant.id, TeacherAssignment.is_active.is_(False))) or 0)
    active_homeroom_assignments = int(
        await db.scalar(
            select(func.count(TeacherAssignment.id)).where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.is_active.is_(True),
                TeacherAssignment.assignment_type == "homeroom",
            )
        )
        or 0
    )
    active_subject_teacher_assignments = int(
        await db.scalar(
            select(func.count(TeacherAssignment.id)).where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.is_active.is_(True),
                TeacherAssignment.assignment_type == "subject_teacher",
            )
        )
        or 0
    )
    teachers_with_active_assignments = int(
        await db.scalar(
            select(func.count(distinct(TeacherAssignment.teacher_id))).where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.is_active.is_(True),
            )
        )
        or 0
    )
    classes_with_active_assignments = int(
        await db.scalar(
            select(func.count(distinct(TeacherAssignment.class_id))).where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.is_active.is_(True),
            )
        )
        or 0
    )

    return {
        "counts": {
            "total_assignments": total_assignments,
            "active_assignments": active_assignments,
            "inactive_assignments": inactive_assignments,
            "active_homeroom_assignments": active_homeroom_assignments,
            "active_subject_teacher_assignments": active_subject_teacher_assignments,
            "teachers_with_active_assignments": teachers_with_active_assignments,
            "classes_with_active_assignments": classes_with_active_assignments,
        }
    }
