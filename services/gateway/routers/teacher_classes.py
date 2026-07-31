from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.dependencies import resolve_authenticated_teacher
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    Campus,
    Class,
    Student,
    Subject,
    SubjectOffering,
    Teacher,
    TeacherAssignment,
    Tenant,
    TimetableEntry,
    User,
)

router = APIRouter(prefix="/teacher/my-classes", tags=["Teacher Classes"])


async def _resolve_teacher_profile(*, db: AsyncSession, tenant_id: uuid.UUID, teacher_user: User) -> Teacher:
    if not getattr(teacher_user, "is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

    teacher_profile = await db.scalar(
        select(Teacher).where(
            Teacher.tenant_id == tenant_id,
            Teacher.user_id == teacher_user.id,
        )
    )
    if teacher_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher profile not found.")
    return teacher_profile


def _assignment_item(
    *,
    assignment_type: str,
    subject: Subject | None,
    start_date: date_type | None,
    end_date: date_type | None,
) -> dict:
    return {
        "assignment_type": assignment_type,
        "subject_id": str(subject.id) if subject else None,
        "subject_code": subject.code if subject else None,
        "subject_name": subject.name if subject else None,
        "start_date": start_date,
        "end_date": end_date,
    }


@router.get("", summary="Teacher classes and assignment coverage")
async def get_teacher_my_classes(
    effective_date: date_type | None = None,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _resolve_teacher_profile(db=db, tenant_id=tenant.id, teacher_user=teacher_user)
    ref_date = effective_date or datetime.now(timezone.utc).date()

    canonical_history_rows = (
        await db.execute(
            select(TeacherAssignment.class_id)
            .where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.teacher_id == teacher_profile.id,
            )
            .distinct()
        )
    ).all()
    canonical_history_class_ids = {row[0] for row in canonical_history_rows}

    canonical_rows = (
        await db.execute(
            select(
                TeacherAssignment,
                Class,
                AcademicYear,
                Campus,
                Subject,
            )
            .join(Class, Class.id == TeacherAssignment.class_id)
            .join(AcademicYear, AcademicYear.id == TeacherAssignment.academic_year_id)
            .outerjoin(Campus, Campus.id == Class.campus_id)
            .outerjoin(SubjectOffering, SubjectOffering.id == TeacherAssignment.subject_offering_id)
            .outerjoin(Subject, Subject.id == SubjectOffering.subject_id)
            .where(
                TeacherAssignment.tenant_id == tenant.id,
                TeacherAssignment.teacher_id == teacher_profile.id,
                TeacherAssignment.is_active.is_(True),
                TeacherAssignment.start_date <= ref_date,
                (TeacherAssignment.end_date.is_(None) | (TeacherAssignment.end_date >= ref_date)),
                Class.tenant_id == tenant.id,
                Class.is_active.is_(True),
                AcademicYear.tenant_id == tenant.id,
                AcademicYear.is_active.is_(True),
                TeacherAssignment.academic_year_id == Class.academic_year_id,
            )
        )
    ).all()

    legacy_homeroom_rows = (
        await db.execute(
            select(Class, AcademicYear, Campus)
            .outerjoin(AcademicYear, AcademicYear.id == Class.academic_year_id)
            .outerjoin(Campus, Campus.id == Class.campus_id)
            .where(
                Class.tenant_id == tenant.id,
                Class.is_active.is_(True),
                Class.class_teacher_id == teacher_profile.id,
            )
        )
    ).all()

    legacy_timetable_rows = (
        await db.execute(
            select(Class, AcademicYear, Campus, Subject)
            .join(TimetableEntry, TimetableEntry.class_id == Class.id)
            .join(Subject, Subject.id == TimetableEntry.subject_id)
            .outerjoin(AcademicYear, AcademicYear.id == Class.academic_year_id)
            .outerjoin(Campus, Campus.id == Class.campus_id)
            .where(
                Class.tenant_id == tenant.id,
                Class.is_active.is_(True),
                TimetableEntry.tenant_id == tenant.id,
                TimetableEntry.teacher_id == teacher_profile.id,
                TimetableEntry.is_active.is_(True),
                TimetableEntry.academic_year == Class.academic_year,
            )
            .distinct(Class.id, Subject.id)
        )
    ).all()

    classes_map: dict[uuid.UUID, dict] = {}

    def _ensure_class_payload(*, klass: Class, academic_year: AcademicYear | None, campus: Campus | None, source: str) -> dict:
        payload = classes_map.get(klass.id)
        if payload is not None:
            return payload
        payload = {
            "class_id": str(klass.id),
            "code": klass.code,
            "grade_level": klass.grade,
            "section": klass.section,
            "academic_year_id": str(klass.academic_year_id) if klass.academic_year_id else None,
            "academic_year": academic_year.name if academic_year else klass.academic_year,
            "campus_id": str(klass.campus_id) if klass.campus_id else None,
            "campus": campus.name if campus else None,
            "is_active": bool(klass.is_active),
            "student_count": 0,
            "assignment_source": source,
            "assignments": [],
            "schedule": {
                "weekly_periods": 0,
                "next_period": None,
            },
        }
        classes_map[klass.id] = payload
        return payload

    for assignment, klass, academic_year, campus, subject in canonical_rows:
        payload = _ensure_class_payload(klass=klass, academic_year=academic_year, campus=campus, source="canonical")
        payload["assignments"].append(
            _assignment_item(
                assignment_type=assignment.assignment_type,
                subject=subject,
                start_date=assignment.start_date,
                end_date=assignment.end_date,
            )
        )

    for klass, academic_year, campus in legacy_homeroom_rows:
        if klass.id in canonical_history_class_ids:
            continue
        payload = _ensure_class_payload(klass=klass, academic_year=academic_year, campus=campus, source="legacy")
        payload["assignments"].append(
            _assignment_item(
                assignment_type="homeroom",
                subject=None,
                start_date=None,
                end_date=None,
            )
        )

    for klass, academic_year, campus, subject in legacy_timetable_rows:
        if klass.id in canonical_history_class_ids:
            continue
        payload = _ensure_class_payload(klass=klass, academic_year=academic_year, campus=campus, source="legacy")
        payload["assignments"].append(
            _assignment_item(
                assignment_type="subject_teacher",
                subject=subject,
                start_date=None,
                end_date=None,
            )
        )

    class_ids = list(classes_map.keys())
    if class_ids:
        student_counts = (
            await db.execute(
                select(Student.class_id, func.count(Student.id))
                .where(
                    Student.tenant_id == tenant.id,
                    Student.class_id.in_(class_ids),
                )
                .group_by(Student.class_id)
            )
        ).all()
        for class_id, count in student_counts:
            classes_map[class_id]["student_count"] = int(count)

        weekly_period_counts = (
            await db.execute(
                select(TimetableEntry.class_id, func.count(TimetableEntry.id))
                .join(Class, Class.id == TimetableEntry.class_id)
                .where(
                    TimetableEntry.tenant_id == tenant.id,
                    TimetableEntry.teacher_id == teacher_profile.id,
                    TimetableEntry.is_active.is_(True),
                    TimetableEntry.class_id.in_(class_ids),
                    TimetableEntry.academic_year == Class.academic_year,
                )
                .group_by(TimetableEntry.class_id)
            )
        ).all()
        for class_id, count in weekly_period_counts:
            classes_map[class_id]["schedule"]["weekly_periods"] = int(count)

    for payload in classes_map.values():
        deduped: dict[tuple[str, str | None], dict] = {}
        for assignment in payload["assignments"]:
            deduped[(assignment["assignment_type"], assignment["subject_id"])] = assignment
        payload["assignments"] = list(deduped.values())

    classes = sorted(
        classes_map.values(),
        key=lambda item: (
            item.get("academic_year") or "",
            item.get("grade_level") or "",
            item.get("section") or "",
            item.get("code") or "",
        ),
    )

    homeroom_classes = 0
    subject_classes = 0
    canonical_classes = 0
    legacy_classes = 0

    for item in classes:
        assignment_types = {a["assignment_type"] for a in item["assignments"]}
        if "homeroom" in assignment_types:
            homeroom_classes += 1
        if "subject_teacher" in assignment_types:
            subject_classes += 1
        if item["assignment_source"] == "canonical":
            canonical_classes += 1
        else:
            legacy_classes += 1

    return {
        "effective_date": ref_date.isoformat(),
        "teacher": {
            "id": str(teacher_profile.id),
            "display_name": teacher_user.name,
        },
        "summary": {
            "total_classes": len(classes),
            "homeroom_classes": homeroom_classes,
            "subject_classes": subject_classes,
            "canonical_classes": canonical_classes,
            "legacy_classes": legacy_classes,
        },
        "classes": classes,
    }