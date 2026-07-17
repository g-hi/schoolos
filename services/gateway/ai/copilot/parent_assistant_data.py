from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Class, Period, PickupRequest, Student, StudentParent, Subject, Teacher, TimetableEntry, User
from shared.db.parent_models import Family, FamilyTimelineEvent, ParentPreferences


def _module_unavailable(reason: str) -> dict[str, object]:
    return {"available": False, "reason": reason}


async def load_parent_bootstrap(
    db: AsyncSession,
    *,
    tenant_id: str,
    parent_user_id: str,
) -> dict[str, object]:
    tenant_uuid = UUID(str(tenant_id))
    parent_uuid = UUID(str(parent_user_id))

    parent_result = await db.execute(
        select(User).where(
            User.id == parent_uuid,
            User.tenant_id == tenant_uuid,
            User.role == "parent",
            User.is_active.is_(True),
        )
    )
    parent = parent_result.scalar_one_or_none()

    prefs_result = await db.execute(
        select(ParentPreferences).where(
            ParentPreferences.user_id == parent_uuid,
            ParentPreferences.tenant_id == tenant_uuid,
        )
    )
    prefs = prefs_result.scalar_one_or_none()

    family_result = await db.execute(
        select(Family)
        .join(StudentParent, StudentParent.family_id == Family.id)
        .where(
            StudentParent.parent_id == parent_uuid,
            Family.tenant_id == tenant_uuid,
            Family.is_active.is_(True),
        )
        .limit(1)
    )
    family = family_result.scalar_one_or_none()

    students_result = await db.execute(
        select(StudentParent, Student, Class)
        .join(Student, Student.id == StudentParent.student_id)
        .join(Class, Class.id == Student.class_id)
        .where(
            StudentParent.parent_id == parent_uuid,
            Student.tenant_id == tenant_uuid,
        )
        .order_by(Student.name)
    )
    authorized_students: list[dict[str, object]] = []
    for student_parent, student, klass in students_result.all():
        homeroom_teacher_name = None
        if klass.class_teacher_id:
            teacher_result = await db.execute(
                select(Teacher, User)
                .join(User, User.id == Teacher.user_id)
                .where(Teacher.id == klass.class_teacher_id)
            )
            teacher_row = teacher_result.first()
            if teacher_row:
                homeroom_teacher_name = teacher_row[1].name

        authorized_students.append(
            {
                "student_id": str(student.id),
                "display_name": student.name,
                "student_code": student.student_code,
                "grade": klass.grade,
                "section": klass.section,
                "class_name": f"{klass.grade}-{klass.section}",
                "class_id": str(klass.id),
                "academic_year": klass.academic_year,
                "homeroom_teacher": homeroom_teacher_name,
                "can_pickup": bool(student_parent.can_pickup),
                "can_view_academics": bool(student_parent.can_view_academics),
                "can_view_behaviour": bool(student_parent.can_view_behaviour),
                "module_availability": {
                    "attendance": _module_unavailable("Attendance information is not available yet."),
                    "homework": _module_unavailable("Homework information is not available yet."),
                    "academics": _module_unavailable("Academic information is not available yet."),
                    "behaviour": _module_unavailable("Behaviour information is not available yet."),
                },
            }
        )

    return {
        "parent_profile": {
            "user_id": str(parent.id) if parent else parent_user_id,
            "display_name": parent.name if parent else "Parent",
            "email": parent.email if parent else None,
            "preferred_timezone": prefs.timezone if prefs else None,
        },
        "family_context": {
            "family_id": str(family.id) if family else None,
            "family_name": family.name if family else None,
            "is_active": bool(family.is_active) if family else False,
        },
        "authorized_students": authorized_students,
    }


def resolve_school_timezone(
    *,
    tenant_settings: dict[str, object] | None,
) -> tuple[str, datetime]:
    settings = tenant_settings or {}
    candidate = settings.get("timezone") or settings.get("school_timezone")
    if isinstance(candidate, str) and candidate.strip():
        try:
            zone = ZoneInfo(candidate.strip())
            return candidate.strip(), datetime.now(zone)
        except ZoneInfoNotFoundError:
            pass
    return "UTC", datetime.now(UTC)


async def load_timeline_events(
    db: AsyncSession,
    *,
    tenant_id: str,
    family_id: str,
    student_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    tenant_uuid = UUID(str(tenant_id))
    family_uuid = UUID(str(family_id))
    query = select(FamilyTimelineEvent).where(
        FamilyTimelineEvent.tenant_id == tenant_uuid,
        FamilyTimelineEvent.family_id == family_uuid,
    )
    if student_id:
        query = query.where(FamilyTimelineEvent.student_id == UUID(str(student_id)))
    query = query.order_by(FamilyTimelineEvent.occurred_at.desc(), FamilyTimelineEvent.id.desc()).limit(limit)
    result = await db.execute(query)
    return [
        {
            "event_id": str(event.id),
            "title": event.title,
            "description": event.description,
            "event_type": event.event_type,
            "event_category": event.event_category,
            "occurred_at": event.occurred_at.isoformat(),
            "student_id": str(event.student_id) if event.student_id else None,
            "priority": event.priority,
            "action_url": event.action_url,
        }
        for event in result.scalars().all()
    ]


async def load_pickup_status(
    db: AsyncSession,
    *,
    tenant_id: str,
    parent_user_id: str,
    student_id: str | None,
) -> list[dict[str, object]]:
    tenant_uuid = UUID(str(tenant_id))
    parent_uuid = UUID(str(parent_user_id))
    query = select(PickupRequest).where(
        PickupRequest.tenant_id == tenant_uuid,
        PickupRequest.parent_id == parent_uuid,
    )
    if student_id:
        query = query.where(PickupRequest.student_id == UUID(str(student_id)))
    query = query.order_by(PickupRequest.requested_at.desc()).limit(5)
    result = await db.execute(query)
    return [
        {
            "pickup_id": str(pickup.id),
            "student_id": str(pickup.student_id),
            "status": pickup.status,
            "requested_at": pickup.requested_at.isoformat() if pickup.requested_at else None,
            "released_at": pickup.released_at.isoformat() if pickup.released_at else None,
        }
        for pickup in result.scalars().all()
    ]


async def load_today_schedule(
    db: AsyncSession,
    *,
    tenant_id: str,
    student_id: str,
    class_id: str,
    academic_year: str,
    current_day_of_week: int,
) -> list[dict[str, object]]:
    tenant_uuid = UUID(str(tenant_id))
    class_uuid = UUID(str(class_id))
    result = await db.execute(
        select(TimetableEntry, Period, Subject)
        .join(Period, Period.id == TimetableEntry.period_id)
        .join(Subject, Subject.id == TimetableEntry.subject_id)
        .where(
            TimetableEntry.tenant_id == tenant_uuid,
            TimetableEntry.class_id == class_uuid,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.day_of_week == current_day_of_week,
            TimetableEntry.is_active.is_(True),
        )
        .order_by(Period.sort_order)
    )
    return [
        {
            "student_id": student_id,
            "period_name": period.name,
            "start_time": period.start_time,
            "end_time": period.end_time,
            "subject_name": subject.name,
        }
        for _, period, subject in result.all()
    ]