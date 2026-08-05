from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Class, Student, StudentParent, User


async def calculate_event_impact(*, db: AsyncSession, tenant_id: uuid.UUID, scope: dict[str, Any]) -> dict[str, Any]:
    scope_type = str(scope.get("scope_type") or "public_information")
    grade_levels = [str(value) for value in scope.get("grade_levels", [])]
    class_ids = [uuid.UUID(str(value)) for value in scope.get("classes", [])]
    staff_roles = [str(value) for value in scope.get("staff_roles", [])]
    selected_user_ids = [uuid.UUID(str(value)) for value in scope.get("selected_users", [])]
    unresolved: list[str] = []

    role_breakdown: dict[str, int] = {}
    grade_breakdown: dict[str, int] = {}
    class_breakdown: dict[str, int] = {}
    recommended_channels = ["in_app"]
    privacy_notes: list[str] = []

    if scope_type == "whole_school":
        rows = (
            await db.execute(
                select(User.role, func.count(User.id))
                .where(User.tenant_id == tenant_id, User.is_active.is_(True))
                .group_by(User.role)
            )
        ).all()
        role_breakdown = {str(role): int(count) for role, count in rows}
    elif scope_type == "staff_roles":
        if not staff_roles:
            unresolved.append("staff_roles scope requires at least one role.")
        rows = (
            await db.execute(
                select(User.role, func.count(User.id))
                .where(User.tenant_id == tenant_id, User.is_active.is_(True), User.role.in_(staff_roles))
                .group_by(User.role)
            )
        ).all()
        role_breakdown = {str(role): int(count) for role, count in rows}
    elif scope_type == "selected_users":
        if not selected_user_ids:
            unresolved.append("selected_users scope requires at least one user id.")
        rows = (
            await db.execute(
                select(User.role, func.count(User.id))
                .where(User.tenant_id == tenant_id, User.id.in_(selected_user_ids), User.is_active.is_(True))
                .group_by(User.role)
            )
        ).all()
        role_breakdown = {str(role): int(count) for role, count in rows}
        found_count = sum(role_breakdown.values())
        if found_count != len(set(selected_user_ids)):
            unresolved.append("Some selected_users do not belong to tenant or are inactive.")
    elif scope_type in {"grade_levels", "classes", "campus"}:
        class_stmt = select(Class.id, Class.grade, Class.section).where(Class.tenant_id == tenant_id, Class.is_active.is_(True))
        if scope_type == "grade_levels":
            if not grade_levels:
                unresolved.append("grade_levels scope requires one or more grades.")
            class_stmt = class_stmt.where(Class.grade.in_(grade_levels))
        if scope_type == "classes":
            if not class_ids:
                unresolved.append("classes scope requires one or more class ids.")
            class_stmt = class_stmt.where(Class.id.in_(class_ids))
        if scope_type == "campus":
            campus_id = scope.get("campus")
            if campus_id is None:
                unresolved.append("campus scope requires a campus id.")
            else:
                class_stmt = class_stmt.where(Class.campus_id == uuid.UUID(str(campus_id)))

        class_rows = (await db.execute(class_stmt)).all()
        class_ids_scoped = [row[0] for row in class_rows]
        for class_id, grade, section in class_rows:
            grade_breakdown[str(grade)] = grade_breakdown.get(str(grade), 0) + 1
            class_breakdown[str(class_id)] = 1

        if class_ids_scoped:
            student_rows = (
                await db.execute(
                    select(User.role, func.count(User.id))
                    .select_from(Student)
                    .join(StudentParent, StudentParent.student_id == Student.id)
                    .join(User, User.id == StudentParent.parent_id)
                    .where(Student.tenant_id == tenant_id, Student.class_id.in_(class_ids_scoped), User.is_active.is_(True))
                    .group_by(User.role)
                )
            ).all()
            role_breakdown = {str(role): int(count) for role, count in student_rows}
        else:
            unresolved.append("No active classes matched this scope.")
        recommended_channels = ["in_app", "email"]
    elif scope_type in {"departments", "public_information"}:
        role_breakdown = {}
        recommended_channels = ["in_app"]
        if scope_type == "departments" and not scope.get("departments"):
            unresolved.append("departments scope requires at least one department label.")
    else:
        unresolved.append(f"Unsupported scope_type '{scope_type}'.")

    affected_count = sum(role_breakdown.values())
    if affected_count == 0:
        unresolved.append("No recipients matched the selected scope.")

    # Privacy guard: confidential staffing updates should not target parents/students directly.
    confidential = bool(scope.get("contains_confidential_staffing", False))
    if confidential and any(role in role_breakdown for role in ("parent", "student")):
        privacy_notes.append("Confidential staffing information cannot target parents or students.")

    audience_categories = sorted([role for role, count in role_breakdown.items() if count > 0])

    return {
        "scope_type": scope_type,
        "audience_categories": audience_categories,
        "affected_count": affected_count,
        "role_breakdown": role_breakdown,
        "grade_breakdown": grade_breakdown,
        "class_breakdown": class_breakdown,
        "department_breakdown": {str(value): 0 for value in scope.get("departments", [])},
        "tenant_safe_references": {
            "class_ids": [str(value) for value in class_ids],
            "selected_user_ids": [str(value) for value in selected_user_ids],
        },
        "unresolved_targeting_issues": unresolved,
        "privacy_notes": privacy_notes,
        "recommended_channels": recommended_channels,
    }
