from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AcademicYear, Class, GradeLevel, Student, StudentEnrollment


@dataclass(frozen=True)
class StudentClassResolution:
    """
    Result of resolving a student's current class.

    source:
        'canonical'  – resolved from an active StudentEnrollment
        'legacy'     – resolved from Student.class_id fallback
        'none'       – could not resolve a class

    denied_due_to_canonical_history:
        True when canonical enrollment history exists for this student/year
        but no qualifying active enrollment was found.  In this case the
        legacy fallback is intentionally blocked.
    """
    class_id: uuid.UUID | None
    enrollment_id: uuid.UUID | None
    source: str
    status: str | None
    denied_due_to_canonical_history: bool
    reason: str


async def resolve_student_class(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    effective_date: date_type | None = None,
    academic_year_id: uuid.UUID | None = None,
) -> StudentClassResolution:
    """
    Return the class for a student at the effective date.

    Resolution order:
    1. Look for an active canonical StudentEnrollment.
       Conditions for a qualifying canonical enrollment:
         - status = 'active'
         - enrolled_on <= effective_date (or any date when effective_date is None)
         - exited_on IS NULL
         - student, class, academic year, grade level belong to tenant
         - class and academic year are active
         - enrollment academic_year_id matches Class.academic_year_id
         - enrollment grade_level_id matches Class.grade_level_id
         - when academic_year_id filter is supplied, enrollment must match it
    2. If canonical history exists (regardless of whether a qualifying
       enrollment was found) → block legacy fallback and return denied result.
    3. When NO canonical history exists → fall back to Student.class_id,
       validated to the same tenant.
    """
    stmt = (
        select(StudentEnrollment, Class, AcademicYear, GradeLevel)
        .join(Class, Class.id == StudentEnrollment.class_id)
        .join(AcademicYear, AcademicYear.id == StudentEnrollment.academic_year_id)
        .join(GradeLevel, GradeLevel.id == StudentEnrollment.grade_level_id)
        .where(
            StudentEnrollment.tenant_id == tenant_id,
            StudentEnrollment.student_id == student_id,
            Class.tenant_id == tenant_id,
            AcademicYear.tenant_id == tenant_id,
            GradeLevel.tenant_id == tenant_id,
            Class.is_active.is_(True),
            AcademicYear.is_active.is_(True),
            StudentEnrollment.academic_year_id == Class.academic_year_id,
            StudentEnrollment.grade_level_id == Class.grade_level_id,
        )
    )
    if academic_year_id is not None:
        stmt = stmt.where(StudentEnrollment.academic_year_id == academic_year_id)

    all_rows = (await db.execute(stmt)).all()

    canonical_history_exists = len(all_rows) > 0

    # Try to find an active qualifying enrollment
    for enrollment, klass, academic_year, grade_level in all_rows:
        if enrollment.status != "active":
            continue
        if enrollment.exited_on is not None:
            continue
        if effective_date is not None and enrollment.enrolled_on > effective_date:
            continue
        return StudentClassResolution(
            class_id=klass.id,
            enrollment_id=enrollment.id,
            source="canonical",
            status="active",
            denied_due_to_canonical_history=False,
            reason="matched_active_canonical_enrollment",
        )

    if canonical_history_exists:
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="canonical",
            status=None,
            denied_due_to_canonical_history=True,
            reason="canonical_history_exists_but_no_active_enrollment",
        )

    # Fallback to Student.class_id
    student = await db.scalar(
        select(Student).where(
            Student.id == student_id,
            Student.tenant_id == tenant_id,
        )
    )
    if student is None:
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="none",
            status=None,
            denied_due_to_canonical_history=False,
            reason="student_not_found",
        )
    if student.class_id is None:
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="none",
            status=None,
            denied_due_to_canonical_history=False,
            reason="student_has_no_class_id",
        )

    klass = await db.scalar(
        select(Class).where(
            Class.id == student.class_id,
            Class.tenant_id == tenant_id,
        )
    )
    if klass is None:
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="none",
            status=None,
            denied_due_to_canonical_history=False,
            reason="legacy_class_not_found_or_wrong_tenant",
        )

    return StudentClassResolution(
        class_id=klass.id,
        enrollment_id=None,
        source="legacy",
        status="active",
        denied_due_to_canonical_history=False,
        reason="legacy_student_class_id_fallback",
    )


async def student_belongs_to_class(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    class_id: uuid.UUID,
    effective_date: date_type | None = None,
    academic_year_id: uuid.UUID | None = None,
) -> StudentClassResolution:
    """
    Return a resolution confirming whether the student belongs to a specific class.

    If the resolved class matches class_id, the result is returned as-is.
    If there is a mismatch, the result will have source='none' and
    the resolution from resolve_student_class is embedded in the reason.
    """
    resolution = await resolve_student_class(
        db=db,
        tenant_id=tenant_id,
        student_id=student_id,
        effective_date=effective_date,
        academic_year_id=academic_year_id,
    )
    if resolution.class_id == class_id:
        return resolution
    return StudentClassResolution(
        class_id=None,
        enrollment_id=None,
        source="none",
        status=None,
        denied_due_to_canonical_history=resolution.denied_due_to_canonical_history,
        reason=f"class_mismatch:{resolution.reason}",
    )


async def list_class_student_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    effective_date: date_type | None = None,
) -> dict:
    """
    Return student IDs for a class using canonical-first resolution.

    Returns:
    {
        "canonical_student_ids":  set of student IDs with active canonical enrollment
        "legacy_student_ids":     set of student IDs from Student.class_id fallback
                                  (only those with NO canonical enrollment history at all)
        "all_student_ids":        union of the above (deduplicated)
    }
    """
    # Canonical active enrollments for this class
    canonical_stmt = select(StudentEnrollment.student_id).where(
        StudentEnrollment.tenant_id == tenant_id,
        StudentEnrollment.class_id == class_id,
        StudentEnrollment.status == "active",
    )
    if effective_date is not None:
        canonical_stmt = canonical_stmt.where(
            StudentEnrollment.enrolled_on <= effective_date,
        )
    canonical_rows = (await db.execute(canonical_stmt)).all()
    canonical_student_ids = {row[0] for row in canonical_rows}

    # Student IDs that have any canonical enrollment history (any class/year)
    any_canonical_history_rows = (
        await db.execute(
            select(StudentEnrollment.student_id)
            .where(
                StudentEnrollment.tenant_id == tenant_id,
            )
            .distinct()
        )
    ).all()
    students_with_any_canonical_history = {row[0] for row in any_canonical_history_rows}

    # Legacy fallback: Student.class_id for students with no canonical history at all
    legacy_stmt = select(Student.id).where(
        Student.tenant_id == tenant_id,
        Student.class_id == class_id,
        Student.id.not_in(students_with_any_canonical_history) if students_with_any_canonical_history else True,
    )
    legacy_rows = (await db.execute(legacy_stmt)).all()
    legacy_student_ids = {row[0] for row in legacy_rows}

    return {
        "canonical_student_ids": canonical_student_ids,
        "legacy_student_ids": legacy_student_ids,
        "all_student_ids": canonical_student_ids | legacy_student_ids,
    }
