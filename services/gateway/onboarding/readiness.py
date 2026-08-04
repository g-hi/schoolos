from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    AcademicYear,
    AccountInvitation,
    Campus,
    Class,
    ImportBatch,
    Student,
    StudentEnrollment,
    StudentParent,
    Subject,
    SubjectOffering,
    Teacher,
    TeacherAssignment,
    TimetableEntry,
    User,
)

CHECK_STATUS_COMPLETE = "complete"
CHECK_STATUS_BLOCKING = "blocking"
CHECK_STATUS_WARNING = "warning"
CHECK_STATUS_INFORMATIONAL = "informational"

STEP_GROUPS = {
    "Foundation": ["campus", "academic_year", "terms", "grade_levels", "subjects"],
    "Academic structure": ["classes", "subject_offerings"],
    "People": ["people", "family_relationships"],
    "Academic operations": ["teacher_assignments", "student_enrolments", "timetable"],
    "Data": ["data_imports"],
    "Completion": ["readiness_review"],
}

STEP_CATALOGUE = [
    "campus",
    "academic_year",
    "terms",
    "grade_levels",
    "subjects",
    "classes",
    "subject_offerings",
    "people",
    "family_relationships",
    "teacher_assignments",
    "student_enrolments",
    "timetable",
    "data_imports",
    "readiness_review",
]

OPTIONAL_SKIP_STEPS = {"data_imports"}
SAFE_ACTION_ROUTES = {"/academic-structure", "/people", "/data", "/timetable"}


@dataclass
class ReadinessContext:
    tenant_id: uuid.UUID
    now: datetime


def _check(
    *,
    check_key: str,
    step_key: str,
    title: str,
    status: str,
    current_value: Any,
    required_value: Any,
    message: str,
    recommended_action: str,
    action_route: str,
    evidence_source: str,
) -> dict[str, Any]:
    route = action_route if action_route in SAFE_ACTION_ROUTES else "/academic-structure"
    return {
        "check_key": check_key,
        "step_key": step_key,
        "title": title,
        "status": status,
        "current_value": current_value,
        "required_value": required_value,
        "message": message,
        "recommended_action": recommended_action,
        "action_route": route,
        "evidence_source": evidence_source,
    }


async def _count(db: AsyncSession, stmt) -> int:
    value = await db.scalar(stmt)
    return int(value or 0)


async def compute_readiness(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    ctx = ReadinessContext(tenant_id=tenant_id, now=datetime.now(timezone.utc))
    checks: list[dict[str, Any]] = []

    active_campuses = await _count(
        db,
        select(func.count(Campus.id)).where(Campus.tenant_id == tenant_id, Campus.is_active.is_(True)),
    )
    checks.append(
        _check(
            check_key="foundation_active_campus",
            step_key="campus",
            title="At least one active campus",
            status=CHECK_STATUS_COMPLETE if active_campuses > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_campuses,
            required_value=1,
            message="Campus setup is required before operational structures can be configured.",
            recommended_action="Create and activate at least one campus.",
            action_route="/academic-structure",
            evidence_source="campuses",
        )
    )

    current_year = await db.scalar(
        select(AcademicYear).where(
            AcademicYear.tenant_id == tenant_id,
            AcademicYear.is_active.is_(True),
            AcademicYear.is_current.is_(True),
        )
    )
    checks.append(
        _check(
            check_key="foundation_current_academic_year",
            step_key="academic_year",
            title="One current active academic year",
            status=CHECK_STATUS_COMPLETE if current_year is not None else CHECK_STATUS_BLOCKING,
            current_value=1 if current_year else 0,
            required_value=1,
            message="A current academic year is required for canonical operations.",
            recommended_action="Mark exactly one active academic year as current.",
            action_route="/academic-structure",
            evidence_source="academic_years",
        )
    )

    active_terms = 0
    if current_year is not None:
        from shared.db.models import Term

        active_terms = await _count(
            db,
            select(func.count(Term.id)).where(
                Term.tenant_id == tenant_id,
                Term.academic_year_id == current_year.id,
                Term.is_active.is_(True),
            ),
        )
    checks.append(
        _check(
            check_key="foundation_active_terms",
            step_key="terms",
            title="At least one active term in current year",
            status=CHECK_STATUS_COMPLETE if active_terms > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_terms,
            required_value=1,
            message="Term setup is required for scheduling windows and reporting cadence.",
            recommended_action="Create at least one active term in the current year.",
            action_route="/academic-structure",
            evidence_source="terms",
        )
    )

    from shared.db.models import GradeLevel

    active_grade_levels = await _count(
        db,
        select(func.count(GradeLevel.id)).where(GradeLevel.tenant_id == tenant_id, GradeLevel.is_active.is_(True)),
    )
    checks.append(
        _check(
            check_key="foundation_active_grade_levels",
            step_key="grade_levels",
            title="At least one active grade level",
            status=CHECK_STATUS_COMPLETE if active_grade_levels > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_grade_levels,
            required_value=1,
            message="Grade levels are required for canonical class and enrollment scope.",
            recommended_action="Create and activate grade levels.",
            action_route="/academic-structure",
            evidence_source="grade_levels",
        )
    )

    subjects_count = await _count(db, select(func.count(Subject.id)).where(Subject.tenant_id == tenant_id))
    checks.append(
        _check(
            check_key="foundation_subjects",
            step_key="subjects",
            title="At least one subject",
            status=CHECK_STATUS_COMPLETE if subjects_count > 0 else CHECK_STATUS_BLOCKING,
            current_value=subjects_count,
            required_value=1,
            message="Subject catalog is required for offering and assignment coverage.",
            recommended_action="Create at least one subject.",
            action_route="/academic-structure",
            evidence_source="subjects",
        )
    )

    active_canonical_classes = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    checks.append(
        _check(
            check_key="academic_active_canonical_classes",
            step_key="classes",
            title="At least one active canonical class",
            status=CHECK_STATUS_COMPLETE if active_canonical_classes > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_canonical_classes,
            required_value=1,
            message="Canonical classes are required for assignments, enrollments and timetable checks.",
            recommended_action="Create at least one canonical active class.",
            action_route="/academic-structure",
            evidence_source="classes",
        )
    )

    invalid_scope_classes = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            or_(
                and_(Class.campus_id.is_(None), or_(Class.academic_year_id.is_not(None), Class.grade_level_id.is_not(None))),
                and_(Class.academic_year_id.is_(None), or_(Class.campus_id.is_not(None), Class.grade_level_id.is_not(None))),
                and_(Class.grade_level_id.is_(None), or_(Class.campus_id.is_not(None), Class.academic_year_id.is_not(None))),
            ),
        ),
    )
    checks.append(
        _check(
            check_key="academic_class_scope_integrity",
            step_key="classes",
            title="Active canonical classes have valid campus/year/grade scope",
            status=CHECK_STATUS_COMPLETE if invalid_scope_classes == 0 else CHECK_STATUS_BLOCKING,
            current_value=invalid_scope_classes,
            required_value=0,
            message="Canonical scope must be complete for each active canonical class.",
            recommended_action="Fix classes missing canonical scope references.",
            action_route="/academic-structure",
            evidence_source="classes",
        )
    )

    active_classes_without_year = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.grade_level_id.is_not(None),
            Class.academic_year_id.is_(None),
        ),
    )
    checks.append(
        _check(
            check_key="academic_class_missing_academic_year",
            step_key="classes",
            title="No active canonical class without an academic year",
            status=CHECK_STATUS_COMPLETE if active_classes_without_year == 0 else CHECK_STATUS_BLOCKING,
            current_value=active_classes_without_year,
            required_value=0,
            message="Active canonical classes must always be tied to an academic year.",
            recommended_action="Assign academic year to all active canonical classes.",
            action_route="/academic-structure",
            evidence_source="classes",
        )
    )

    offering_count = await _count(db, select(func.count(SubjectOffering.id)).where(SubjectOffering.tenant_id == tenant_id, SubjectOffering.is_active.is_(True)))
    checks.append(
        _check(
            check_key="academic_subject_offerings",
            step_key="subject_offerings",
            title="At least one active subject offering",
            status=CHECK_STATUS_COMPLETE if offering_count > 0 else CHECK_STATUS_BLOCKING,
            current_value=offering_count,
            required_value=1,
            message="Subject offerings are required for subject-teacher assignment coverage.",
            recommended_action="Create active subject offerings for class scope.",
            action_route="/academic-structure",
            evidence_source="subject_offerings",
        )
    )

    active_leadership = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.role.in_(["principal", "school_admin"]),
        ),
    )
    checks.append(
        _check(
            check_key="people_active_leadership",
            step_key="people",
            title="At least one active leadership account",
            status=CHECK_STATUS_COMPLETE if active_leadership > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_leadership,
            required_value=1,
            message="Leadership accounts are required for governance and approval workflows.",
            recommended_action="Activate at least one principal or school_admin account.",
            action_route="/people",
            evidence_source="users",
        )
    )

    active_teacher_profiles = await _count(
        db,
        select(func.count(Teacher.id))
        .join(User, User.id == Teacher.user_id)
        .where(Teacher.tenant_id == tenant_id, User.tenant_id == tenant_id, User.is_active.is_(True)),
    )
    checks.append(
        _check(
            check_key="people_active_teacher_profile",
            step_key="people",
            title="At least one active teacher account/profile",
            status=CHECK_STATUS_COMPLETE if active_teacher_profiles > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_teacher_profiles,
            required_value=1,
            message="Teacher profile coverage is required for class operations.",
            recommended_action="Provision at least one active teacher profile.",
            action_route="/people",
            evidence_source="teachers_users",
        )
    )

    active_teacher_users_without_profile = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.role == "teacher",
            User.is_active.is_(True),
            ~User.id.in_(select(Teacher.user_id).where(Teacher.tenant_id == tenant_id)),
        ),
    )
    checks.append(
        _check(
            check_key="people_teacher_user_profile_consistency",
            step_key="people",
            title="No active teacher user without teacher profile",
            status=CHECK_STATUS_COMPLETE if active_teacher_users_without_profile == 0 else CHECK_STATUS_BLOCKING,
            current_value=active_teacher_users_without_profile,
            required_value=0,
            message="Teacher users must map to teacher profiles.",
            recommended_action="Provision missing teacher profiles or deactivate inconsistent users.",
            action_route="/people",
            evidence_source="users_teachers",
        )
    )

    active_parent_users_without_relationship = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.role == "parent",
            User.is_active.is_(True),
            ~User.id.in_(select(StudentParent.parent_id)),
        ),
    )
    checks.append(
        _check(
            check_key="people_parent_profile_consistency",
            step_key="people",
            title="No active parent user without expected parent compatibility",
            status=CHECK_STATUS_COMPLETE if active_parent_users_without_relationship == 0 else CHECK_STATUS_BLOCKING,
            current_value=active_parent_users_without_relationship,
            required_value=0,
            message="Active parent users should be linked to at least one student relationship.",
            recommended_action="Link parent users to students or deactivate inconsistent accounts.",
            action_route="/people",
            evidence_source="users_student_parents",
        )
    )

    active_students = await _count(db, select(func.count(Student.id)).where(Student.tenant_id == tenant_id))
    checks.append(
        _check(
            check_key="people_active_students",
            step_key="people",
            title="At least one active student",
            status=CHECK_STATUS_COMPLETE if active_students > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_students,
            required_value=1,
            message="Student records are required for enrollment and timetable operations.",
            recommended_action="Create student records.",
            action_route="/people",
            evidence_source="students",
        )
    )

    active_homeroom_classes = await _count(
        db,
        select(func.count(func.distinct(TeacherAssignment.class_id))).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.is_active.is_(True),
            TeacherAssignment.assignment_type == "homeroom",
        ),
    )
    classes_missing_homeroom = max(active_canonical_classes - active_homeroom_classes, 0)
    checks.append(
        _check(
            check_key="ops_homeroom_coverage",
            step_key="teacher_assignments",
            title="Active classes have homeroom coverage",
            status=CHECK_STATUS_COMPLETE if classes_missing_homeroom == 0 else CHECK_STATUS_BLOCKING,
            current_value=classes_missing_homeroom,
            required_value=0,
            message="Homeroom coverage is required for active classes.",
            recommended_action="Create homeroom assignments for uncovered classes.",
            action_route="/academic-structure",
            evidence_source="teacher_assignments",
        )
    )

    subject_assignment_count = await _count(
        db,
        select(func.count(TeacherAssignment.id)).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.is_active.is_(True),
            TeacherAssignment.assignment_type == "subject_teacher",
        ),
    )
    checks.append(
        _check(
            check_key="ops_subject_teacher_coverage_report",
            step_key="teacher_assignments",
            title="Subject-teacher assignment coverage is reported",
            status=CHECK_STATUS_COMPLETE if subject_assignment_count > 0 else CHECK_STATUS_WARNING,
            current_value=subject_assignment_count,
            required_value=1,
            message="Subject-teacher assignments improve timetable quality and substitution confidence.",
            recommended_action="Add subject-teacher assignments where needed.",
            action_route="/academic-structure",
            evidence_source="teacher_assignments",
        )
    )

    active_canonical_students = await _count(
        db,
        select(func.count(Student.id))
        .join(Class, Class.id == Student.class_id)
        .where(
            Student.tenant_id == tenant_id,
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    active_enrolled_students = await _count(
        db,
        select(func.count(func.distinct(StudentEnrollment.student_id)))
        .join(Student, Student.id == StudentEnrollment.student_id)
        .join(Class, Class.id == StudentEnrollment.class_id)
        .where(
            StudentEnrollment.tenant_id == tenant_id,
            StudentEnrollment.status == "active",
            Student.tenant_id == tenant_id,
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    enrollment_gap = max(active_canonical_students - active_enrolled_students, 0)
    checks.append(
        _check(
            check_key="ops_active_student_enrollment_coverage",
            step_key="student_enrolments",
            title="Active canonical students have active enrollments",
            status=CHECK_STATUS_COMPLETE if enrollment_gap == 0 else CHECK_STATUS_BLOCKING,
            current_value=enrollment_gap,
            required_value=0,
            message="Canonical student records require active enrollment coverage.",
            recommended_action="Create missing active enrollments for canonical students.",
            action_route="/academic-structure",
            evidence_source="student_enrollments",
        )
    )

    multiple_active_enrollment = await _count(
        db,
        select(func.count())
        .select_from(
            select(
                StudentEnrollment.student_id,
                StudentEnrollment.academic_year_id,
                func.count(StudentEnrollment.id).label("c"),
            )
            .where(StudentEnrollment.tenant_id == tenant_id, StudentEnrollment.status == "active")
            .group_by(StudentEnrollment.student_id, StudentEnrollment.academic_year_id)
            .having(func.count(StudentEnrollment.id) > 1)
            .subquery()
        ),
    )
    checks.append(
        _check(
            check_key="ops_multiple_active_enrollment_diagnostic",
            step_key="student_enrolments",
            title="No multiple-active-enrollment diagnostic",
            status=CHECK_STATUS_COMPLETE if multiple_active_enrollment == 0 else CHECK_STATUS_BLOCKING,
            current_value=multiple_active_enrollment,
            required_value=0,
            message="A student must not have multiple active enrollments in the same year.",
            recommended_action="Resolve duplicate active enrollment records.",
            action_route="/academic-structure",
            evidence_source="student_enrollments",
        )
    )

    stale_class_pointer_conflicts = await _count(
        db,
        select(func.count(Student.id))
        .join(Class, Class.id == Student.class_id)
        .where(
            Student.tenant_id == tenant_id,
            Class.tenant_id == tenant_id,
            Class.campus_id.is_(None),
            Student.id.in_(
                select(StudentEnrollment.student_id).where(
                    StudentEnrollment.tenant_id == tenant_id,
                    StudentEnrollment.status == "active",
                )
            ),
        ),
    )
    checks.append(
        _check(
            check_key="ops_stale_class_pointer_conflict",
            step_key="student_enrolments",
            title="No stale canonical/legacy class conflicts",
            status=CHECK_STATUS_COMPLETE if stale_class_pointer_conflicts == 0 else CHECK_STATUS_BLOCKING,
            current_value=stale_class_pointer_conflicts,
            required_value=0,
            message="Students with active canonical enrollments should not point to legacy classes.",
            recommended_action="Realign student class pointers with canonical active enrollments.",
            action_route="/academic-structure",
            evidence_source="students_classes_enrollments",
        )
    )

    students_without_parent_guardian = await _count(
        db,
        select(func.count(Student.id)).where(
            Student.tenant_id == tenant_id,
            ~Student.id.in_(
                select(StudentParent.student_id).where(
                    StudentParent.relation_type.in_(["parent", "mother", "father", "guardian"]),
                    or_(StudentParent.is_active.is_(True), StudentParent.is_active.is_(None)),
                )
            ),
        ),
    )
    checks.append(
        _check(
            check_key="family_students_without_parent_guardian",
            step_key="family_relationships",
            title="Students without active parent/guardian relationships",
            status=CHECK_STATUS_COMPLETE if students_without_parent_guardian == 0 else CHECK_STATUS_WARNING,
            current_value=students_without_parent_guardian,
            required_value=0,
            message="Parent/guardian relationship completeness improves communication readiness.",
            recommended_action="Link students to active parent/guardian relationships.",
            action_route="/people",
            evidence_source="student_parents",
        )
    )

    inactive_family_history = await _count(
        db,
        select(func.count()).select_from(StudentParent).where(
            or_(StudentParent.is_active.is_(False), StudentParent.is_active.is_(None)),
        ),
    )
    checks.append(
        _check(
            check_key="family_inactive_history",
            step_key="family_relationships",
            title="Inactive family history",
            status=CHECK_STATUS_INFORMATIONAL,
            current_value=inactive_family_history,
            required_value="n/a",
            message="Inactive relationship history is retained for audit and timeline continuity.",
            recommended_action="Review only if relationship history appears unexpected.",
            action_route="/people",
            evidence_source="student_parents",
        )
    )

    active_timetable_entries = await _count(
        db,
        select(func.count(TimetableEntry.id)).where(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.is_active.is_(True),
        ),
    )
    checks.append(
        _check(
            check_key="ops_timetable_required",
            step_key="timetable",
            title="Active timetable entries exist",
            status=CHECK_STATUS_COMPLETE if active_timetable_entries > 0 else CHECK_STATUS_BLOCKING,
            current_value=active_timetable_entries,
            required_value=1,
            message="Timetable publication requires active entries.",
            recommended_action="Upload or generate timetable entries for active classes.",
            action_route="/timetable",
            evidence_source="timetable_entries",
        )
    )

    classes_with_timetable = await _count(
        db,
        select(func.count(func.distinct(TimetableEntry.class_id)))
        .join(Class, Class.id == TimetableEntry.class_id)
        .where(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.is_active.is_(True),
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    timetable_gap_classes = max(active_canonical_classes - classes_with_timetable, 0)
    checks.append(
        _check(
            check_key="ops_timetable_gap_for_active_classes",
            step_key="timetable",
            title="Timetable gaps for expected active classes",
            status=CHECK_STATUS_COMPLETE if timetable_gap_classes == 0 else CHECK_STATUS_BLOCKING,
            current_value=timetable_gap_classes,
            required_value=0,
            message="Active classes expected to operate should have timetable coverage.",
            recommended_action="Publish timetable coverage for all active classes.",
            action_route="/timetable",
            evidence_source="classes_timetable_entries",
        )
    )

    recent_since = ctx.now - timedelta(days=30)
    failed_imports = await _count(
        db,
        select(func.count(ImportBatch.id)).where(
            ImportBatch.tenant_id == tenant_id,
            ImportBatch.status.in_(["failed", "completed_with_errors"]),
            ImportBatch.created_at >= recent_since,
        ),
    )
    checks.append(
        _check(
            check_key="data_recent_failed_or_error_imports",
            step_key="data_imports",
            title="Recent failed/error imports",
            status=CHECK_STATUS_WARNING if failed_imports > 0 else CHECK_STATUS_COMPLETE,
            current_value=failed_imports,
            required_value=0,
            message="Failed or partial imports may indicate unresolved data quality issues.",
            recommended_action="Review import history and correct unresolved errors.",
            action_route="/data",
            evidence_source="import_batches",
        )
    )

    preview_ready_imports = await _count(
        db,
        select(func.count(ImportBatch.id)).where(
            ImportBatch.tenant_id == tenant_id,
            ImportBatch.status == "preview_ready",
        ),
    )
    checks.append(
        _check(
            check_key="data_preview_ready_uncommitted_imports",
            step_key="data_imports",
            title="Preview-ready uncommitted imports",
            status=CHECK_STATUS_INFORMATIONAL if preview_ready_imports > 0 else CHECK_STATUS_COMPLETE,
            current_value=preview_ready_imports,
            required_value=0,
            message="Preview-ready batches are pending a deliberate commit decision.",
            recommended_action="Commit or cancel pending preview batches.",
            action_route="/data",
            evidence_source="import_batches",
        )
    )

    pending_invitations = await _count(
        db,
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant_id,
            AccountInvitation.accepted_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
            AccountInvitation.expires_at > ctx.now,
        ),
    )
    checks.append(
        _check(
            check_key="people_pending_invitations",
            step_key="people",
            title="Pending invitations",
            status=CHECK_STATUS_INFORMATIONAL if pending_invitations > 0 else CHECK_STATUS_COMPLETE,
            current_value=pending_invitations,
            required_value=0,
            message="Pending invitations are tracked for activation follow-up.",
            recommended_action="Monitor pending invitations and follow up as needed.",
            action_route="/people",
            evidence_source="account_invitations",
        )
    )

    expired_invitations = await _count(
        db,
        select(func.count(AccountInvitation.id)).where(
            AccountInvitation.tenant_id == tenant_id,
            AccountInvitation.accepted_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
            AccountInvitation.expires_at <= ctx.now,
        ),
    )
    checks.append(
        _check(
            check_key="people_expired_invitations",
            step_key="people",
            title="Expired invitations",
            status=CHECK_STATUS_WARNING if expired_invitations > 0 else CHECK_STATUS_COMPLETE,
            current_value=expired_invitations,
            required_value=0,
            message="Expired invitations indicate onboarding friction for invited users.",
            recommended_action="Reissue or revoke expired invitations.",
            action_route="/people",
            evidence_source="account_invitations",
        )
    )

    inactive_users_with_active_teacher_profile = await _count(
        db,
        select(func.count(Teacher.id))
        .join(User, User.id == Teacher.user_id)
        .where(Teacher.tenant_id == tenant_id, User.tenant_id == tenant_id, User.is_active.is_(False)),
    )
    checks.append(
        _check(
            check_key="people_inactive_users_with_active_profiles",
            step_key="people",
            title="Inactive users with active profiles",
            status=CHECK_STATUS_WARNING if inactive_users_with_active_teacher_profile > 0 else CHECK_STATUS_COMPLETE,
            current_value=inactive_users_with_active_teacher_profile,
            required_value=0,
            message="Inactive accounts tied to active profiles should be reviewed.",
            recommended_action="Reconcile inactive users and their profile lifecycle.",
            action_route="/people",
            evidence_source="users_teachers",
        )
    )

    blocker_count = sum(1 for check in checks if check["status"] == CHECK_STATUS_BLOCKING)
    warning_count = sum(1 for check in checks if check["status"] == CHECK_STATUS_WARNING)
    informational_count = sum(1 for check in checks if check["status"] == CHECK_STATUS_INFORMATIONAL)
    complete_count = sum(1 for check in checks if check["status"] == CHECK_STATUS_COMPLETE)

    readiness_percentage = int(round((complete_count / len(checks)) * 100)) if checks else 0

    grouped_checks: dict[str, list[dict[str, Any]]] = {group: [] for group in STEP_GROUPS}
    for check in checks:
        group_name = next((g for g, steps in STEP_GROUPS.items() if check["step_key"] in steps), "Foundation")
        grouped_checks[group_name].append(check)

    step_statuses: dict[str, str] = {step: "not_started" for step in STEP_CATALOGUE}
    for step in STEP_CATALOGUE:
        step_checks = [check for check in checks if check["step_key"] == step]
        if any(check["status"] == CHECK_STATUS_BLOCKING for check in step_checks):
            step_statuses[step] = "blocked"
        elif step_checks and all(check["status"] in {CHECK_STATUS_COMPLETE, CHECK_STATUS_WARNING, CHECK_STATUS_INFORMATIONAL} for check in step_checks):
            step_statuses[step] = "completed"
        else:
            step_statuses[step] = "in_progress"

    recommended_next_actions = []
    for check in checks:
        if check["status"] in {CHECK_STATUS_BLOCKING, CHECK_STATUS_WARNING}:
            recommended_next_actions.append(
                {
                    "step_key": check["step_key"],
                    "check_key": check["check_key"],
                    "message": check["recommended_action"],
                    "action_route": check["action_route"],
                }
            )

    return {
        "readiness_percentage": readiness_percentage,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "informational_count": informational_count,
        "checks": checks,
        "grouped_checks": grouped_checks,
        "step_statuses": step_statuses,
        "recommended_next_actions": recommended_next_actions,
        "is_ready": blocker_count == 0,
    }
