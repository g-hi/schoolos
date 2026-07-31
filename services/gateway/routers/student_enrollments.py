from __future__ import annotations

import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import AcademicYear, Class, GradeLevel, Student, StudentEnrollment, Tenant, User

router = APIRouter(prefix="/leadership/student-enrollments", tags=["Student Enrollments"])

_TERMINAL_STATUSES = {"transferred", "withdrawn", "completed"}
_PATCH_ALLOWED_TRANSITIONS = {"withdrawn", "completed"}


class StudentEnrollmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    class_id: uuid.UUID
    enrolled_on: date_type
    status: str = "active"


class StudentEnrollmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    exited_on: date_type | None = None
    exit_reason: str | None = None


class StudentEnrollmentTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_class_id: uuid.UUID
    transfer_date: date_type
    reason: str | None = None


def _validate_status(value: str) -> str:
    if value not in {"active", "transferred", "withdrawn", "completed"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid enrollment status.")
    return value


def _validate_exit_reason(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def _load_student(*, db: AsyncSession, tenant_id: uuid.UUID, student_id: uuid.UUID) -> Student:
    student = await db.scalar(
        select(Student).where(
            Student.id == student_id,
            Student.tenant_id == tenant_id,
        )
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    if hasattr(student, "is_active") and getattr(student, "is_active") is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Student is inactive.")
    return student


async def _load_canonical_class(*, db: AsyncSession, tenant_id: uuid.UUID, class_id: uuid.UUID) -> Class:
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


async def _load_grade_level(*, db: AsyncSession, tenant_id: uuid.UUID, grade_level_id: uuid.UUID) -> GradeLevel:
    grade_level = await db.scalar(
        select(GradeLevel).where(
            GradeLevel.id == grade_level_id,
            GradeLevel.tenant_id == tenant_id,
        )
    )
    if grade_level is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade level not found.")
    if not grade_level.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Grade level is inactive.")
    return grade_level


async def _load_enrollment(*, db: AsyncSession, tenant_id: uuid.UUID, enrollment_id: uuid.UUID) -> StudentEnrollment:
    enrollment = await db.scalar(
        select(StudentEnrollment).where(
            StudentEnrollment.id == enrollment_id,
            StudentEnrollment.tenant_id == tenant_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student enrollment not found.")
    return enrollment


def _validate_enrolled_on_in_academic_year(*, enrolled_on: date_type, academic_year: AcademicYear) -> None:
    if enrolled_on < academic_year.start_date or enrolled_on > academic_year.end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="enrolled_on must fall within the academic year.")


def _validate_exited_on_for_terminal_status(*, exited_on: date_type, enrolled_on: date_type, academic_year: AcademicYear) -> None:
    if exited_on < enrolled_on:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="exited_on cannot be earlier than enrolled_on.")
    upper_bound = academic_year.end_date + timedelta(days=1)
    if exited_on < academic_year.start_date or exited_on > upper_bound:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="exited_on must be within the academic year or the following day.")


async def _ensure_no_active_enrollment(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    exclude_enrollment_id: uuid.UUID | None = None,
) -> None:
    stmt = select(StudentEnrollment.id).where(
        StudentEnrollment.tenant_id == tenant_id,
        StudentEnrollment.student_id == student_id,
        StudentEnrollment.academic_year_id == academic_year_id,
        StudentEnrollment.status == "active",
    )
    if exclude_enrollment_id is not None:
        stmt = stmt.where(StudentEnrollment.id != exclude_enrollment_id)
    duplicate = await db.scalar(stmt)
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active enrollment already exists for this student in this academic year.")


def _enrollment_payload(
    *,
    enrollment: StudentEnrollment,
    student: Student,
    klass: Class,
    academic_year: AcademicYear,
    grade_level: GradeLevel,
) -> dict:
    return {
        "id": str(enrollment.id),
        "student_id": str(enrollment.student_id),
        "student_name": student.name,
        "academic_year_id": str(enrollment.academic_year_id),
        "academic_year_name": academic_year.name,
        "grade_level_id": str(enrollment.grade_level_id),
        "grade_level_name": grade_level.name,
        "class_id": str(enrollment.class_id),
        "class_code": klass.code,
        "class_section": klass.section,
        "status": enrollment.status,
        "enrolled_on": enrollment.enrolled_on,
        "exited_on": enrollment.exited_on,
        "exit_reason": enrollment.exit_reason,
    }


async def _load_payload_context(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    enrollment: StudentEnrollment,
) -> tuple[Student, Class, AcademicYear, GradeLevel]:
    row = (
        await db.execute(
            select(Student, Class, AcademicYear, GradeLevel)
            .join(Class, Class.id == enrollment.class_id)
            .join(AcademicYear, AcademicYear.id == enrollment.academic_year_id)
            .join(GradeLevel, GradeLevel.id == enrollment.grade_level_id)
            .where(
                Student.id == enrollment.student_id,
                Student.tenant_id == tenant_id,
                Class.tenant_id == tenant_id,
                AcademicYear.tenant_id == tenant_id,
                GradeLevel.tenant_id == tenant_id,
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student enrollment context not found.")
    return row


@router.get("", summary="List student enrollments")
async def list_student_enrollments(
    academic_year_id: uuid.UUID | None = Query(default=None),
    student_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    grade_level_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    stmt = (
        select(StudentEnrollment, Student, Class, AcademicYear, GradeLevel)
        .join(Student, Student.id == StudentEnrollment.student_id)
        .join(Class, Class.id == StudentEnrollment.class_id)
        .join(AcademicYear, AcademicYear.id == StudentEnrollment.academic_year_id)
        .join(GradeLevel, GradeLevel.id == StudentEnrollment.grade_level_id)
        .where(StudentEnrollment.tenant_id == tenant.id)
    )
    if academic_year_id is not None:
        stmt = stmt.where(StudentEnrollment.academic_year_id == academic_year_id)
    if student_id is not None:
        stmt = stmt.where(StudentEnrollment.student_id == student_id)
    if class_id is not None:
        stmt = stmt.where(StudentEnrollment.class_id == class_id)
    if grade_level_id is not None:
        stmt = stmt.where(StudentEnrollment.grade_level_id == grade_level_id)
    if status_filter is not None:
        _validate_status(status_filter)
        stmt = stmt.where(StudentEnrollment.status == status_filter)

    rows = (await db.execute(stmt.order_by(AcademicYear.start_date.desc(), Class.grade.asc(), Class.section.asc()))).all()
    return [
        _enrollment_payload(
            enrollment=enrollment,
            student=student,
            klass=klass,
            academic_year=academic_year,
            grade_level=grade_level,
        )
        for enrollment, student, klass, academic_year, grade_level in rows
    ]


@router.post("", summary="Create student enrollment")
async def create_student_enrollment(
    body: StudentEnrollmentCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    status_value = _validate_status(body.status)
    if status_value != "active":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="New enrollments must start as active.")

    student = await _load_student(db=db, tenant_id=tenant.id, student_id=body.student_id)
    klass = await _load_canonical_class(db=db, tenant_id=tenant.id, class_id=body.class_id)
    academic_year = await _load_academic_year(db=db, tenant_id=tenant.id, academic_year_id=klass.academic_year_id)
    grade_level = await _load_grade_level(db=db, tenant_id=tenant.id, grade_level_id=klass.grade_level_id)

    _validate_enrolled_on_in_academic_year(enrolled_on=body.enrolled_on, academic_year=academic_year)
    await _ensure_no_active_enrollment(
        db=db,
        tenant_id=tenant.id,
        student_id=student.id,
        academic_year_id=academic_year.id,
    )

    enrollment = StudentEnrollment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=academic_year.id,
        student_id=student.id,
        class_id=klass.id,
        grade_level_id=grade_level.id,
        status="active",
        enrolled_on=body.enrolled_on,
        exited_on=None,
        exit_reason=None,
    )
    db.add(enrollment)

    student.class_id = klass.id

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="student_enrollment.created",
        entity_type="StudentEnrollment",
        entity_id=enrollment.id,
        actor_id=actor.id,
        details={
            "student_id": str(student.id),
            "class_id": str(klass.id),
            "academic_year_id": str(academic_year.id),
            "grade_level_id": str(grade_level.id),
            "status": enrollment.status,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active enrollment already exists for this student in this academic year.")

    await db.refresh(enrollment)
    return _enrollment_payload(
        enrollment=enrollment,
        student=student,
        klass=klass,
        academic_year=academic_year,
        grade_level=grade_level,
    )


@router.patch("/{enrollment_id}", summary="Update student enrollment lifecycle")
async def update_student_enrollment(
    enrollment_id: uuid.UUID,
    body: StudentEnrollmentUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    enrollment = await _load_enrollment(db=db, tenant_id=tenant.id, enrollment_id=enrollment_id)
    student, klass, academic_year, grade_level = await _load_payload_context(db=db, tenant_id=tenant.id, enrollment=enrollment)

    if enrollment.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active enrollments can be updated via PATCH.")

    next_status = _validate_status(body.status) if body.status is not None else enrollment.status
    next_exit_reason = _validate_exit_reason(body.exit_reason) if "exit_reason" in body.model_fields_set else enrollment.exit_reason

    if next_status == "transferred":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use transfer endpoint for transferred status.")

    if next_status != "active" and next_status not in _PATCH_ALLOWED_TRANSITIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid lifecycle transition.")

    if next_status in _PATCH_ALLOWED_TRANSITIONS:
        if body.exited_on is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="exited_on is required for terminal enrollment status.")
        _validate_exited_on_for_terminal_status(exited_on=body.exited_on, enrolled_on=enrollment.enrolled_on, academic_year=academic_year)
        enrollment.exited_on = body.exited_on
    elif body.exited_on is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="active enrollment cannot have exited_on.")

    enrollment.status = next_status
    enrollment.exit_reason = next_exit_reason

    action = "student_enrollment.withdrawn" if next_status == "withdrawn" else "student_enrollment.completed"
    if next_status != "active":
        await log_action(
            db=db,
            tenant_id=tenant.id,
            action=action,
            entity_type="StudentEnrollment",
            entity_id=enrollment.id,
            actor_id=actor.id,
            details={
                "student_id": str(enrollment.student_id),
                "class_id": str(enrollment.class_id),
                "academic_year_id": str(enrollment.academic_year_id),
                "grade_level_id": str(enrollment.grade_level_id),
                "status": enrollment.status,
            },
        )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enrollment update conflict.")

    await db.refresh(enrollment)
    return _enrollment_payload(
        enrollment=enrollment,
        student=student,
        klass=klass,
        academic_year=academic_year,
        grade_level=grade_level,
    )


@router.post("/{enrollment_id}/transfer", summary="Transfer student enrollment")
async def transfer_student_enrollment(
    enrollment_id: uuid.UUID,
    body: StudentEnrollmentTransferRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    source = await _load_enrollment(db=db, tenant_id=tenant.id, enrollment_id=enrollment_id)
    if source.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active enrollments can be transferred.")

    student = await _load_student(db=db, tenant_id=tenant.id, student_id=source.student_id)
    source_class = await _load_canonical_class(db=db, tenant_id=tenant.id, class_id=source.class_id)
    source_year = await _load_academic_year(db=db, tenant_id=tenant.id, academic_year_id=source.academic_year_id)

    destination_class = await _load_canonical_class(db=db, tenant_id=tenant.id, class_id=body.new_class_id)
    if destination_class.id == source.class_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transfer destination class must be different.")
    if destination_class.academic_year_id != source.academic_year_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transfer class must belong to the same academic year.")

    destination_grade_level = await _load_grade_level(db=db, tenant_id=tenant.id, grade_level_id=destination_class.grade_level_id)

    if body.transfer_date < source.enrolled_on:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="transfer_date cannot be earlier than enrolled_on.")
    _validate_enrolled_on_in_academic_year(enrolled_on=body.transfer_date, academic_year=source_year)
    await _ensure_no_active_enrollment(
        db=db,
        tenant_id=tenant.id,
        student_id=student.id,
        academic_year_id=source.academic_year_id,
        exclude_enrollment_id=source.id,
    )

    source.status = "transferred"
    source.exited_on = body.transfer_date
    source.exit_reason = _validate_exit_reason(body.reason)

    destination = StudentEnrollment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=source.academic_year_id,
        student_id=student.id,
        class_id=destination_class.id,
        grade_level_id=destination_grade_level.id,
        status="active",
        enrolled_on=body.transfer_date,
        exited_on=None,
        exit_reason=None,
    )
    db.add(destination)
    student.class_id = destination_class.id

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="student_enrollment.transferred",
        entity_type="StudentEnrollment",
        entity_id=source.id,
        actor_id=actor.id,
        details={
            "student_id": str(source.student_id),
            "class_id": str(source.class_id),
            "academic_year_id": str(source.academic_year_id),
            "grade_level_id": str(source.grade_level_id),
            "status": source.status,
            "destination_class_id": str(destination_class.id),
        },
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="student_enrollment.transfer_destination_created",
        entity_type="StudentEnrollment",
        entity_id=destination.id,
        actor_id=actor.id,
        details={
            "student_id": str(destination.student_id),
            "class_id": str(destination.class_id),
            "academic_year_id": str(destination.academic_year_id),
            "grade_level_id": str(destination.grade_level_id),
            "status": destination.status,
        },
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transfer conflicts with existing active enrollment.")

    await db.refresh(source)
    await db.refresh(destination)

    source_grade = await _load_grade_level(db=db, tenant_id=tenant.id, grade_level_id=source.grade_level_id)
    return {
        "source_enrollment": _enrollment_payload(
            enrollment=source,
            student=student,
            klass=source_class,
            academic_year=source_year,
            grade_level=source_grade,
        ),
        "destination_enrollment": _enrollment_payload(
            enrollment=destination,
            student=student,
            klass=destination_class,
            academic_year=source_year,
            grade_level=destination_grade_level,
        ),
    }


@router.get("/summary", summary="Student enrollment summary")
async def student_enrollment_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    total_enrollments = int(await db.scalar(select(func.count(StudentEnrollment.id)).where(StudentEnrollment.tenant_id == tenant.id)) or 0)
    active_enrollments = int(
        await db.scalar(select(func.count(StudentEnrollment.id)).where(StudentEnrollment.tenant_id == tenant.id, StudentEnrollment.status == "active")) or 0
    )
    transferred_enrollments = int(
        await db.scalar(select(func.count(StudentEnrollment.id)).where(StudentEnrollment.tenant_id == tenant.id, StudentEnrollment.status == "transferred")) or 0
    )
    withdrawn_enrollments = int(
        await db.scalar(select(func.count(StudentEnrollment.id)).where(StudentEnrollment.tenant_id == tenant.id, StudentEnrollment.status == "withdrawn")) or 0
    )
    completed_enrollments = int(
        await db.scalar(select(func.count(StudentEnrollment.id)).where(StudentEnrollment.tenant_id == tenant.id, StudentEnrollment.status == "completed")) or 0
    )

    active_student_ids = {
        row[0]
        for row in (
            await db.execute(
                select(StudentEnrollment.student_id)
                .where(
                    StudentEnrollment.tenant_id == tenant.id,
                    StudentEnrollment.status == "active",
                )
                .distinct()
            )
        ).all()
    }

    legacy_only_stmt = select(func.count(Student.id)).where(
        Student.tenant_id == tenant.id,
        Student.class_id.is_not(None),
    )
    if active_student_ids:
        legacy_only_stmt = legacy_only_stmt.where(Student.id.not_in(active_student_ids))
    legacy_only_count = int(await db.scalar(legacy_only_stmt) or 0)

    active_by_class_rows = (
        await db.execute(
            select(Class.id, Class.code, Class.section, func.count(StudentEnrollment.id))
            .join(StudentEnrollment, StudentEnrollment.class_id == Class.id)
            .where(
                StudentEnrollment.tenant_id == tenant.id,
                StudentEnrollment.status == "active",
                Class.tenant_id == tenant.id,
            )
            .group_by(Class.id, Class.code, Class.section)
            .order_by(Class.grade.asc(), Class.section.asc())
        )
    ).all()

    active_by_grade_rows = (
        await db.execute(
            select(GradeLevel.id, GradeLevel.name, func.count(StudentEnrollment.id))
            .join(StudentEnrollment, StudentEnrollment.grade_level_id == GradeLevel.id)
            .where(
                StudentEnrollment.tenant_id == tenant.id,
                StudentEnrollment.status == "active",
                GradeLevel.tenant_id == tenant.id,
            )
            .group_by(GradeLevel.id, GradeLevel.name)
            .order_by(GradeLevel.name.asc())
        )
    ).all()

    return {
        "total_enrollments": total_enrollments,
        "active_enrollments": active_enrollments,
        "transferred_enrollments": transferred_enrollments,
        "withdrawn_enrollments": withdrawn_enrollments,
        "completed_enrollments": completed_enrollments,
        "students_with_active_canonical_enrollment": len(active_student_ids),
        "students_with_legacy_class_id_but_no_canonical_enrollment": legacy_only_count,
        "active_enrollments_by_class": [
            {
                "class_id": str(class_id),
                "class_code": class_code,
                "class_section": class_section,
                "count": int(count),
            }
            for class_id, class_code, class_section, count in active_by_class_rows
        ],
        "active_enrollments_by_grade_level": [
            {
                "grade_level_id": str(grade_level_id),
                "grade_level_name": grade_level_name,
                "count": int(count),
            }
            for grade_level_id, grade_level_name, count in active_by_grade_rows
        ],
    }