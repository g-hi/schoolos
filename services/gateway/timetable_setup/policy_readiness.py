from __future__ import annotations

import json
import math
import uuid
from collections import Counter, defaultdict
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.policy_diagnostics import build_policy_diagnostics_payload
from services.gateway.timetable_setup.readiness import compute_timetable_input_readiness
from shared.db.models import (
    AcademicYear,
    BellSchedule,
    BellSchedulePeriod,
    Campus,
    Class,
    GradeLevel,
    SchoolWeekConfig,
    Subject,
    Teacher,
    TeachingRoom,
    Term,
    TimetablePolicyConstraint,
    TimetablePolicyException,
    TimetablePolicySet,
    WeeklyTeachingRequirement,
)


LEADERSHIP_ROLES = ["principal", "school_admin"]
READINESS_STATUSES = {"not_evaluated", "not_configured", "blocked", "needs_review", "conditionally_ready", "ready"}
ACTIVE_POLICY_STATUSES = {"active"}
VISIBLE_POLICY_STATUSES = {"draft", "pending_review", "approved", "active", "suspended", "retired"}
ACTIVE_CONSTRAINT_STATUSES = {"active", "approved"}
VISIBLE_CONSTRAINT_STATUSES = {"draft", "pending_review", "approved", "active", "suspended", "retired"}
VISIBLE_EXCEPTION_STATES = {"draft", "pending_review", "approved", "rejected", "revoked"}

CONSTRAINT_SCOPE_SPECIFICITY = {
    "whole_school": 0,
    "policy_set": 1,
    "campus": 2,
    "grade": 2,
    "department": 2,
    "period": 2,
    "class": 3,
    "subject": 3,
    "teacher": 3,
    "room": 3,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_uuid(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _serialize_datetime(value: datetime | None) -> datetime | None:
    return value


def _json_text(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)


def _relax_enforcement(level: str) -> str:
    mapping = {"hard": "soft", "soft": "preference", "preference": "advisory", "advisory": "advisory"}
    return mapping.get(level, level)


def _check_set(items: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get(field_name) or "unknown") for item in items).items()))


def _context_label(context: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("academic_year_id", "term_id", "campus_id", "grade_id", "class_id", "subject_id", "teacher_id", "room_id"):
        if context.get(key):
            pieces.append(f"{key}={context[key]}")
    if context.get("effective_at") is not None:
        pieces.append(f"effective_at={context['effective_at']}")
    return "; ".join(pieces) if pieces else "tenant-scope"


def _policy_row(item: TimetablePolicySet) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "name": item.name,
        "description": item.description,
        "lifecycle_status": item.lifecycle_status,
        "version_number": item.version_number,
        "is_active": item.is_active,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "source_type": item.source_type,
        "created_by_user_id": _serialize_uuid(item.created_by_user_id),
        "approved_by_user_id": _serialize_uuid(item.approved_by_user_id),
        "approved_at": _serialize_datetime(item.approved_at),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _constraint_row(item: TimetablePolicyConstraint, policy_set: TimetablePolicySet) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "policy_set_id": str(item.policy_set_id),
        "policy_set_name": policy_set.name,
        "academic_year_id": str(policy_set.academic_year_id),
        "term_id": str(policy_set.term_id),
        "campus_id": _serialize_uuid(policy_set.campus_id),
        "constraint_type": item.constraint_type,
        "category": item.category,
        "enforcement_level": item.enforcement_level,
        "lifecycle_status": item.lifecycle_status,
        "scope_type": item.scope_type,
        "scope_reference_id": _serialize_uuid(item.scope_reference_id),
        "scope_reference_code": item.scope_reference_code,
        "parameters": item.parameters_json,
        "weight": item.weight,
        "priority": item.priority,
        "is_active": item.is_active,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "explanation": item.explanation,
        "source_type": item.source_type,
        "confidence_score": item.confidence_score,
        "requires_approval": item.requires_approval,
        "version_number": item.version_number,
        "created_at": item.created_at,
    }


def _exception_row(item: TimetablePolicyException) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "policy_set_id": _serialize_uuid(item.policy_set_id),
        "constraint_id": _serialize_uuid(item.constraint_id),
        "scope_type": item.scope_type,
        "scope_reference_id": _serialize_uuid(item.scope_reference_id),
        "scope_reference_code": item.scope_reference_code,
        "reason": item.reason,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "approval_state": item.approval_state,
        "requested_by_user_id": _serialize_uuid(item.requested_by_user_id),
        "approved_by_user_id": _serialize_uuid(item.approved_by_user_id),
        "approved_at": _serialize_datetime(item.approved_at),
        "expires_at": _serialize_datetime(item.expires_at),
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _requirement_row(item: WeeklyTeachingRequirement) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "academic_year_id": _serialize_uuid(item.academic_year_id),
        "term_id": _serialize_uuid(item.term_id),
        "class_id": _serialize_uuid(item.class_id),
        "subject_id": _serialize_uuid(item.subject_id),
        "teacher_id": _serialize_uuid(item.teacher_id),
        "sessions_per_week": item.sessions_per_week,
        "periods_per_session": item.periods_per_session,
        "min_daily_sessions": item.min_daily_sessions,
        "max_daily_sessions": item.max_daily_sessions,
        "double_period_mode": item.double_period_mode,
        "specialist_room_type": item.specialist_room_type,
        "preferred_period_numbers": list(item.preferred_period_numbers or []),
        "forbidden_period_numbers": list(item.forbidden_period_numbers or []),
        "has_fixed_sessions": item.has_fixed_sessions,
        "fixed_session_rules": list(item.fixed_session_rules or []),
        "priority": item.priority,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _room_row(item: TeachingRoom) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "room_code": item.room_code,
        "room_name": item.room_name,
        "room_type": item.room_type,
        "capacity": item.capacity,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _school_week_row(item: SchoolWeekConfig) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "academic_year_id": _serialize_uuid(item.academic_year_id),
        "term_id": _serialize_uuid(item.term_id),
        "name": item.name,
        "operational_weekdays": list(item.operational_weekdays or []),
        "is_default": item.is_default,
        "source_type": item.source_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _bell_period_row(item: BellSchedulePeriod) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "bell_schedule_id": str(item.bell_schedule_id),
        "period_number": item.period_number,
        "label": item.label,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "is_teaching_period": item.is_teaching_period,
        "is_active": item.is_active,
    }


def _class_row(item: Class) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "academic_year_id": _serialize_uuid(item.academic_year_id),
        "grade_level_id": _serialize_uuid(item.grade_level_id),
        "grade": item.grade,
        "section": item.section,
        "code": item.code,
        "is_active": item.is_active,
    }


def _teacher_row(item: Teacher) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "user_id": str(item.user_id),
        "max_weekly_hours": item.max_weekly_hours,
        "max_substitutions_per_week": item.max_substitutions_per_week,
        "created_at": item.created_at,
    }


def _subject_row(item: Subject) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "code": item.code,
        "name": item.name,
        "is_active": item.is_active,
    }


def _grade_row(item: GradeLevel) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "code": item.code,
        "name": item.name,
        "sequence": item.sequence,
        "is_active": item.is_active,
    }


def _term_row(item: Term) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "academic_year_id": str(item.academic_year_id),
        "code": item.code,
        "name": item.name,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "is_active": item.is_active,
    }


def _academic_year_row(item: AcademicYear) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "code": item.code,
        "name": item.name,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "is_active": item.is_active,
    }


def _campus_row(item: Campus) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "code": item.code,
        "name": item.name,
        "is_active": item.is_active,
    }


def _effective_at_is_valid(item: dict[str, Any], effective_at: datetime | None) -> bool:
    if effective_at is None:
        return True
    start_date = item.get("effective_start_date")
    end_date = item.get("effective_end_date")
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    date_value = effective_at.date()
    if start_date is not None and date_value < start_date:
        return False
    if end_date is not None and date_value > end_date:
        return False
    return True


def _policy_scope_matches(item: dict[str, Any], context: dict[str, Any]) -> bool:
    if context.get("academic_year_id") and item["academic_year_id"] != context["academic_year_id"]:
        return False
    if context.get("term_id") and item["term_id"] != context["term_id"]:
        return False
    if context.get("campus_id") is not None:
        return item.get("campus_id") in {None, context.get("campus_id")}
    return item.get("campus_id") is None


def _policy_specificity(item: dict[str, Any], context: dict[str, Any]) -> int:
    if context.get("campus_id") is not None and item.get("campus_id") == context.get("campus_id"):
        return 2
    if context.get("campus_id") is None and item.get("campus_id") is None:
        return 2
    if item.get("campus_id") is None:
        return 1
    return 0


def _same_tenant(item: dict[str, Any], context: dict[str, Any]) -> bool:
    tenant_id = context.get("tenant_id")
    if tenant_id is None:
        return True
    item_tenant_id = item.get("tenant_id")
    return item_tenant_id is None or item_tenant_id == tenant_id


def _constraint_specificity(item: dict[str, Any], context: dict[str, Any]) -> int:
    scope_type = item["scope_type"]
    if scope_type == "teacher" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("teacher_id"):
        return 3
    if scope_type == "class" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("class_id"):
        return 3
    if scope_type == "subject" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("subject_id"):
        return 3
    if scope_type == "room" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("room_id"):
        return 3
    if scope_type == "grade" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("grade_id"):
        return 2
    if scope_type == "campus" and item.get("scope_reference_id") and item.get("scope_reference_id") == context.get("campus_id"):
        return 2
    if scope_type == "whole_school":
        return 1
    if scope_type == "policy_set" and item.get("scope_reference_id") == context.get("selected_policy_set_id"):
        return 2
    return 0


def _is_reference_valid(reference: dict[str, Any] | None, *, active_required: bool = True) -> bool:
    if reference is None:
        return False
    if active_required and not reference.get("is_active", True):
        return False
    return True


def _constraint_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["constraint_type"],
        item["scope_type"],
        item.get("scope_reference_id"),
        item.get("scope_reference_code"),
        item["enforcement_level"],
        _json_text(item.get("parameters", {})),
    )


def _exception_target_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("policy_set_id"),
        item.get("constraint_id"),
        item["scope_type"],
        item.get("scope_reference_id"),
        item.get("scope_reference_code"),
    )


def _exception_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _exception_target_key(item),
        item.get("reason"),
        item.get("start_date"),
        item.get("end_date"),
        item.get("expires_at"),
        item.get("approval_state"),
    )


def _context_from_filters(
    *,
    academic_year_id: uuid.UUID | None,
    term_id: uuid.UUID | None,
    campus_id: uuid.UUID | None,
    grade_id: uuid.UUID | None,
    class_id: uuid.UUID | None,
    subject_id: uuid.UUID | None,
    teacher_id: uuid.UUID | None,
    room_id: uuid.UUID | None,
    effective_at: datetime | None,
) -> dict[str, Any]:
    return {
        "academic_year_id": str(academic_year_id) if academic_year_id else None,
        "term_id": str(term_id) if term_id else None,
        "campus_id": str(campus_id) if campus_id else None,
        "grade_id": str(grade_id) if grade_id else None,
        "class_id": str(class_id) if class_id else None,
        "subject_id": str(subject_id) if subject_id else None,
        "teacher_id": str(teacher_id) if teacher_id else None,
        "room_id": str(room_id) if room_id else None,
        "effective_at": effective_at,
    }


async def _validate_context_references(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID | None,
    term_id: uuid.UUID | None,
    campus_id: uuid.UUID | None,
    grade_id: uuid.UUID | None,
    class_id: uuid.UUID | None,
    subject_id: uuid.UUID | None,
    teacher_id: uuid.UUID | None,
    room_id: uuid.UUID | None,
    department_id: uuid.UUID | None,
) -> dict[str, dict[str, Any] | None]:
    if department_id is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported filter: department_id.")

    refs: dict[str, dict[str, Any] | None] = {"academic_year": None, "term": None, "campus": None, "grade": None, "class": None, "subject": None, "teacher": None, "room": None}

    if academic_year_id is not None:
        academic_year = await db.scalar(select(AcademicYear).where(AcademicYear.id == academic_year_id, AcademicYear.tenant_id == tenant_id))
        if academic_year is None or not academic_year.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive academic year.")
        refs["academic_year"] = _academic_year_row(academic_year)

    if term_id is not None:
        term = await db.scalar(select(Term).where(Term.id == term_id, Term.tenant_id == tenant_id))
        if term is None or not term.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive term.")
        if academic_year_id is not None and term.academic_year_id != academic_year_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid academic-year/term relationship.")
        refs["term"] = _term_row(term)

    if campus_id is not None:
        campus = await db.scalar(select(Campus).where(Campus.id == campus_id, Campus.tenant_id == tenant_id))
        if campus is None or not campus.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive campus.")
        refs["campus"] = _campus_row(campus)

    if grade_id is not None:
        grade = await db.scalar(select(GradeLevel).where(GradeLevel.id == grade_id, GradeLevel.tenant_id == tenant_id))
        if grade is None or not grade.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive grade level.")
        refs["grade"] = _grade_row(grade)

    if class_id is not None:
        klass = await db.scalar(select(Class).where(Class.id == class_id, Class.tenant_id == tenant_id))
        if klass is None or not klass.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive class.")
        if campus_id is not None and klass.campus_id is not None and klass.campus_id != campus_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class is outside the requested campus scope.")
        if academic_year_id is not None and klass.academic_year_id is not None and klass.academic_year_id != academic_year_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class is outside the requested academic year scope.")
        if grade_id is not None and klass.grade_level_id is not None and klass.grade_level_id != grade_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class is outside the requested grade scope.")
        refs["class"] = _class_row(klass)

    if subject_id is not None:
        subject = await db.scalar(select(Subject).where(Subject.id == subject_id, Subject.tenant_id == tenant_id))
        if subject is None or not subject.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive subject.")
        refs["subject"] = _subject_row(subject)

    if teacher_id is not None:
        teacher = await db.scalar(select(Teacher).where(Teacher.id == teacher_id, Teacher.tenant_id == tenant_id))
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown teacher.")
        refs["teacher"] = _teacher_row(teacher)

    if room_id is not None:
        room = await db.scalar(select(TeachingRoom).where(TeachingRoom.id == room_id, TeachingRoom.tenant_id == tenant_id))
        if room is None or not room.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown or inactive room.")
        if campus_id is not None and room.campus_id is not None and room.campus_id != campus_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Room is outside the requested campus scope.")
        refs["room"] = _room_row(room)

    return refs


async def _load_rows(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    policy_sets = (await db.execute(select(TimetablePolicySet).where(TimetablePolicySet.tenant_id == tenant_id).order_by(TimetablePolicySet.created_at.asc()))).scalars().all()
    constraint_rows = (await db.execute(select(TimetablePolicyConstraint, TimetablePolicySet).join(TimetablePolicySet, TimetablePolicySet.id == TimetablePolicyConstraint.policy_set_id).where(TimetablePolicyConstraint.tenant_id == tenant_id).order_by(TimetablePolicyConstraint.created_at.asc()))).all()
    exceptions = (await db.execute(select(TimetablePolicyException).where(TimetablePolicyException.tenant_id == tenant_id).order_by(TimetablePolicyException.created_at.asc()))).scalars().all()
    requirements = (await db.execute(select(WeeklyTeachingRequirement).where(WeeklyTeachingRequirement.tenant_id == tenant_id).order_by(WeeklyTeachingRequirement.created_at.asc()))).scalars().all()
    rooms = (await db.execute(select(TeachingRoom).where(TeachingRoom.tenant_id == tenant_id).order_by(TeachingRoom.created_at.asc()))).scalars().all()
    school_weeks = (await db.execute(select(SchoolWeekConfig).where(SchoolWeekConfig.tenant_id == tenant_id).order_by(SchoolWeekConfig.created_at.asc()))).scalars().all()
    bell_periods = (await db.execute(select(BellSchedulePeriod).join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id).where(BellSchedulePeriod.tenant_id == tenant_id, BellSchedule.tenant_id == tenant_id).order_by(BellSchedulePeriod.period_number.asc()))).scalars().all()
    classes = (await db.execute(select(Class).where(Class.tenant_id == tenant_id))).scalars().all()
    subjects = (await db.execute(select(Subject).where(Subject.tenant_id == tenant_id))).scalars().all()
    teachers = (await db.execute(select(Teacher).where(Teacher.tenant_id == tenant_id))).scalars().all()
    grade_levels = (await db.execute(select(GradeLevel).where(GradeLevel.tenant_id == tenant_id))).scalars().all()
    academic_years = (await db.execute(select(AcademicYear).where(AcademicYear.tenant_id == tenant_id))).scalars().all()
    terms = (await db.execute(select(Term).where(Term.tenant_id == tenant_id))).scalars().all()
    campuses = (await db.execute(select(Campus).where(Campus.tenant_id == tenant_id))).scalars().all()
    diagnostics = await build_policy_diagnostics_payload(db, tenant_id)
    readiness = await compute_timetable_input_readiness(db, tenant_id)
    return {
        "policy_sets": [_policy_row(item) for item in policy_sets],
        "constraints": [_constraint_row(item, policy_set) for item, policy_set in constraint_rows],
        "exceptions": [_exception_row(item) for item in exceptions],
        "requirements": [_requirement_row(item) for item in requirements],
        "rooms": [_room_row(item) for item in rooms],
        "school_weeks": [_school_week_row(item) for item in school_weeks],
        "bell_periods": [_bell_period_row(item) for item in bell_periods],
        "classes": [_class_row(item) for item in classes],
        "subjects": [_subject_row(item) for item in subjects],
        "teachers": [_teacher_row(item) for item in teachers],
        "grade_levels": [_grade_row(item) for item in grade_levels],
        "academic_years": [_academic_year_row(item) for item in academic_years],
        "terms": [_term_row(item) for item in terms],
        "campuses": [_campus_row(item) for item in campuses],
        "diagnostics": diagnostics,
        "canonical_readiness": readiness,
    }


def _policy_match_reason(item: dict[str, Any], context: dict[str, Any]) -> str:
    if not _policy_scope_matches(item, context):
        return "out_of_scope"
    if not _effective_at_is_valid(item, context.get("effective_at")):
        return "outside_effective_window"
    if item["lifecycle_status"] == "active" and item["is_active"]:
        return "selected_operational_policy"
    if item["lifecycle_status"] == "approved" and not item["is_active"]:
        return "approved_but_inactive"
    if item["lifecycle_status"] == "pending_review":
        return "pending_review"
    if item["lifecycle_status"] == "draft":
        return "draft"
    if item["lifecycle_status"] in {"suspended", "retired"}:
        return "non_operational_lifecycle"
    return "visible"


def _select_effective_policy_set(policy_sets: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    visible_candidates = []
    for item in policy_sets:
        if not _same_tenant(item, context):
            continue
        if not _policy_scope_matches(item, context):
            continue
        item_copy = dict(item)
        item_copy["selection_reason"] = _policy_match_reason(item, context)
        item_copy["specificity"] = _policy_specificity(item, context)
        item_copy["operational"] = item["lifecycle_status"] == "active" and item["is_active"] and _effective_at_is_valid(item, context.get("effective_at"))
        visible_candidates.append(item_copy)

    operational_candidates = [item for item in visible_candidates if item["operational"]]
    operational_candidates.sort(key=lambda row: (-row["specificity"], -int(row["version_number"]), row["created_at"], row["id"]))
    selected = operational_candidates[0] if operational_candidates else None
    unresolved_ambiguity = len(operational_candidates) > 1 and operational_candidates[0]["specificity"] == operational_candidates[1]["specificity"]

    rejected_candidates = []
    for item in visible_candidates:
        rejected_candidates.append({
            "id": item["id"],
            "name": item["name"],
            "lifecycle_status": item["lifecycle_status"],
            "is_active": item["is_active"],
            "campus_id": item.get("campus_id"),
            "version_number": item["version_number"],
            "selected": bool(selected and item["id"] == selected["id"]),
            "selection_reason": item["selection_reason"],
            "specificity": item["specificity"],
            "effective_start_date": item.get("effective_start_date"),
            "effective_end_date": item.get("effective_end_date"),
        })

    if selected is None:
        visible_active = [item for item in visible_candidates if item["lifecycle_status"] in {"approved", "pending_review", "draft"}]
        selected_reason = "not_configured" if not visible_active else "needs_review"
    else:
        selected_reason = "selected_operational_policy"

    return {
        "selected": selected,
        "selected_reason": selected_reason,
        "rejected_candidates": rejected_candidates,
        "operational_candidates": operational_candidates,
        "unresolved_ambiguity": unresolved_ambiguity,
        "candidate_count": len(visible_candidates),
        "operational_candidate_count": len(operational_candidates),
    }


def _constraint_matches_context(item: dict[str, Any], context: dict[str, Any]) -> bool:
    scope_type = item["scope_type"]
    if scope_type == "whole_school":
        return True
    if scope_type == "policy_set":
        return item.get("scope_reference_id") == context.get("selected_policy_set_id")
    if scope_type == "campus":
        return context.get("campus_id") is not None and item.get("scope_reference_id") == context.get("campus_id")
    if scope_type == "grade":
        return context.get("grade_id") is not None and item.get("scope_reference_id") == context.get("grade_id")
    if scope_type == "class":
        return context.get("class_id") is not None and item.get("scope_reference_id") == context.get("class_id")
    if scope_type == "subject":
        return context.get("subject_id") is not None and item.get("scope_reference_id") == context.get("subject_id")
    if scope_type == "teacher":
        return context.get("teacher_id") is not None and item.get("scope_reference_id") == context.get("teacher_id")
    if scope_type == "room":
        return context.get("room_id") is not None and item.get("scope_reference_id") == context.get("room_id")
    if scope_type == "period":
        return True
    if scope_type == "department":
        return bool(item.get("scope_reference_code"))
    return False


def _effective_exceptions_by_target(exceptions: list[dict[str, Any]], context: dict[str, Any]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    result: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[Any, ...]] = set()
    for item in exceptions:
        if not _same_tenant(item, context):
            continue
        if item["approval_state"] != "approved" or not item["is_active"]:
            continue
        if item.get("start_date") is not None and context.get("effective_at") is not None and context["effective_at"].date() < item["start_date"]:
            continue
        if item.get("end_date") is not None and context.get("effective_at") is not None and context["effective_at"].date() > item["end_date"]:
            continue
        if item.get("expires_at") is not None and context.get("effective_at") is not None and context["effective_at"] > item["expires_at"]:
            continue
        target_key = _exception_target_key(item)
        signature = _exception_signature(item)
        if signature in seen:
            continue
        seen.add(signature)
        result[target_key].append(item)
    return result


def _evaluate_exceptions(
    *,
    exceptions: list[dict[str, Any]],
    selected_policy: dict[str, Any] | None,
    effective_constraints: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    valid_by_target = _effective_exceptions_by_target(exceptions, context)
    seen_valid_signatures: set[tuple[Any, ...]] = set()
    valid_count = 0
    pending_count = 0
    expired_count = 0
    invalid_count = 0
    conflicting_count = 0
    ignored_count = 0
    issue_details: list[dict[str, Any]] = []
    affected_constraints: set[str] = set()

    for item in exceptions:
        target_exists = False
        target_active = False
        if item.get("policy_set_id"):
            target_exists = selected_policy is not None and selected_policy["id"] == item["policy_set_id"]
            target_active = bool(selected_policy and selected_policy["id"] == item["policy_set_id"] and selected_policy["lifecycle_status"] == "active" and selected_policy["is_active"])
        if item.get("constraint_id"):
            target_exists = any(constraint["id"] == item["constraint_id"] for constraint in effective_constraints)
            target_active = any(constraint["id"] == item["constraint_id"] and constraint["selected"] for constraint in effective_constraints)

        if item["approval_state"] == "pending_review":
            pending_count += 1
            issue_details.append({"exception_id": item["id"], "status": "pending_review", "reason": item["reason"]})
            continue
        if item["approval_state"] in {"rejected", "revoked"}:
            ignored_count += 1
            issue_details.append({"exception_id": item["id"], "status": item["approval_state"], "reason": item["reason"]})
            continue
        if item.get("start_date") is not None and context.get("effective_at") is not None and context["effective_at"].date() < item["start_date"]:
            invalid_count += 1
            issue_details.append({"exception_id": item["id"], "status": "not_started", "reason": item["reason"]})
            continue
        if item.get("expires_at") is not None and context.get("effective_at") is not None and context["effective_at"] > item["expires_at"]:
            expired_count += 1
            issue_details.append({"exception_id": item["id"], "status": "expired", "reason": item["reason"]})
            continue
        if not target_exists:
            invalid_count += 1
            issue_details.append({"exception_id": item["id"], "status": "missing_target", "reason": item["reason"]})
            continue
        if not target_active:
            invalid_count += 1
            issue_details.append({"exception_id": item["id"], "status": "inactive_target", "reason": item["reason"]})
            continue

        signature = _exception_signature(item)
        if signature in seen_valid_signatures:
            ignored_count += 1
            continue
        seen_valid_signatures.add(signature)

        matching = valid_by_target.get(_exception_target_key(item), [])
        if len(matching) > 1:
            conflicting_count += len(matching)
            issue_details.append({"exception_id": item["id"], "status": "conflicting", "reason": item["reason"]})
            continue

        valid_count += 1
        if item.get("constraint_id"):
            affected_constraints.add(str(item["constraint_id"]))
        if item.get("policy_set_id"):
            for constraint in effective_constraints:
                if constraint["policy_set_id"] == str(item["policy_set_id"]) and constraint["selected"]:
                    affected_constraints.add(constraint["id"])

    return {
        "valid_exception_count": valid_count,
        "pending_exception_count": pending_count,
        "expired_exception_count": expired_count,
        "invalid_exception_count": invalid_count,
        "conflicting_exception_count": conflicting_count,
        "ignored_exception_count": ignored_count,
        "issue_details": issue_details,
        "affected_constraints": sorted(affected_constraints),
        "approved_valid_targets": list(valid_by_target.keys()),
        "ready": invalid_count == 0 and expired_count == 0 and conflicting_count == 0,
    }


def _build_effective_constraints(policy_set: dict[str, Any] | None, constraints: list[dict[str, Any]], exceptions: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    if policy_set is None:
        return {"items": [], "selected_count": 0, "effective_constraint_count": 0, "blocker_count": 0, "warning_count": 0, "information_count": 0, "selected_types": [], "unresolved_ambiguity": False, "conflicts": []}

    applicable = [
        item
        for item in constraints
        if _same_tenant(item, context)
        and item["policy_set_id"] == policy_set["id"]
        and item["lifecycle_status"] == "active"
        and item["is_active"]
        and _constraint_matches_context(item, context)
        and _effective_at_is_valid(item, context.get("effective_at"))
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in applicable:
        grouped[item["constraint_type"]].append(item)

    items: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    blocker_count = 0
    warning_count = 0
    information_count = 0

    for constraint_type, group in sorted(grouped.items(), key=lambda row: row[0]):
        ranked = sorted(
            group,
            key=lambda row: (
                -_constraint_specificity(row, context),
                int(row["priority"]),
                -float(row["weight"]),
                -int(row["version_number"]),
                row["created_at"],
                row["id"],
            ),
        )
        selected_constraint = ranked[0]
        equal_rank = [item for item in ranked if int(item["priority"]) == int(selected_constraint["priority"]) and _constraint_specificity(item, context) == _constraint_specificity(selected_constraint, context)]
        selected_reason = "selected_by_precedence"
        overridden_by: str | None = None
        if len(equal_rank) > 1 and any(_json_text(item.get("parameters", {})) != _json_text(selected_constraint.get("parameters", {})) or item["enforcement_level"] != selected_constraint["enforcement_level"] for item in equal_rank[1:]):
            conflicts.append(
                {
                    "constraint_type": constraint_type,
                    "conflict_type": "equal_priority_contradiction",
                    "constraint_ids": [item["id"] for item in equal_rank],
                    "policy_set_id": policy_set["id"],
                    "severity": "blocker",
                }
            )
            blocker_count += 1
            selected_reason = "equal_priority_contradiction"

        matching_exception = None
        for item in exceptions:
            if not _same_tenant(item, context):
                continue
            if item["approval_state"] != "approved" or not item["is_active"]:
                continue
            if item.get("constraint_id") is not None and str(item.get("constraint_id")) == selected_constraint["id"]:
                if item.get("start_date") is not None and context.get("effective_at") is not None and context["effective_at"].date() < item["start_date"]:
                    continue
                if item.get("expires_at") is not None and context.get("effective_at") is not None and context["effective_at"] > item["expires_at"]:
                    continue
                matching_exception = dict(item)
                break

        final_enforcement = selected_constraint["enforcement_level"]
        if matching_exception is not None:
            final_enforcement = _relax_enforcement(final_enforcement)

        item_payload = {
            "id": selected_constraint["id"],
            "constraint_id": selected_constraint["id"],
            "policy_set_id": selected_constraint["policy_set_id"],
            "type": selected_constraint["constraint_type"],
            "category": selected_constraint["category"],
            "enforcement_level": selected_constraint["enforcement_level"],
            "scope": {"scope_type": selected_constraint["scope_type"], "scope_reference_id": selected_constraint.get("scope_reference_id"), "scope_reference_code": selected_constraint.get("scope_reference_code")},
            "parameters": selected_constraint.get("parameters", {}),
            "priority": selected_constraint["priority"],
            "weight": selected_constraint["weight"],
            "source_type": selected_constraint["source_type"],
            "effective_start_date": selected_constraint.get("effective_start_date"),
            "effective_end_date": selected_constraint.get("effective_end_date"),
            "lifecycle_status": selected_constraint["lifecycle_status"],
            "selected": True,
            "selection_reason": selected_reason,
            "overridden_constraint_id": overridden_by,
            "applicable_exception": matching_exception,
            "final_effective_enforcement": final_enforcement,
            "provenance": {"policy_set_id": selected_constraint["policy_set_id"], "constraint_id": selected_constraint["id"], "context": _context_label(context)},
        }
        if matching_exception is not None:
            item_payload["selection_reason"] = "selected_with_exception"
        items.append(item_payload)
        if final_enforcement == "hard":
            blocker_count += 0
        elif final_enforcement in {"soft", "preference"}:
            warning_count += 1
        else:
            information_count += 1

        for other in ranked[1:]:
            items.append(
                {
                    "id": other["id"],
                    "constraint_id": other["id"],
                    "policy_set_id": other["policy_set_id"],
                    "type": other["constraint_type"],
                    "category": other["category"],
                    "enforcement_level": other["enforcement_level"],
                    "scope": {"scope_type": other["scope_type"], "scope_reference_id": other.get("scope_reference_id"), "scope_reference_code": other.get("scope_reference_code")},
                    "parameters": other.get("parameters", {}),
                    "priority": other["priority"],
                    "weight": other["weight"],
                    "source_type": other["source_type"],
                    "effective_start_date": other.get("effective_start_date"),
                    "effective_end_date": other.get("effective_end_date"),
                    "lifecycle_status": other["lifecycle_status"],
                    "selected": False,
                    "selection_reason": "overridden_by_more_specific_or_higher_priority_constraint",
                    "overridden_constraint_id": selected_constraint["id"],
                    "applicable_exception": None,
                    "final_effective_enforcement": other["enforcement_level"],
                    "provenance": {"policy_set_id": other["policy_set_id"], "constraint_id": other["id"], "context": _context_label(context)},
                }
            )

    return {
        "items": items,
        "selected_count": sum(1 for item in items if item["selected"]),
        "effective_constraint_count": sum(1 for item in items if item["selected"]),
        "blocker_count": blocker_count + len(conflicts),
        "warning_count": warning_count,
        "information_count": information_count,
        "unresolved_ambiguity": bool(conflicts),
        "conflicts": conflicts,
    }


def _evaluate_coverage(
    *,
    canonical_readiness: dict[str, Any],
    effective_policy: dict[str, Any],
    effective_constraints: dict[str, Any],
    diagnostics: dict[str, Any],
    exceptions: dict[str, Any],
    context: dict[str, Any],
    requirements: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    school_weeks: list[dict[str, Any]],
    bell_periods: list[dict[str, Any]],
) -> dict[str, Any]:
    applicable_checks: list[dict[str, Any]] = []

    def add_check(*, key: str, title: str, category: str, mandatory: bool, applicable: bool, satisfied: bool, explanation: str, weight: int, evidence: dict[str, Any] | None = None) -> None:
        applicable_checks.append(
            {
                "check_key": key,
                "title": title,
                "category": category,
                "mandatory": mandatory,
                "applicable": applicable,
                "satisfied": satisfied,
                "weight": weight,
                "explanation": explanation,
                "evidence": evidence or {},
            }
        )

    teacher_assigned_requirements = [item for item in requirements if item["teacher_id"] is not None and item["review_status"] == "approved" and item["is_active"]]
    specialist_requirements = [item for item in requirements if item.get("specialist_room_type") and item["review_status"] == "approved" and item["is_active"]]
    fixed_session_requirements = [item for item in requirements if item["has_fixed_sessions"] and item["review_status"] == "approved" and item["is_active"]]
    multi_campus = len({item.get("campus_id") for item in requirements if item.get("campus_id")}) > 1 or len({item.get("campus_id") for item in rooms if item.get("campus_id")}) > 1

    add_check(
        key="canonical_input",
        title="Canonical timetable inputs are ready",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=int(canonical_readiness.get("blocker_count", 0)) == 0,
        explanation="Phase 10A readiness blockers must be clear before policy authorization can pass.",
        weight=20,
        evidence={"canonical_blockers": canonical_readiness.get("blocker_count", 0)},
    )
    add_check(
        key="policy_set_operational",
        title="An operational policy set exists",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=effective_policy.get("selected") is not None and effective_policy.get("selected").get("lifecycle_status") == "active" and effective_policy.get("selected").get("is_active"),
        explanation="The selected policy set must be approved and active.",
        weight=20,
        evidence={"policy_set_id": effective_policy.get("selected", {}).get("id") if effective_policy.get("selected") else None},
    )
    add_check(
        key="policy_scope_integrity",
        title="Planning context is tenant-owned and valid",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=effective_policy.get("selected") is not None and not effective_policy.get("unresolved_ambiguity"),
        explanation="Context references must belong to the authenticated tenant and not create ambiguity.",
        weight=10,
        evidence={"context": _context_label(context)},
    )
    add_check(
        key="diagnostic_feasibility",
        title="No impossible diagnostic remains",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=int(diagnostics.get("generation", {}).get("blocker_count", 0)) == 0,
        explanation="A hard diagnostic blocker must not remain.",
        weight=15,
        evidence={"diagnostic_blockers": diagnostics.get("generation", {}).get("blocker_count", 0)},
    )
    add_check(
        key="exception_validity",
        title="Exceptions are valid and unexpired",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=int(exceptions.get("invalid_exception_count", 0)) == 0 and int(exceptions.get("expired_exception_count", 0)) == 0 and int(exceptions.get("conflicting_exception_count", 0)) == 0,
        explanation="Exceptions must target valid tenant records and remain within their valid date range.",
        weight=10,
        evidence={"invalid": exceptions.get("invalid_exception_count", 0), "expired": exceptions.get("expired_exception_count", 0), "conflicting": exceptions.get("conflicting_exception_count", 0)},
    )
    add_check(
        key="approvals_complete",
        title="Mandatory approvals are complete",
        category="mandatory",
        mandatory=True,
        applicable=True,
        satisfied=int(effective_policy.get("pending_policy_count", 0)) == 0 and int(effective_policy.get("pending_constraint_count", 0)) == 0 and int(exceptions.get("pending_exception_count", 0)) == 0,
        explanation="Pending policy, constraint, or exception decisions keep readiness in review.",
        weight=15,
        evidence={"pending_policy": effective_policy.get("pending_policy_count", 0), "pending_constraint": effective_policy.get("pending_constraint_count", 0), "pending_exception": exceptions.get("pending_exception_count", 0)},
    )

    add_check(
        key="teacher_availability",
        title="Teacher availability is covered",
        category="policy",
        mandatory=bool(teacher_assigned_requirements),
        applicable=bool(teacher_assigned_requirements),
        satisfied=bool(teacher_assigned_requirements) and any(item["selected"] and item["type"] in {"teacher_unavailable", "teacher_max_daily_sessions", "teacher_max_consecutive_sessions", "teacher_min_break"} for item in effective_constraints.get("items", [])),
        explanation="Teacher-assigned requirements need teacher availability or workload policy coverage.",
        weight=8,
        evidence={"teacher_assigned_requirements": len(teacher_assigned_requirements)},
    )
    add_check(
        key="teacher_eligibility",
        title="Teacher eligibility is covered",
        category="policy",
        mandatory=bool(teacher_assigned_requirements),
        applicable=bool(teacher_assigned_requirements),
        satisfied=bool(teacher_assigned_requirements) and any(item["selected"] and item["type"] == "teacher_subject_eligibility" for item in effective_constraints.get("items", [])),
        explanation="Teacher-subject pairings should be explicitly covered where teachers are assigned.",
        weight=6,
        evidence={"teacher_assigned_requirements": len(teacher_assigned_requirements)},
    )
    add_check(
        key="room_compatibility",
        title="Room compatibility is covered",
        category="policy",
        mandatory=bool(specialist_requirements),
        applicable=bool(specialist_requirements),
        satisfied=bool(specialist_requirements) and any(item["selected"] and item["type"] in {"room_required_type", "room_capacity", "room_unavailable"} for item in effective_constraints.get("items", [])),
        explanation="Specialist room requirements need compatible room policy coverage.",
        weight=8,
        evidence={"specialist_requirements": len(specialist_requirements)},
    )
    add_check(
        key="room_availability",
        title="Room availability is covered",
        category="policy",
        mandatory=bool(rooms),
        applicable=bool(rooms),
        satisfied=bool(rooms) and any(item["selected"] and item["type"] in {"room_unavailable", "room_capacity"} for item in effective_constraints.get("items", [])),
        explanation="Active rooms should be governed by room availability or capacity rules when present.",
        weight=6,
        evidence={"rooms": len(rooms)},
    )
    add_check(
        key="school_week",
        title="School week is covered",
        category="canonical",
        mandatory=True,
        applicable=True,
        satisfied=any(item["review_status"] == "approved" and item["is_active"] for item in school_weeks),
        explanation="An approved active school week configuration is required.",
        weight=10,
        evidence={"school_weeks": len(school_weeks)},
    )
    add_check(
        key="bell_periods",
        title="Bell periods are covered",
        category="canonical",
        mandatory=True,
        applicable=True,
        satisfied=any(item["is_teaching_period"] and item["is_active"] for item in bell_periods),
        explanation="At least one active teaching bell period is required.",
        weight=10,
        evidence={"teaching_periods": sum(1 for item in bell_periods if item["is_teaching_period"] and item["is_active"])},
    )
    add_check(
        key="fixed_sessions",
        title="Fixed sessions are covered",
        category="policy",
        mandatory=bool(fixed_session_requirements),
        applicable=bool(fixed_session_requirements),
        satisfied=bool(fixed_session_requirements) and any(item["selected"] and item["type"] == "fixed_session" for item in effective_constraints.get("items", [])),
        explanation="Fixed session requirements need an explicit fixed-session policy.",
        weight=6,
        evidence={"fixed_session_requirements": len(fixed_session_requirements)},
    )
    add_check(
        key="curriculum_requirements",
        title="Curriculum requirements are covered",
        category="policy",
        mandatory=True,
        applicable=True,
        satisfied=any(item["selected"] and item["type"] in {"subject_required_weekly_sessions", "subject_required_weekly_minutes"} for item in effective_constraints.get("items", [])),
        explanation="Weekly sessions or minutes should be explicitly covered for curriculum integrity.",
        weight=8,
        evidence={"requirements": len(requirements)},
    )
    add_check(
        key="campus_travel",
        title="Campus travel is covered",
        category="policy",
        mandatory=multi_campus,
        applicable=multi_campus,
        satisfied=not multi_campus or any(item["selected"] and item["type"] == "campus_travel_buffer" for item in effective_constraints.get("items", [])),
        explanation="Cross-campus planning needs a travel buffer when multiple campuses are used.",
        weight=4,
        evidence={"multi_campus": multi_campus},
    )

    all_checks = list(applicable_checks)
    applicable_checks = [item for item in all_checks if item["applicable"]]
    satisfied_checks = [item for item in applicable_checks if item["satisfied"]]
    missing_mandatory_checks = [item for item in applicable_checks if item["mandatory"] and not item["satisfied"]]
    missing_optional_checks = [item for item in applicable_checks if not item["mandatory"] and not item["satisfied"]]
    not_applicable_checks = [item for item in all_checks if not item["applicable"]]

    applicable_weight = sum(int(item["weight"]) for item in applicable_checks)
    completed_weight = sum(int(item["weight"]) for item in satisfied_checks)
    excluded_not_applicable_weight = sum(int(item["weight"]) for item in not_applicable_checks)
    coverage_percentage = 0 if applicable_weight == 0 else int(round((completed_weight / applicable_weight) * 100))

    return {
        "coverage_percentage": coverage_percentage,
        "applicable_weight": applicable_weight,
        "completed_weight": completed_weight,
        "excluded_not_applicable_weight": excluded_not_applicable_weight,
        "applicable_checks": applicable_checks,
        "satisfied_checks": satisfied_checks,
        "missing_mandatory_checks": missing_mandatory_checks,
        "missing_optional_checks": missing_optional_checks,
        "not_applicable_checks": not_applicable_checks,
        "explanation": "; ".join(f"{item['title']}: {'satisfied' if item['satisfied'] else 'missing'}" for item in applicable_checks),
    }


def _build_score_breakdown(
    *,
    canonical_ready: bool,
    policy_lifecycle_ready: bool,
    coverage_ready: bool,
    reference_integrity_ready: bool,
    diagnostic_ready: bool,
    approvals_ready: bool,
    exception_ready: bool,
    coverage: dict[str, Any],
    diagnostics: dict[str, Any],
    exceptions: dict[str, Any],
) -> dict[str, Any]:
    dimensions = [
        {"dimension": "lifecycle_readiness", "weight": 20, "score": 100 if policy_lifecycle_ready else 0},
        {"dimension": "scope_resolution", "weight": 15, "score": 100 if reference_integrity_ready else 0},
        {"dimension": "mandatory_coverage", "weight": 20, "score": int(coverage.get("coverage_percentage", 0))},
        {"dimension": "reference_integrity", "weight": 15, "score": 100 if reference_integrity_ready else 0},
        {"dimension": "diagnostic_feasibility", "weight": 15, "score": 100 if diagnostic_ready else 0},
        {"dimension": "approval_completeness", "weight": 10, "score": 100 if approvals_ready else 0},
        {"dimension": "exception_validity", "weight": 5, "score": 100 if exception_ready else 0},
    ]
    completed_weight = sum(int(item["weight"]) * int(item["score"]) for item in dimensions) // 100
    applicable_weight = sum(int(item["weight"]) for item in dimensions)
    excluded_not_applicable_weight = 0
    overall = 0 if applicable_weight == 0 else int(round(sum(int(item["weight"]) * int(item["score"]) for item in dimensions) / applicable_weight / 100 * 100))
    explanation = "; ".join(f"{item['dimension']}={item['score']}" for item in dimensions)
    return {
        "overall_score": overall,
        "dimensions": dimensions,
        "applicable_weight": applicable_weight,
        "completed_weight": completed_weight,
        "excluded_not_applicable_weight": excluded_not_applicable_weight,
        "calculation_explanation": explanation,
    }


def _build_approval_queue(
    *,
    effective_policy: dict[str, Any],
    effective_constraints: dict[str, Any],
    diagnostics: dict[str, Any],
    exceptions: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    selected_policy = effective_policy.get("selected")

    for candidate in effective_policy.get("rejected_candidates", []):
        if candidate["lifecycle_status"] == "pending_review":
            items.append(
                {
                    "type": "policy_set_pending_review",
                    "title": f"Policy set pending review: {candidate['name']}",
                    "summary": "Leadership review is required before the policy set can become operational.",
                    "urgency": "high",
                    "related_entity": {"type": "TimetablePolicySet", "id": candidate["id"]},
                    "policy_set": candidate["id"],
                    "setup_step": "approvals_and_readiness",
                    "responsible_roles": LEADERSHIP_ROLES,
                    "required_action": "Approve or reject the policy set.",
                    "target_route": "/leadership/timetable-policies/policy-sets",
                    "blocker_relationship": "blocks policy activation",
                    "created_at": _now(),
                    "tenant_safe_references": {"policy_set_id": candidate["id"]},
                }
            )
        elif candidate["lifecycle_status"] == "approved" and not candidate["is_active"]:
            items.append(
                {
                    "type": "policy_set_activation_gap",
                    "title": f"Policy set approved but not active: {candidate['name']}",
                    "summary": "The policy set has approval but still requires activation.",
                    "urgency": "medium",
                    "related_entity": {"type": "TimetablePolicySet", "id": candidate["id"]},
                    "policy_set": candidate["id"],
                    "setup_step": "approvals_and_readiness",
                    "responsible_roles": LEADERSHIP_ROLES,
                    "required_action": "Activate the approved policy set.",
                    "target_route": "/leadership/timetable-policies/policy-sets",
                    "blocker_relationship": "blocks scheduling authorization",
                    "created_at": _now(),
                    "tenant_safe_references": {"policy_set_id": candidate["id"]},
                }
            )

    for item in effective_constraints.get("items", []):
        if not item["selected"] and item["lifecycle_status"] == "pending_review":
            items.append(
                {
                    "type": "constraint_pending_review",
                    "title": f"Constraint pending review: {item['type']}",
                    "summary": "The constraint must be approved before it can affect readiness.",
                    "urgency": "high",
                    "related_entity": {"type": "TimetablePolicyConstraint", "id": item["constraint_id"]},
                    "policy_set": item["policy_set_id"],
                    "setup_step": "approvals_and_readiness",
                    "responsible_roles": LEADERSHIP_ROLES,
                    "required_action": "Approve or reject the constraint.",
                    "target_route": "/leadership/timetable-policies/policy-sets",
                    "blocker_relationship": "blocks policy activation",
                    "created_at": _now(),
                    "tenant_safe_references": {"constraint_id": item["constraint_id"]},
                }
            )

    for item in exceptions.get("issue_details", []):
        if item["status"] == "pending_review":
            items.append(
                {
                    "type": "exception_pending_review",
                    "title": f"Exception pending review: {item['exception_id']}",
                    "summary": "The exception needs leadership approval.",
                    "urgency": "high",
                    "related_entity": {"type": "TimetablePolicyException", "id": item["exception_id"]},
                    "policy_set": None,
                    "setup_step": "approvals_and_readiness",
                    "responsible_roles": LEADERSHIP_ROLES,
                    "required_action": "Approve or reject the exception.",
                    "target_route": "/leadership/timetable-policies/exceptions",
                    "blocker_relationship": "blocks scheduling authorization if required by the policy scope",
                    "created_at": _now(),
                    "tenant_safe_references": {"exception_id": item["exception_id"]},
                }
            )

    for blocker in diagnostics.get("conflicts", []):
        if blocker.get("severity") == "blocker":
            items.append(
                {
                    "type": "diagnostic_resolution",
                    "title": blocker.get("title", "Diagnostic blocker"),
                    "summary": blocker.get("explanation", "Resolve the diagnostic blocker.")[:240],
                    "urgency": "critical",
                    "related_entity": {"type": "PolicyDiagnostic", "id": blocker.get("diagnostic_key")},
                    "policy_set": selected_policy["id"] if selected_policy else None,
                    "setup_step": "approvals_and_readiness",
                    "responsible_roles": LEADERSHIP_ROLES,
                    "required_action": blocker.get("recommended_action", "Adjust policy to resolve the blocker."),
                    "target_route": blocker.get("setup_route", "/leadership/timetable-policies/readiness"),
                    "blocker_relationship": "blocks scheduling authorization",
                    "created_at": _now(),
                    "tenant_safe_references": {"diagnostic_key": blocker.get("diagnostic_key")},
                }
            )

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["type"], str(item.get("related_entity", {}).get("id")))
        if key not in unique:
            unique[key] = item
    ranked = sorted(
        unique.values(),
        key=lambda row: (
            0 if row["urgency"] == "critical" else 1 if row["urgency"] == "high" else 2 if row["urgency"] == "medium" else 3,
            row["title"],
        ),
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def _build_actions(readiness_payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    priority_map = {
        "tenant_or_scope_integrity": 1,
        "canonical_input_missing": 2,
        "no_applicable_policy_set": 3,
        "active_policy_overlap": 4,
        "hard_diagnostic_blocker": 5,
        "fixed_resource_collision": 6,
        "mandatory_approval_gap": 7,
        "invalid_or_expired_exception": 8,
        "inactive_or_missing_reference": 9,
        "policy_coverage_gap": 10,
        "soft_warning": 11,
        "optional_quality_improvement": 12,
    }

    for blocker in readiness_payload.get("readiness_blockers", []):
        actions.append(
            {
                "rank": priority_map.get(blocker["bucket"], 99),
                "severity": blocker.get("severity", "blocker"),
                "action": blocker.get("action"),
                "explanation": blocker.get("explanation"),
                "policy_set": blocker.get("policy_set"),
                "related_constraints": blocker.get("related_constraints", []),
                "affected_entities": blocker.get("affected_entities", []),
                "expected_readiness_impact": blocker.get("expected_readiness_impact", "Raises readiness when resolved."),
                "required_role": blocker.get("required_role", "principal"),
                "approval_requirement": blocker.get("approval_requirement", "leadership"),
                "target_route": blocker.get("target_route", "/leadership/timetable-policies/readiness"),
                "policy_rule": blocker.get("policy_rule", "Deterministic policy readiness gate"),
                "trade_offs": blocker.get("trade_offs", []),
            }
        )

    actions.sort(key=lambda row: (row["rank"], row["action"]))
    return actions


def analyze_policy_readiness_state(
    *,
    canonical_readiness: dict[str, Any],
    policy_sets: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    requirements: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    school_weeks: list[dict[str, Any]],
    bell_periods: list[dict[str, Any]],
    classes: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    teachers: list[dict[str, Any]],
    grade_levels: list[dict[str, Any]],
    academic_years: list[dict[str, Any]],
    terms: list[dict[str, Any]],
    campuses: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    policy_resolution = _select_effective_policy_set(policy_sets, context)
    selected_policy = policy_resolution.get("selected")
    context = dict(context)
    context["selected_policy_set_id"] = selected_policy["id"] if selected_policy else None

    effective_constraints = _build_effective_constraints(selected_policy, constraints, exceptions, context)
    exception_readiness = _evaluate_exceptions(exceptions=exceptions, selected_policy=selected_policy, effective_constraints=effective_constraints["items"], context=context)
    coverage = _evaluate_coverage(
        canonical_readiness=canonical_readiness,
        effective_policy=policy_resolution,
        effective_constraints=effective_constraints,
        diagnostics=diagnostics,
        exceptions=exception_readiness,
        context=context,
        requirements=requirements,
        rooms=rooms,
        school_weeks=school_weeks,
        bell_periods=bell_periods,
    )

    policy_blocker_count = 0
    policy_warning_count = 0
    policy_information_count = 0
    if selected_policy is None:
        policy_blocker_count += 1
    if policy_resolution.get("unresolved_ambiguity"):
        policy_blocker_count += 1
    if policy_resolution.get("selected") is not None and policy_resolution["selected"]["lifecycle_status"] != "active":
        policy_blocker_count += 1
    if policy_resolution.get("selected") is not None and not policy_resolution["selected"]["is_active"]:
        policy_blocker_count += 1
    if policy_resolution.get("selected") is not None and not _effective_at_is_valid(policy_resolution["selected"], context.get("effective_at")):
        policy_blocker_count += 1
    if selected_policy is not None and any(item["lifecycle_status"] == "pending_review" for item in policy_resolution.get("rejected_candidates", [])):
        policy_warning_count += 1
    if selected_policy is not None and any(item["lifecycle_status"] == "approved" and not item["is_active"] for item in policy_resolution.get("rejected_candidates", [])):
        policy_warning_count += 1
    if not any(item["mandatory"] and not item["satisfied"] for item in coverage["applicable_checks"]):
        policy_information_count += 1

    policy_lifecycle_ready = selected_policy is not None and selected_policy["lifecycle_status"] == "active" and selected_policy["is_active"] and not policy_resolution.get("unresolved_ambiguity")
    policy_coverage_ready = not any(item["mandatory"] and not item["satisfied"] for item in coverage["applicable_checks"])
    diagnostic_feasibility_ready = int(diagnostics.get("generation", {}).get("blocker_count", 0)) == 0 and int(effective_constraints.get("blocker_count", 0)) == 0
    exceptions_ready = exception_readiness["ready"]
    approvals_ready = int(policy_resolution.get("operational_candidate_count", 0)) > 0 and int(exception_readiness.get("pending_exception_count", 0)) == 0
    canonical_input_ready = int(canonical_readiness.get("blocker_count", 0)) == 0
    reference_integrity_ready = selected_policy is not None and all(item is not None for item in context.values() if item is not None and not isinstance(item, datetime))

    pending_approval_count = (
        int(policy_resolution.get("candidate_count", 0)) - int(policy_resolution.get("operational_candidate_count", 0))
        + int(exception_readiness.get("pending_exception_count", 0))
        + sum(1 for item in effective_constraints.get("items", []) if item["lifecycle_status"] == "pending_review")
    )
    unresolved_diagnostic_count = int(diagnostics.get("generation", {}).get("blocker_count", 0)) + int(effective_constraints.get("blocker_count", 0))
    expired_exception_count = int(exception_readiness.get("expired_exception_count", 0))

    blockers: list[dict[str, Any]] = []
    if not canonical_input_ready:
        blockers.append({"bucket": "canonical_input_missing", "severity": "blocker", "action": "Complete Phase 10A canonical timetable inputs.", "explanation": "Canonical readiness still has blockers.", "policy_rule": "Canonical inputs are mandatory before scheduling authorization.", "target_route": "/leadership/timetable-setup/readiness", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})
    if selected_policy is None:
        blockers.append({"bucket": "no_applicable_policy_set", "severity": "blocker", "action": "Approve and activate an applicable policy set.", "explanation": "No approved active policy set is available for the planning context.", "policy_rule": "Only approved and active policy sets are operational.", "target_route": "/leadership/timetable-policies/policy-sets", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})
    if policy_resolution.get("unresolved_ambiguity"):
        blockers.append({"bucket": "active_policy_overlap", "severity": "blocker", "action": "Resolve the active policy overlap.", "explanation": "Multiple operational candidates remain for the same policy scope.", "policy_rule": "Contradictory active policy sets must not be silently resolved.", "target_route": "/leadership/timetable-policies/policy-sets", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})
    for blocker in diagnostics.get("conflicts", []):
        if blocker.get("severity") == "blocker":
            bucket = "hard_diagnostic_blocker" if blocker.get("kind") == "conflict" else "fixed_resource_collision"
            blockers.append({"bucket": bucket, "severity": "blocker", "action": blocker.get("recommended_action", "Resolve the diagnostic blocker."), "explanation": blocker.get("explanation", blocker.get("summary", "Diagnostic blocker present.")), "policy_rule": blocker.get("title", "Policy diagnostic blocker"), "target_route": blocker.get("setup_route", "/leadership/timetable-policies/readiness"), "required_role": "principal", "approval_requirement": "leadership", "related_constraints": blocker.get("constraint_ids", []), "affected_entities": []})
    if pending_approval_count > 0:
        blockers.append({"bucket": "mandatory_approval_gap", "severity": "blocker", "action": "Complete the pending leadership approvals.", "explanation": "There are pending policy, constraint, or exception approvals.", "policy_rule": "Pending mandatory review blocks scheduling authorization.", "target_route": "/leadership/timetable-policies/readiness/approvals", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})
    if expired_exception_count > 0 or not exceptions_ready:
        blockers.append({"bucket": "invalid_or_expired_exception", "severity": "blocker", "action": "Fix or remove invalid exceptions.", "explanation": "At least one exception is invalid, expired, or conflicting.", "policy_rule": "Approved exceptions must be valid and unexpired.", "target_route": "/leadership/timetable-policies/exceptions", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": exception_readiness.get("affected_constraints", []), "affected_entities": []})
    if not policy_coverage_ready:
        blockers.append({"bucket": "policy_coverage_gap", "severity": "blocker", "action": "Add the missing mandatory policy coverage.", "explanation": "One or more mandatory coverage checks are still missing.", "policy_rule": "Mandatory policy coverage must be satisfied.", "target_route": "/leadership/timetable-policies/readiness/effective-constraints", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})
    if unresolved_diagnostic_count > 0:
        blockers.append({"bucket": "hard_diagnostic_blocker", "severity": "blocker", "action": "Resolve the diagnostic blocker.", "explanation": "Derived diagnostics still contain blockers.", "policy_rule": "No impossible policy diagnostic may remain.", "target_route": "/leadership/timetable-policies/diagnostics", "required_role": "principal", "approval_requirement": "leadership", "related_constraints": [], "affected_entities": []})

    warnings = []
    if policy_warning_count > 0:
        warnings.append({"bucket": "soft_warning", "severity": "warning", "action": "Review the policy warnings.", "explanation": "The selected policy context has warnings but no hard blocker.", "policy_rule": "Warnings may still permit scheduling when no mandatory blocker exists.", "target_route": "/leadership/timetable-policies/readiness/effective-policy", "required_role": "principal", "approval_requirement": "review", "related_constraints": [], "affected_entities": []})

    policy_generation_allowed = policy_lifecycle_ready and policy_coverage_ready and diagnostic_feasibility_ready and exceptions_ready and approvals_ready and unresolved_diagnostic_count == 0 and not blockers
    diagnostic_generation_allowed = int(diagnostics.get("generation", {}).get("blocker_count", 0)) == 0
    canonical_input_generation_allowed = canonical_input_ready
    generation_allowed = canonical_input_generation_allowed and policy_generation_allowed and diagnostic_generation_allowed

    if blockers:
        readiness_status = "blocked"
    elif pending_approval_count > 0:
        readiness_status = "needs_review"
    elif warnings:
        readiness_status = "conditionally_ready"
    elif generation_allowed:
        readiness_status = "ready"
    else:
        readiness_status = "not_configured" if selected_policy is None else "needs_review"

    score_breakdown = _build_score_breakdown(
        canonical_ready=canonical_input_ready,
        policy_lifecycle_ready=policy_lifecycle_ready,
        coverage_ready=policy_coverage_ready,
        reference_integrity_ready=reference_integrity_ready,
        diagnostic_ready=diagnostic_feasibility_ready,
        approvals_ready=approvals_ready,
        exception_ready=exceptions_ready,
        coverage=coverage,
        diagnostics=diagnostics,
        exceptions=exception_readiness,
    )

    approval_queue = _build_approval_queue(effective_policy=policy_resolution, effective_constraints=effective_constraints, diagnostics=diagnostics, exceptions=exception_readiness)
    readiness_payload = {
        "calculation_id": str(uuid.uuid5(uuid.NAMESPACE_URL, _json_text({"tenant_id": context.get("tenant_id"), "policy_set_id": context.get("selected_policy_set_id"), "scope": {k: v for k, v in context.items() if k != "effective_at"}, "policy_count": len(policy_sets), "constraint_count": len(constraints), "exception_count": len(exceptions)}))),
        "tenant": {"id": str(context.get("tenant_id")), "context_label": _context_label(context)},
        "academic_year": _serialize_uuid(uuid.UUID(context["academic_year_id"])) if context.get("academic_year_id") else None,
        "term": _serialize_uuid(uuid.UUID(context["term_id"])) if context.get("term_id") else None,
        "campus": _serialize_uuid(uuid.UUID(context["campus_id"])) if context.get("campus_id") else None,
        "planning_scope": context,
        "policy_set_id": selected_policy["id"] if selected_policy else None,
        "policy_set_status": selected_policy["lifecycle_status"] if selected_policy else None,
        "policy_set_version": selected_policy["version_number"] if selected_policy else None,
        "evaluated_at": _now(),
        "readiness_status": readiness_status,
        "generation_allowed": generation_allowed,
        "canonical_input_generation_allowed": canonical_input_generation_allowed,
        "policy_generation_allowed": policy_generation_allowed,
        "diagnostic_generation_allowed": diagnostic_generation_allowed,
        "overall_policy_score": score_breakdown["overall_score"],
        "canonical_input_ready": canonical_input_ready,
        "policy_lifecycle_ready": policy_lifecycle_ready,
        "policy_coverage_ready": policy_coverage_ready,
        "diagnostic_feasibility_ready": diagnostic_feasibility_ready,
        "exceptions_ready": exceptions_ready,
        "approvals_ready": approvals_ready,
        "blocker_count": int(canonical_readiness.get("blocker_count", 0)) + len(blockers),
        "warning_count": int(canonical_readiness.get("warning_count", 0)) + len(warnings),
        "information_count": int(canonical_readiness.get("information_count", 0)) + int(coverage.get("not_applicable_checks") and len(coverage.get("not_applicable_checks")) or 0),
        "pending_approval_count": pending_approval_count,
        "expired_exception_count": expired_exception_count,
        "unresolved_diagnostic_count": unresolved_diagnostic_count,
        "effective_constraint_count": effective_constraints.get("effective_constraint_count", 0),
        "skipped_check_count": len(coverage.get("not_applicable_checks", [])),
        "required_actions": [],
        "policy_explanation": {
            "selected_policy_set": policy_resolution.get("selected"),
            "rejected_candidates": policy_resolution.get("rejected_candidates", []),
            "precedence_reason": policy_resolution.get("selected_reason"),
            "conflicting_policy_sets": [item for item in policy_resolution.get("rejected_candidates", []) if item.get("selected") is False and item.get("lifecycle_status") == "active"],
            "unresolved_ambiguity": policy_resolution.get("unresolved_ambiguity"),
        },
        "calculation_breakdown": {
            "policy_resolution": policy_resolution,
            "effective_constraints": effective_constraints,
            "coverage": coverage,
            "score_breakdown": score_breakdown,
            "diagnostics": diagnostics,
            "exception_readiness": exception_readiness,
            "approval_queue_count": len(approval_queue),
            "canonical_readiness": canonical_readiness,
        },
        "source_and_provenance_summary": {
            "policy_set_count": len(policy_sets),
            "constraint_count": len(constraints),
            "exception_count": len(exceptions),
            "requirement_count": len(requirements),
            "room_count": len(rooms),
            "school_week_count": len(school_weeks),
            "bell_period_count": len(bell_periods),
            "class_count": len(classes),
            "subject_count": len(subjects),
            "teacher_count": len(teachers),
            "grade_level_count": len(grade_levels),
            "academic_year_count": len(academic_years),
            "term_count": len(terms),
            "campus_count": len(campuses),
            "diagnostic_generation_allowed": diagnostics.get("generation", {}).get("generation_allowed", True),
            "context_label": _context_label(context),
        },
        "effective_policy_set": policy_resolution.get("selected"),
        "effective_constraints": effective_constraints.get("items", []),
        "coverage": coverage,
        "policy_score": score_breakdown,
        "approval_queue": approval_queue,
        "exception_readiness": exception_readiness,
        "policy_readiness_status": readiness_status,
        "policy_blocker_count": len(blockers),
        "policy_warning_count": len(warnings),
        "policy_pending_approval_count": pending_approval_count,
        "policy_required_actions": approval_queue,
        "readiness_blockers": blockers,
        "readiness_warnings": warnings,
    }

    readiness_payload["required_actions"] = _build_actions(readiness_payload)
    return readiness_payload


async def build_policy_readiness_payload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    academic_year_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    grade_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    effective_at: datetime | None = None,
) -> dict[str, Any]:
    context_refs = await _validate_context_references(
        db=db,
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        term_id=term_id,
        campus_id=campus_id,
        grade_id=grade_id,
        class_id=class_id,
        subject_id=subject_id,
        teacher_id=teacher_id,
        room_id=room_id,
        department_id=department_id,
    )
    rows = await _load_rows(db, tenant_id)
    context = _context_from_filters(
        academic_year_id=academic_year_id,
        term_id=term_id,
        campus_id=campus_id,
        grade_id=grade_id,
        class_id=class_id,
        subject_id=subject_id,
        teacher_id=teacher_id,
        room_id=room_id,
        effective_at=effective_at,
    )
    context.update({"tenant_id": str(tenant_id), "context_refs": context_refs})
    payload = analyze_policy_readiness_state(
        canonical_readiness=rows["canonical_readiness"],
        policy_sets=rows["policy_sets"],
        constraints=rows["constraints"],
        exceptions=rows["exceptions"],
        diagnostics=rows["diagnostics"],
        requirements=rows["requirements"],
        rooms=rows["rooms"],
        school_weeks=rows["school_weeks"],
        bell_periods=rows["bell_periods"],
        classes=rows["classes"],
        subjects=rows["subjects"],
        teachers=rows["teachers"],
        grade_levels=rows["grade_levels"],
        academic_years=rows["academic_years"],
        terms=rows["terms"],
        campuses=rows["campuses"],
        context=context,
    )
    payload["context_validation"] = context_refs
    payload["diagnostics"] = rows["diagnostics"]
    payload["generated_at"] = _now()
    return payload
