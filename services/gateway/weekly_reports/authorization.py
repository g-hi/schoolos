from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.authorization.teacher_scope import teacher_has_weekly_report_class_scope
from shared.db.models import Class, Student, Teacher, TimetableEntry, User


_LEADERSHIP_ROLES = {"principal", "school_admin"}
_AUTHOR_ROLES = {"teacher", "principal", "school_admin"}


@dataclass(frozen=True)
class AuthorizedStudentContext:
    student: Student
    klass: Class
    teacher_profile: Teacher | None


async def resolve_teacher_profile_for_user(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user: User,
) -> Teacher | None:
    result = await db.execute(
        select(Teacher).where(
            Teacher.tenant_id == tenant_id,
            Teacher.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def authorize_staff_for_student_action(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor: User,
    student_id: uuid.UUID,
    action: str,
) -> AuthorizedStudentContext:
    if actor.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if actor.role not in _AUTHOR_ROLES and actor.role not in _LEADERSHIP_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

    student_result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(
            Student.id == student_id,
            Student.tenant_id == tenant_id,
            Class.tenant_id == tenant_id,
        )
    )
    row = student_result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    student, klass = row
    teacher_profile = await resolve_teacher_profile_for_user(db=db, tenant_id=tenant_id, user=actor)

    if actor.role in _LEADERSHIP_ROLES:
        return AuthorizedStudentContext(student=student, klass=klass, teacher_profile=teacher_profile)

    if actor.role != "teacher" or not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

    decision = await teacher_has_weekly_report_class_scope(
        db=db,
        tenant_id=tenant_id,
        teacher_id=teacher_profile.id,
        klass=klass,
        effective_date=datetime.now(timezone.utc).date(),
    )
    if decision.authorized:
        return AuthorizedStudentContext(student=student, klass=klass, teacher_profile=teacher_profile)

    # Use not-found semantics to reduce student relationship enumeration.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")


def ensure_can_review_or_publish(actor: User) -> None:
    if actor.role not in _LEADERSHIP_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")


async def list_staff_authorized_students(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor: User,
) -> list[tuple[Student, Class]]:
    if actor.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if actor.role in _LEADERSHIP_ROLES:
        result = await db.execute(
            select(Student, Class)
            .join(Class, Class.id == Student.class_id)
            .where(Student.tenant_id == tenant_id, Class.tenant_id == tenant_id)
            .order_by(Student.name)
        )
        return list(result.all())

    if actor.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

    teacher_profile = await resolve_teacher_profile_for_user(db=db, tenant_id=tenant_id, user=actor)
    if not teacher_profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")

    result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(
            Student.tenant_id == tenant_id,
            Class.tenant_id == tenant_id,
        )
        .order_by(Student.name)
    )

    effective_date = datetime.now(timezone.utc).date()
    authorized_classes: set[uuid.UUID] = set()
    decisions_by_class: dict[uuid.UUID, bool] = {}
    rows = list(result.all())

    for _student, klass in rows:
        cached = decisions_by_class.get(klass.id)
        if cached is None:
            decision = await teacher_has_weekly_report_class_scope(
                db=db,
                tenant_id=tenant_id,
                teacher_id=teacher_profile.id,
                klass=klass,
                effective_date=effective_date,
            )
            decisions_by_class[klass.id] = decision.authorized
            cached = decision.authorized
        if cached:
            authorized_classes.add(klass.id)

    return [(student, klass) for student, klass in rows if klass.id in authorized_classes]
