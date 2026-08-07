from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.policy_readiness import build_policy_readiness_payload
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    BellSchedule,
    Campus,
    Class,
    Subject,
    Teacher,
    TeachingRoom,
    Tenant,
    Term,
    TimetableGenerationConfiguration,
    TimetableGenerationLock,
    TimetableGenerationObjective,
    TimetableGenerationOverride,
    TimetableParallelLessonBlock,
    TimetableParallelLessonChild,
    TimetableTeacherSchedulingPreference,
    User,
    WeeklyTeachingRequirement,
)


router = APIRouter(prefix="/leadership/timetable-generation", tags=["Timetable Generation"])

GENERATION_MODES = {"standard", "customized", "repair"}
STABILITY_MODES = {"very_high", "high", "balanced", "flexible"}
CONFIG_LIFECYCLE = {"draft", "ready_for_review", "approved", "superseded", "cancelled"}
PREFERENCE_STRENGTHS = {"hard", "strong", "normal", "low"}
PREFERENCE_TYPES = {
    "avoid_first_period",
    "avoid_last_period",
    "avoid_selected_periods",
    "prefer_selected_periods",
    "unavailable_selected_periods",
    "prefer_grouped_free_periods",
    "prefer_selected_days",
    "avoid_selected_days",
    "temporary_accommodation",
}
OVERRIDE_TYPES = {
    "teacher_free_period",
    "class_subject_timing_preference",
    "room_avoidance",
    "repair_assignment_protection",
    "other_override",
}
SCOPE_TYPES = {
    "whole_school",
    "campus",
    "department",
    "grade",
    "class",
    "subject",
    "teacher",
    "room",
    "day",
    "period",
    "period_range",
    "session_reference",
}
LOCK_STATES = {"locked", "prefer_to_keep", "flexible"}
LOCK_TARGET_TYPES = {
    "session_reference",
    "teacher",
    "class",
    "subject",
    "grade",
    "room",
    "day",
    "period",
    "period_range",
}
REPAIR_SCOPE_LEVELS = {"minimum", "affected_entities", "grade", "whole_school"}
REPAIR_REASONS = {
    "teacher_departure",
    "teacher_replacement",
    "teacher_assignment_change",
    "teacher_department_change",
    "teacher_availability_change",
    "class_added",
    "class_removed",
    "class_requirement_change",
    "room_unavailable",
    "room_change",
    "policy_change",
    "bell_structure_change",
    "manual_adjustment",
    "other_controlled_reason",
}
OBJECTIVE_KEYS = {
    "satisfy_hard_constraints",
    "teacher_preferences",
    "workload_balance",
    "subject_distribution",
    "minimize_teacher_gaps",
    "minimize_room_changes",
    "minimize_timetable_disruption",
    "preference_fairness",
    "preserve_existing_assignments",
}
OBJECTIVE_PRIORITIES = {"critical", "high", "normal", "low"}
PARALLEL_BLOCK_TYPES = {"foreign_language", "electives", "split_class", "other_parallel"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_required_text(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must not be blank.")
    return cleaned


def _ensure_actor_tenant(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class GenerationObjectiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_key: str
    priority_level: str


class GenerationConfigurationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID | None = None
    bell_schedule_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    generation_mode: str = "standard"
    stability_mode: str = "balanced"
    baseline_reference_type: str | None = None
    baseline_reference_id: uuid.UUID | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    source_type: str = "manual"
    objective_priorities: list[GenerationObjectiveInput] = Field(default_factory=list)
    repair_scope: dict[str, Any] = Field(default_factory=dict)
    effective_context: dict[str, Any] = Field(default_factory=dict)


class GenerationConfigurationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bell_schedule_id: uuid.UUID | None = None
    name: str | None = None
    description: str | None = None
    stability_mode: str | None = None
    baseline_reference_type: str | None = None
    baseline_reference_id: uuid.UUID | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    objective_priorities: list[GenerationObjectiveInput] | None = None
    repair_scope: dict[str, Any] | None = None
    effective_context: dict[str, Any] | None = None


class LifecycleReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class TeacherPreferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teacher_id: uuid.UUID
    academic_year_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID | None = None
    preference_type: str
    strength: str
    weekdays: list[int] = Field(default_factory=list)
    period_numbers: list[int] = Field(default_factory=list)
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    temporary_accommodation_text: str | None = None
    leadership_note: str | None = None
    source_type: str = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)


class TeacherPreferencePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference_type: str | None = None
    strength: str | None = None
    weekdays: list[int] | None = None
    period_numbers: list[int] | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    temporary_accommodation_text: str | None = None
    leadership_note: str | None = None
    is_active: bool | None = None


class GenerationOverrideCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_type: str
    strength: str
    scope_type: str
    scope_reference_id: uuid.UUID | None = None
    scope_reference_code: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_type: str = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)


class GenerationOverridePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strength: str | None = None
    scope_type: str | None = None
    scope_reference_id: uuid.UUID | None = None
    scope_reference_code: str | None = None
    payload: dict[str, Any] | None = None
    is_active: bool | None = None


class GenerationLockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_state: str
    target_type: str
    target_reference_id: uuid.UUID | None = None
    target_reference_code: str | None = None
    day_of_week: int | None = None
    period_number: int | None = None
    period_end_number: int | None = None
    is_manual_hard_lock: bool = False
    source_type: str = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)


class GenerationLockPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_state: str | None = None
    target_type: str | None = None
    target_reference_id: uuid.UUID | None = None
    target_reference_code: str | None = None
    day_of_week: int | None = None
    period_number: int | None = None
    period_end_number: int | None = None
    is_manual_hard_lock: bool | None = None
    is_active: bool | None = None


class ParallelLessonChildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    teacher_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    sequence_order: int | None = None
    requirement: dict[str, Any] = Field(default_factory=dict)


class ParallelLessonBlockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID | None = None
    class_id: uuid.UUID
    display_label: str
    block_type: str
    synchronization_requirement: str = "same_period"
    source_type: str = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)
    children: list[ParallelLessonChildInput] = Field(default_factory=list)


class ParallelLessonBlockPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_label: str | None = None
    block_type: str | None = None
    synchronization_requirement: str | None = None
    children: list[ParallelLessonChildInput] | None = None
    is_active: bool | None = None


def _validate_date_range(start_date: date_type | None, end_date: date_type | None, *, field: str = "effective_end_date") -> None:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field} cannot be before effective_start_date.")


def _validate_weekdays(weekdays: list[int]) -> None:
    for item in weekdays:
        if item < 0 or item > 6:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="weekdays must be between 0 and 6.")


def _validate_period_numbers(period_numbers: list[int]) -> None:
    for item in period_numbers:
        if item <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_numbers must be positive integers.")


async def _require_active_context(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    term_id: uuid.UUID,
    campus_id: uuid.UUID | None,
) -> None:
    year = await db.scalar(select(AcademicYear).where(AcademicYear.id == academic_year_id, AcademicYear.tenant_id == tenant_id, AcademicYear.is_active.is_(True)))
    if year is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Academic year not found in tenant scope.")

    term = await db.scalar(select(Term).where(Term.id == term_id, Term.tenant_id == tenant_id, Term.is_active.is_(True)))
    if term is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Term not found in tenant scope.")
    if term.academic_year_id != academic_year_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Term does not belong to selected academic year.")

    if campus_id is not None:
        campus = await db.scalar(select(Campus).where(Campus.id == campus_id, Campus.tenant_id == tenant_id, Campus.is_active.is_(True)))
        if campus is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campus not found in tenant scope.")


async def _validate_bell_schedule_scope(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    bell_schedule_id: uuid.UUID | None,
    academic_year_id: uuid.UUID,
    term_id: uuid.UUID,
    campus_id: uuid.UUID | None,
) -> None:
    if bell_schedule_id is None:
        return
    item = await db.scalar(
        select(BellSchedule).where(
            BellSchedule.id == bell_schedule_id,
            BellSchedule.tenant_id == tenant_id,
            BellSchedule.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bell schedule not found in tenant scope.")
    if item.academic_year_id not in {None, academic_year_id}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bell schedule academic year mismatch.")
    if item.term_id not in {None, term_id}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bell schedule term mismatch.")
    if item.campus_id not in {None, campus_id}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bell schedule campus mismatch.")


async def _resolve_scope_reference(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scope_type: str,
    scope_reference_id: uuid.UUID | None,
    scope_reference_code: str | None,
) -> None:
    if scope_type not in SCOPE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported scope_type.")

    if scope_type in {"whole_school"}:
        if scope_reference_id is not None or (scope_reference_code or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="whole_school scope cannot include scope references.")
        return

    if scope_type in {"grade", "day", "period", "period_range", "session_reference"}:
        if scope_reference_id is None and not (scope_reference_code or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{scope_type} scope requires a reference.")
        return

    if scope_reference_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{scope_type} scope requires scope_reference_id.")

    model_lookup = {
        "campus": Campus,
        "class": Class,
        "subject": Subject,
        "teacher": Teacher,
        "room": TeachingRoom,
    }
    model = model_lookup.get(scope_type)
    if model is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported scope_type.")

    stmt = select(model).where(model.id == scope_reference_id, model.tenant_id == tenant_id)
    if hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))
    row = await db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{scope_type} reference is outside tenant scope or inactive.")


def _configuration_payload(item: TimetableGenerationConfiguration) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "bell_schedule_id": str(item.bell_schedule_id) if item.bell_schedule_id else None,
        "name": item.name,
        "description": item.description,
        "generation_mode": item.generation_mode,
        "stability_mode": item.stability_mode,
        "lifecycle_status": item.lifecycle_status,
        "baseline_reference_type": item.baseline_reference_type,
        "baseline_reference_id": str(item.baseline_reference_id) if item.baseline_reference_id else None,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "objective_priorities": item.objective_priorities_json,
        "repair_scope": item.repair_scope_json,
        "effective_context": item.effective_context_json,
        "validation_summary": item.validation_summary_json,
        "source_type": item.source_type,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "reviewed_by_user_id": str(item.reviewed_by_user_id) if item.reviewed_by_user_id else None,
        "approved_by_user_id": str(item.approved_by_user_id) if item.approved_by_user_id else None,
        "reviewed_at": item.reviewed_at,
        "approved_at": item.approved_at,
        "superseded_by_configuration_id": str(item.superseded_by_configuration_id) if item.superseded_by_configuration_id else None,
        "cancellation_reason": item.cancellation_reason,
        "version_number": item.version_number,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _preference_payload(item: TimetableTeacherSchedulingPreference) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "teacher_id": str(item.teacher_id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "preference_type": item.preference_type,
        "strength": item.strength,
        "weekdays": item.weekdays_json,
        "period_numbers": item.period_numbers_json,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "temporary_accommodation_text": item.temporary_accommodation_text,
        "leadership_note": item.leadership_note,
        "source_type": item.source_type,
        "provenance": item.provenance_json,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _override_payload(item: TimetableGenerationOverride) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "configuration_id": str(item.configuration_id),
        "override_type": item.override_type,
        "strength": item.strength,
        "scope_type": item.scope_type,
        "scope_reference_id": str(item.scope_reference_id) if item.scope_reference_id else None,
        "scope_reference_code": item.scope_reference_code,
        "payload": item.payload_json,
        "source_type": item.source_type,
        "provenance": item.provenance_json,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _lock_payload(item: TimetableGenerationLock) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "configuration_id": str(item.configuration_id),
        "lock_state": item.lock_state,
        "target_type": item.target_type,
        "target_reference_id": str(item.target_reference_id) if item.target_reference_id else None,
        "target_reference_code": item.target_reference_code,
        "day_of_week": item.day_of_week,
        "period_number": item.period_number,
        "period_end_number": item.period_end_number,
        "is_manual_hard_lock": item.is_manual_hard_lock,
        "source_type": item.source_type,
        "provenance": item.provenance_json,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _parallel_block_payload(item: TimetableParallelLessonBlock, children: list[TimetableParallelLessonChild]) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "class_id": str(item.class_id),
        "display_label": item.display_label,
        "block_type": item.block_type,
        "synchronization_requirement": item.synchronization_requirement,
        "source_type": item.source_type,
        "provenance": item.provenance_json,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "children": [
            {
                "id": str(child.id),
                "requirement_id": str(child.requirement_id) if child.requirement_id else None,
                "subject_id": str(child.subject_id) if child.subject_id else None,
                "teacher_id": str(child.teacher_id) if child.teacher_id else None,
                "room_id": str(child.room_id) if child.room_id else None,
                "sequence_order": child.sequence_order,
                "requirement": child.requirement_json,
                "is_active": child.is_active,
            }
            for child in children
        ],
    }


async def _replace_objectives(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    configuration_id: uuid.UUID,
    objectives: list[GenerationObjectiveInput],
) -> list[dict[str, str]]:
    existing = (
        await db.execute(
            select(TimetableGenerationObjective).where(
                TimetableGenerationObjective.tenant_id == tenant_id,
                TimetableGenerationObjective.configuration_id == configuration_id,
            )
        )
    ).scalars().all()
    for row in existing:
        await db.delete(row)

    payload: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in objectives:
        if item.objective_key not in OBJECTIVE_KEYS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported objective_key.")
        if item.priority_level not in OBJECTIVE_PRIORITIES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported objective priority.")
        if item.objective_key in seen:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Duplicate objective_key is not allowed.")
        seen.add(item.objective_key)
        row = TimetableGenerationObjective(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            configuration_id=configuration_id,
            objective_key=item.objective_key,
            priority_level=item.priority_level,
        )
        db.add(row)
        payload.append({"objective_key": item.objective_key, "priority_level": item.priority_level})
    return payload


def _validate_repair_scope(value: dict[str, Any]) -> None:
    if not value:
        return
    scope_level = value.get("scope_level")
    if scope_level is not None and scope_level not in REPAIR_SCOPE_LEVELS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported repair scope level.")
    reasons = value.get("reasons") or []
    for reason in reasons:
        if reason not in REPAIR_REASONS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported repair reason.")


async def _run_generation_validation(
    *,
    db: AsyncSession,
    tenant: Tenant,
    config: TimetableGenerationConfiguration,
) -> dict[str, Any]:
    errors: list[str] = []

    if config.generation_mode not in GENERATION_MODES:
        errors.append("Unsupported generation mode.")

    if config.generation_mode == "repair" and config.baseline_reference_id is None:
        errors.append("Repair mode requires a baseline_reference_id.")

    if config.generation_mode in {"standard", "customized"} and config.baseline_reference_id is not None and config.baseline_reference_type is None:
        errors.append("baseline_reference_type is required when baseline_reference_id is provided.")

    if config.stability_mode not in STABILITY_MODES:
        errors.append("Unsupported stability mode.")

    if config.effective_end_date and config.effective_start_date and config.effective_end_date < config.effective_start_date:
        errors.append("effective_end_date cannot be before effective_start_date.")

    await _require_active_context(
        db=db,
        tenant_id=tenant.id,
        academic_year_id=config.academic_year_id,
        term_id=config.term_id,
        campus_id=config.campus_id,
    )

    await _validate_bell_schedule_scope(
        db=db,
        tenant_id=tenant.id,
        bell_schedule_id=config.bell_schedule_id,
        academic_year_id=config.academic_year_id,
        term_id=config.term_id,
        campus_id=config.campus_id,
    )

    policy_gate = await build_policy_readiness_payload(
        db,
        tenant.id,
        academic_year_id=config.academic_year_id,
        term_id=config.term_id,
        campus_id=config.campus_id,
    )

    summary = {
        "validated_at": _now().isoformat(),
        "is_valid": len(errors) == 0,
        "errors": errors,
        "policy_generation_allowed": bool(policy_gate.get("generation_allowed", False)),
        "policy_readiness_status": policy_gate.get("readiness_status"),
        "policy_blocker_count": int(policy_gate.get("policy_blocker_count", 0)),
    }
    return summary


@router.get("/configurations", summary="List generation configurations")
async def list_generation_configurations(
    lifecycle_status: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = (
        select(TimetableGenerationConfiguration)
        .where(TimetableGenerationConfiguration.tenant_id == tenant.id)
        .order_by(TimetableGenerationConfiguration.created_at.desc())
    )
    if lifecycle_status is not None:
        if lifecycle_status not in CONFIG_LIFECYCLE:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported lifecycle_status.")
        stmt = stmt.where(TimetableGenerationConfiguration.lifecycle_status == lifecycle_status)

    rows = (await db.execute(stmt)).scalars().all()
    return [_configuration_payload(item) for item in rows]


@router.post("/configurations", summary="Create generation configuration draft")
async def create_generation_configuration(
    body: GenerationConfigurationCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.generation_mode not in GENERATION_MODES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported generation_mode.")
    if body.stability_mode not in STABILITY_MODES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported stability_mode.")

    _validate_date_range(body.effective_start_date, body.effective_end_date)
    _validate_repair_scope(body.repair_scope)

    await _require_active_context(
        db=db,
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
    )
    await _validate_bell_schedule_scope(
        db=db,
        tenant_id=tenant.id,
        bell_schedule_id=body.bell_schedule_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
    )

    if body.generation_mode == "repair" and body.baseline_reference_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Repair mode requires baseline_reference_id.")

    item = TimetableGenerationConfiguration(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
        bell_schedule_id=body.bell_schedule_id,
        name=_clean_required_text(body.name, label="name"),
        description=body.description,
        generation_mode=body.generation_mode,
        stability_mode=body.stability_mode,
        lifecycle_status="draft",
        baseline_reference_type=body.baseline_reference_type,
        baseline_reference_id=body.baseline_reference_id,
        effective_start_date=body.effective_start_date,
        effective_end_date=body.effective_end_date,
        objective_priorities_json={},
        repair_scope_json=body.repair_scope,
        effective_context_json=body.effective_context,
        validation_summary_json={},
        source_type=body.source_type,
        created_by_user_id=actor.id,
    )
    db.add(item)
    await db.flush()

    objectives = await _replace_objectives(db=db, tenant_id=tenant.id, configuration_id=item.id, objectives=body.objective_priorities)
    item.objective_priorities_json = {entry["objective_key"]: entry["priority_level"] for entry in objectives}

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.created",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"generation_mode": item.generation_mode, "stability_mode": item.stability_mode},
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.get("/configurations/{configuration_id}", summary="Get one generation configuration")
async def get_generation_configuration(
    configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    return _configuration_payload(item)


@router.patch("/configurations/{configuration_id}", summary="Update generation configuration draft")
async def patch_generation_configuration(
    configuration_id: uuid.UUID,
    body: GenerationConfigurationPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if item.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft configurations can be edited.")

    if body.name is not None:
        item.name = _clean_required_text(body.name, label="name")
    if body.description is not None:
        item.description = body.description
    if body.stability_mode is not None:
        if body.stability_mode not in STABILITY_MODES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported stability_mode.")
        item.stability_mode = body.stability_mode

    if body.baseline_reference_type is not None:
        item.baseline_reference_type = body.baseline_reference_type
    if body.baseline_reference_id is not None:
        item.baseline_reference_id = body.baseline_reference_id

    if body.effective_start_date is not None:
        item.effective_start_date = body.effective_start_date
    if body.effective_end_date is not None:
        item.effective_end_date = body.effective_end_date
    _validate_date_range(item.effective_start_date, item.effective_end_date)

    if body.bell_schedule_id is not None:
        await _validate_bell_schedule_scope(
            db=db,
            tenant_id=tenant.id,
            bell_schedule_id=body.bell_schedule_id,
            academic_year_id=item.academic_year_id,
            term_id=item.term_id,
            campus_id=item.campus_id,
        )
        item.bell_schedule_id = body.bell_schedule_id

    if body.repair_scope is not None:
        _validate_repair_scope(body.repair_scope)
        item.repair_scope_json = body.repair_scope
    if body.effective_context is not None:
        item.effective_context_json = body.effective_context

    if body.objective_priorities is not None:
        objectives = await _replace_objectives(
            db=db,
            tenant_id=tenant.id,
            configuration_id=item.id,
            objectives=body.objective_priorities,
        )
        item.objective_priorities_json = {entry["objective_key"]: entry["priority_level"] for entry in objectives}

    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.modified",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lifecycle_status": item.lifecycle_status, "version_number": item.version_number},
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.post("/configurations/{configuration_id}/validate", summary="Validate generation configuration")
async def validate_generation_configuration(
    configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")

    summary = await _run_generation_validation(db=db, tenant=tenant, config=item)
    item.validation_summary_json = summary
    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.validated",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_valid": summary["is_valid"]},
    )
    await db.commit()
    await db.refresh(item)

    return {
        "configuration_id": str(item.id),
        "lifecycle_status": item.lifecycle_status,
        "validation": summary,
        "future_solver_eligible": bool(summary.get("is_valid") and summary.get("policy_generation_allowed")),
    }


@router.post("/configurations/{configuration_id}/submit", summary="Submit draft configuration for review")
async def submit_generation_configuration(
    configuration_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if item.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft configurations can be submitted.")

    summary = await _run_generation_validation(db=db, tenant=tenant, config=item)
    item.validation_summary_json = summary
    if not summary["is_valid"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": "Configuration validation failed.", "errors": summary["errors"]})

    item.lifecycle_status = "ready_for_review"
    item.reviewed_by_user_id = actor.id
    item.reviewed_at = _now()
    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.submitted",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.post("/configurations/{configuration_id}/approve", summary="Approve generation configuration")
async def approve_generation_configuration(
    configuration_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if item.lifecycle_status != "ready_for_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only ready_for_review configurations can be approved.")

    item.lifecycle_status = "approved"
    item.approved_by_user_id = actor.id
    item.approved_at = _now()
    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.approved",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={
            "reason": body.reason,
            "future_problem_builder_eligible": True,
            "solver_started": False,
            "timetable_published": False,
        },
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.post("/configurations/{configuration_id}/cancel", summary="Cancel generation configuration")
async def cancel_generation_configuration(
    configuration_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if item.lifecycle_status not in {"draft", "ready_for_review", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Configuration cannot be cancelled from current state.")

    item.lifecycle_status = "cancelled"
    item.cancellation_reason = body.reason
    item.is_active = False
    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.cancelled",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.post("/configurations/{configuration_id}/supersede", summary="Supersede generation configuration")
async def supersede_generation_configuration(
    configuration_id: uuid.UUID,
    body: LifecycleReasonRequest,
    superseded_by_configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    replacement = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == superseded_by_configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if item is None or replacement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if item.id == replacement.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A configuration cannot supersede itself.")

    item.lifecycle_status = "superseded"
    item.superseded_by_configuration_id = replacement.id
    item.is_active = False
    item.version_number += 1

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.configuration.superseded",
        entity_type="TimetableGenerationConfiguration",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason, "superseded_by_configuration_id": str(replacement.id)},
    )
    await db.commit()
    await db.refresh(item)
    return _configuration_payload(item)


@router.get("/preferences", summary="List teacher scheduling preferences")
async def list_teacher_preferences(
    active_only: bool = Query(default=True),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(TimetableTeacherSchedulingPreference).where(TimetableTeacherSchedulingPreference.tenant_id == tenant.id)
    if active_only:
        stmt = stmt.where(TimetableTeacherSchedulingPreference.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(TimetableTeacherSchedulingPreference.created_at.desc()))).scalars().all()
    return [_preference_payload(item) for item in rows]


@router.post("/preferences", summary="Create teacher scheduling preference")
async def create_teacher_preference(
    body: TeacherPreferenceCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.preference_type not in PREFERENCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported preference_type.")
    if body.strength not in PREFERENCE_STRENGTHS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported strength.")

    _validate_date_range(body.effective_start_date, body.effective_end_date)
    _validate_weekdays(body.weekdays)
    _validate_period_numbers(body.period_numbers)

    await _require_active_context(
        db=db,
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
    )

    teacher = await db.scalar(select(Teacher).where(Teacher.id == body.teacher_id, Teacher.tenant_id == tenant.id))
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Teacher not found in tenant scope.")

    item = TimetableTeacherSchedulingPreference(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        teacher_id=body.teacher_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
        preference_type=body.preference_type,
        strength=body.strength,
        weekdays_json=body.weekdays,
        period_numbers_json=body.period_numbers,
        effective_start_date=body.effective_start_date,
        effective_end_date=body.effective_end_date,
        temporary_accommodation_text=body.temporary_accommodation_text,
        leadership_note=body.leadership_note,
        source_type=body.source_type,
        provenance_json=body.provenance,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(item)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.preference.added",
        entity_type="TimetableTeacherSchedulingPreference",
        entity_id=item.id,
        actor_id=actor.id,
        details={"strength": item.strength, "preference_type": item.preference_type, "is_hard": item.strength == "hard"},
    )
    await db.commit()
    await db.refresh(item)
    return _preference_payload(item)


@router.get("/preferences/{preference_id}", summary="Get one teacher scheduling preference")
async def get_teacher_preference(
    preference_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableTeacherSchedulingPreference).where(
            TimetableTeacherSchedulingPreference.id == preference_id,
            TimetableTeacherSchedulingPreference.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher scheduling preference not found.")
    return _preference_payload(item)


@router.patch("/preferences/{preference_id}", summary="Update teacher scheduling preference")
async def patch_teacher_preference(
    preference_id: uuid.UUID,
    body: TeacherPreferencePatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableTeacherSchedulingPreference).where(
            TimetableTeacherSchedulingPreference.id == preference_id,
            TimetableTeacherSchedulingPreference.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher scheduling preference not found.")

    if body.preference_type is not None:
        if body.preference_type not in PREFERENCE_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported preference_type.")
        item.preference_type = body.preference_type
    if body.strength is not None:
        if body.strength not in PREFERENCE_STRENGTHS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported strength.")
        item.strength = body.strength
    if body.weekdays is not None:
        _validate_weekdays(body.weekdays)
        item.weekdays_json = body.weekdays
    if body.period_numbers is not None:
        _validate_period_numbers(body.period_numbers)
        item.period_numbers_json = body.period_numbers
    if body.effective_start_date is not None:
        item.effective_start_date = body.effective_start_date
    if body.effective_end_date is not None:
        item.effective_end_date = body.effective_end_date
    _validate_date_range(item.effective_start_date, item.effective_end_date)
    if body.temporary_accommodation_text is not None:
        item.temporary_accommodation_text = body.temporary_accommodation_text
    if body.leadership_note is not None:
        item.leadership_note = body.leadership_note
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.preference.changed",
        entity_type="TimetableTeacherSchedulingPreference",
        entity_id=item.id,
        actor_id=actor.id,
        details={"strength": item.strength, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _preference_payload(item)


@router.post("/preferences/{preference_id}/deactivate", summary="Deactivate teacher scheduling preference")
async def deactivate_teacher_preference(
    preference_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableTeacherSchedulingPreference).where(
            TimetableTeacherSchedulingPreference.id == preference_id,
            TimetableTeacherSchedulingPreference.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher scheduling preference not found.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.preference.deactivated",
        entity_type="TimetableTeacherSchedulingPreference",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _preference_payload(item)


@router.get("/configurations/{configuration_id}/overrides", summary="List generation overrides")
async def list_generation_overrides(
    configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")

    rows = (
        await db.execute(
            select(TimetableGenerationOverride)
            .where(
                TimetableGenerationOverride.tenant_id == tenant.id,
                TimetableGenerationOverride.configuration_id == configuration_id,
            )
            .order_by(TimetableGenerationOverride.created_at.asc())
        )
    ).scalars().all()
    return [_override_payload(item) for item in rows]


@router.post("/configurations/{configuration_id}/overrides", summary="Create generation override")
async def create_generation_override(
    configuration_id: uuid.UUID,
    body: GenerationOverrideCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.override_type not in OVERRIDE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported override_type.")
    if body.strength not in PREFERENCE_STRENGTHS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported strength.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Overrides can only be changed while configuration is draft.")

    await _resolve_scope_reference(
        db=db,
        tenant_id=tenant.id,
        scope_type=body.scope_type,
        scope_reference_id=body.scope_reference_id,
        scope_reference_code=body.scope_reference_code,
    )

    item = TimetableGenerationOverride(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        configuration_id=configuration_id,
        override_type=body.override_type,
        strength=body.strength,
        scope_type=body.scope_type,
        scope_reference_id=body.scope_reference_id,
        scope_reference_code=body.scope_reference_code,
        payload_json=body.payload,
        source_type=body.source_type,
        provenance_json=body.provenance,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(item)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.override.added",
        entity_type="TimetableGenerationOverride",
        entity_id=item.id,
        actor_id=actor.id,
        details={"override_type": item.override_type, "strength": item.strength},
    )
    await db.commit()
    await db.refresh(item)
    return _override_payload(item)


@router.patch("/overrides/{override_id}", summary="Update generation override")
async def patch_generation_override(
    override_id: uuid.UUID,
    body: GenerationOverridePatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationOverride).where(
            TimetableGenerationOverride.id == override_id,
            TimetableGenerationOverride.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation override not found.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == item.configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Overrides can only be changed while configuration is draft.")

    if body.strength is not None:
        if body.strength not in PREFERENCE_STRENGTHS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported strength.")
        item.strength = body.strength

    effective_scope_type = body.scope_type if body.scope_type is not None else item.scope_type
    effective_scope_reference_id = body.scope_reference_id if body.scope_reference_id is not None else item.scope_reference_id
    effective_scope_reference_code = body.scope_reference_code if body.scope_reference_code is not None else item.scope_reference_code

    if body.scope_type is not None or body.scope_reference_id is not None or body.scope_reference_code is not None:
        await _resolve_scope_reference(
            db=db,
            tenant_id=tenant.id,
            scope_type=effective_scope_type,
            scope_reference_id=effective_scope_reference_id,
            scope_reference_code=effective_scope_reference_code,
        )
        item.scope_type = effective_scope_type
        item.scope_reference_id = effective_scope_reference_id
        item.scope_reference_code = effective_scope_reference_code

    if body.payload is not None:
        item.payload_json = body.payload
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.override.changed",
        entity_type="TimetableGenerationOverride",
        entity_id=item.id,
        actor_id=actor.id,
        details={"scope_type": item.scope_type, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _override_payload(item)


@router.post("/overrides/{override_id}/remove", summary="Deactivate generation override")
async def remove_generation_override(
    override_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationOverride).where(
            TimetableGenerationOverride.id == override_id,
            TimetableGenerationOverride.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation override not found.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == item.configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Overrides can only be changed while configuration is draft.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.override.removed",
        entity_type="TimetableGenerationOverride",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _override_payload(item)


@router.get("/configurations/{configuration_id}/locks", summary="List generation locks")
async def list_generation_locks(
    configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")

    rows = (
        await db.execute(
            select(TimetableGenerationLock)
            .where(
                TimetableGenerationLock.tenant_id == tenant.id,
                TimetableGenerationLock.configuration_id == configuration_id,
            )
            .order_by(TimetableGenerationLock.created_at.asc())
        )
    ).scalars().all()
    return [_lock_payload(item) for item in rows]


@router.post("/configurations/{configuration_id}/locks", summary="Create generation lock")
async def create_generation_lock(
    configuration_id: uuid.UUID,
    body: GenerationLockCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.lock_state not in LOCK_STATES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported lock_state.")
    if body.target_type not in LOCK_TARGET_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported target_type.")
    if body.source_type not in {"manual", "imported", "agent_proposal", "system_generated"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported source_type.")

    if body.day_of_week is not None and (body.day_of_week < 0 or body.day_of_week > 6):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="day_of_week must be between 0 and 6.")
    if body.period_number is not None and body.period_number <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_number must be positive.")
    if body.period_end_number is not None and body.period_number is not None and body.period_end_number < body.period_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_end_number cannot be before period_number.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Locks can only be changed while configuration is draft.")

    await _resolve_scope_reference(
        db=db,
        tenant_id=tenant.id,
        scope_type=body.target_type if body.target_type != "session_reference" else "session_reference",
        scope_reference_id=body.target_reference_id,
        scope_reference_code=body.target_reference_code,
    )

    item = TimetableGenerationLock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        configuration_id=configuration_id,
        lock_state=body.lock_state,
        target_type=body.target_type,
        target_reference_id=body.target_reference_id,
        target_reference_code=body.target_reference_code,
        day_of_week=body.day_of_week,
        period_number=body.period_number,
        period_end_number=body.period_end_number,
        is_manual_hard_lock=body.is_manual_hard_lock,
        source_type=body.source_type,
        provenance_json=body.provenance,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(item)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.lock.added",
        entity_type="TimetableGenerationLock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lock_state": item.lock_state, "is_manual_hard_lock": item.is_manual_hard_lock},
    )
    await db.commit()
    await db.refresh(item)
    return _lock_payload(item)


@router.patch("/locks/{lock_id}", summary="Update generation lock")
async def patch_generation_lock(
    lock_id: uuid.UUID,
    body: GenerationLockPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationLock).where(
            TimetableGenerationLock.id == lock_id,
            TimetableGenerationLock.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation lock not found.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == item.configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Locks can only be changed while configuration is draft.")

    if body.lock_state is not None:
        if body.lock_state not in LOCK_STATES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported lock_state.")
        item.lock_state = body.lock_state

    effective_target_type = body.target_type if body.target_type is not None else item.target_type
    effective_target_reference_id = body.target_reference_id if body.target_reference_id is not None else item.target_reference_id
    effective_target_reference_code = body.target_reference_code if body.target_reference_code is not None else item.target_reference_code

    if body.target_type is not None or body.target_reference_id is not None or body.target_reference_code is not None:
        await _resolve_scope_reference(
            db=db,
            tenant_id=tenant.id,
            scope_type=effective_target_type,
            scope_reference_id=effective_target_reference_id,
            scope_reference_code=effective_target_reference_code,
        )
        item.target_type = effective_target_type
        item.target_reference_id = effective_target_reference_id
        item.target_reference_code = effective_target_reference_code

    if body.day_of_week is not None:
        if body.day_of_week < 0 or body.day_of_week > 6:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="day_of_week must be between 0 and 6.")
        item.day_of_week = body.day_of_week
    if body.period_number is not None:
        if body.period_number <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_number must be positive.")
        item.period_number = body.period_number
    if body.period_end_number is not None:
        if item.period_number is not None and body.period_end_number < item.period_number:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_end_number cannot be before period_number.")
        item.period_end_number = body.period_end_number
    if body.is_manual_hard_lock is not None:
        item.is_manual_hard_lock = body.is_manual_hard_lock
    if body.is_active is not None:
        item.is_active = body.is_active

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.lock.changed",
        entity_type="TimetableGenerationLock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lock_state": item.lock_state, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _lock_payload(item)


@router.post("/locks/{lock_id}/remove", summary="Deactivate generation lock")
async def remove_generation_lock(
    lock_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableGenerationLock).where(
            TimetableGenerationLock.id == lock_id,
            TimetableGenerationLock.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation lock not found.")

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == item.configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")
    if config.lifecycle_status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Locks can only be changed while configuration is draft.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.lock.removed",
        entity_type="TimetableGenerationLock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)
    return _lock_payload(item)


async def _validate_parallel_child(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    term_id: uuid.UUID,
    child: ParallelLessonChildInput,
) -> None:
    if child.requirement_id is None and child.subject_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Each child requires requirement_id or subject_id.")

    if child.requirement_id is not None:
        req = await db.scalar(
            select(WeeklyTeachingRequirement).where(
                WeeklyTeachingRequirement.id == child.requirement_id,
                WeeklyTeachingRequirement.tenant_id == tenant_id,
                WeeklyTeachingRequirement.is_active.is_(True),
            )
        )
        if req is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parallel child requirement not found in tenant scope.")
        if req.class_id != class_id or req.academic_year_id != academic_year_id or req.term_id != term_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parallel child requirement must match block class and context.")

    if child.subject_id is not None:
        subject = await db.scalar(select(Subject).where(Subject.id == child.subject_id, Subject.tenant_id == tenant_id))
        if subject is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parallel child subject not found in tenant scope.")

    if child.teacher_id is not None:
        teacher = await db.scalar(select(Teacher).where(Teacher.id == child.teacher_id, Teacher.tenant_id == tenant_id))
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parallel child teacher not found in tenant scope.")

    if child.room_id is not None:
        room = await db.scalar(select(TeachingRoom).where(TeachingRoom.id == child.room_id, TeachingRoom.tenant_id == tenant_id, TeachingRoom.is_active.is_(True)))
        if room is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Parallel child room not found in tenant scope.")


async def _replace_parallel_children(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    block_id: uuid.UUID,
    class_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    term_id: uuid.UUID,
    children: list[ParallelLessonChildInput],
) -> list[TimetableParallelLessonChild]:
    existing = (
        await db.execute(
            select(TimetableParallelLessonChild).where(
                TimetableParallelLessonChild.tenant_id == tenant_id,
                TimetableParallelLessonChild.parallel_block_id == block_id,
            )
        )
    ).scalars().all()
    for row in existing:
        await db.delete(row)

    inserted: list[TimetableParallelLessonChild] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for child in children:
        await _validate_parallel_child(
            db=db,
            tenant_id=tenant_id,
            class_id=class_id,
            academic_year_id=academic_year_id,
            term_id=term_id,
            child=child,
        )
        key = (
            str(child.requirement_id) if child.requirement_id else None,
            str(child.subject_id) if child.subject_id else None,
            str(child.teacher_id) if child.teacher_id else None,
        )
        if key in seen:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Duplicate malformed parallel child is not allowed.")
        seen.add(key)

        row = TimetableParallelLessonChild(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            parallel_block_id=block_id,
            requirement_id=child.requirement_id,
            subject_id=child.subject_id,
            teacher_id=child.teacher_id,
            room_id=child.room_id,
            sequence_order=child.sequence_order,
            requirement_json=child.requirement,
            is_active=True,
        )
        db.add(row)
        inserted.append(row)

    return inserted


@router.get("/parallel-blocks", summary="List parallel lesson blocks")
async def list_parallel_blocks(
    active_only: bool = Query(default=True),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(TimetableParallelLessonBlock).where(TimetableParallelLessonBlock.tenant_id == tenant.id)
    if active_only:
        stmt = stmt.where(TimetableParallelLessonBlock.is_active.is_(True))
    blocks = (await db.execute(stmt.order_by(TimetableParallelLessonBlock.created_at.desc()))).scalars().all()

    payload: list[dict[str, Any]] = []
    for item in blocks:
        children = (
            await db.execute(
                select(TimetableParallelLessonChild).where(
                    TimetableParallelLessonChild.tenant_id == tenant.id,
                    TimetableParallelLessonChild.parallel_block_id == item.id,
                    TimetableParallelLessonChild.is_active.is_(True),
                )
            )
        ).scalars().all()
        payload.append(_parallel_block_payload(item, children))
    return payload


@router.post("/parallel-blocks", summary="Create parallel lesson block")
async def create_parallel_block(
    body: ParallelLessonBlockCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.block_type not in PARALLEL_BLOCK_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported block_type.")
    if body.synchronization_requirement not in {"same_period", "same_day"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported synchronization_requirement.")

    await _require_active_context(
        db=db,
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
    )

    class_row = await db.scalar(select(Class).where(Class.id == body.class_id, Class.tenant_id == tenant.id))
    if class_row is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class not found in tenant scope.")

    item = TimetableParallelLessonBlock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
        class_id=body.class_id,
        display_label=_clean_required_text(body.display_label, label="display_label"),
        block_type=body.block_type,
        synchronization_requirement=body.synchronization_requirement,
        source_type=body.source_type,
        provenance_json=body.provenance,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(item)
    await db.flush()

    children = await _replace_parallel_children(
        db=db,
        tenant_id=tenant.id,
        block_id=item.id,
        class_id=body.class_id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        children=body.children,
    )

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.parallel_block.changed",
        entity_type="TimetableParallelLessonBlock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"block_type": item.block_type, "child_count": len(children)},
    )
    await db.commit()
    await db.refresh(item)
    return _parallel_block_payload(item, children)


@router.get("/parallel-blocks/{block_id}", summary="Get one parallel lesson block")
async def get_parallel_block(
    block_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableParallelLessonBlock).where(
            TimetableParallelLessonBlock.id == block_id,
            TimetableParallelLessonBlock.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parallel lesson block not found.")

    children = (
        await db.execute(
            select(TimetableParallelLessonChild).where(
                TimetableParallelLessonChild.tenant_id == tenant.id,
                TimetableParallelLessonChild.parallel_block_id == block_id,
                TimetableParallelLessonChild.is_active.is_(True),
            )
        )
    ).scalars().all()
    return _parallel_block_payload(item, children)


@router.patch("/parallel-blocks/{block_id}", summary="Update parallel lesson block")
async def patch_parallel_block(
    block_id: uuid.UUID,
    body: ParallelLessonBlockPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableParallelLessonBlock).where(
            TimetableParallelLessonBlock.id == block_id,
            TimetableParallelLessonBlock.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parallel lesson block not found.")

    if body.display_label is not None:
        item.display_label = _clean_required_text(body.display_label, label="display_label")
    if body.block_type is not None:
        if body.block_type not in PARALLEL_BLOCK_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported block_type.")
        item.block_type = body.block_type
    if body.synchronization_requirement is not None:
        if body.synchronization_requirement not in {"same_period", "same_day"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported synchronization_requirement.")
        item.synchronization_requirement = body.synchronization_requirement
    if body.is_active is not None:
        item.is_active = body.is_active

    if body.children is not None:
        await _replace_parallel_children(
            db=db,
            tenant_id=tenant.id,
            block_id=item.id,
            class_id=item.class_id,
            academic_year_id=item.academic_year_id,
            term_id=item.term_id,
            children=body.children,
        )

    children = (
        await db.execute(
            select(TimetableParallelLessonChild).where(
                TimetableParallelLessonChild.tenant_id == tenant.id,
                TimetableParallelLessonChild.parallel_block_id == item.id,
                TimetableParallelLessonChild.is_active.is_(True),
            )
        )
    ).scalars().all()

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.parallel_block.changed",
        entity_type="TimetableParallelLessonBlock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"block_type": item.block_type, "is_active": item.is_active},
    )
    await db.commit()
    await db.refresh(item)
    return _parallel_block_payload(item, children)


@router.post("/parallel-blocks/{block_id}/deactivate", summary="Deactivate parallel lesson block")
async def deactivate_parallel_block(
    block_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(
        select(TimetableParallelLessonBlock).where(
            TimetableParallelLessonBlock.id == block_id,
            TimetableParallelLessonBlock.tenant_id == tenant.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parallel lesson block not found.")

    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_generation.parallel_block.changed",
        entity_type="TimetableParallelLessonBlock",
        entity_id=item.id,
        actor_id=actor.id,
        details={"is_active": False},
    )
    await db.commit()
    await db.refresh(item)

    children = (
        await db.execute(
            select(TimetableParallelLessonChild).where(
                TimetableParallelLessonChild.tenant_id == tenant.id,
                TimetableParallelLessonChild.parallel_block_id == item.id,
                TimetableParallelLessonChild.is_active.is_(True),
            )
        )
    ).scalars().all()
    return _parallel_block_payload(item, children)


@router.get("/configurations/{configuration_id}/summary", summary="Get generation configuration summary")
async def generation_configuration_summary(
    configuration_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    config = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant.id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation configuration not found.")

    validation_summary = await _run_generation_validation(db=db, tenant=tenant, config=config)

    preference_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TimetableTeacherSchedulingPreference)
            .where(
                TimetableTeacherSchedulingPreference.tenant_id == tenant.id,
                TimetableTeacherSchedulingPreference.academic_year_id == config.academic_year_id,
                TimetableTeacherSchedulingPreference.term_id == config.term_id,
                TimetableTeacherSchedulingPreference.is_active.is_(True),
            )
        )
        or 0
    )

    hard_preference_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TimetableTeacherSchedulingPreference)
            .where(
                TimetableTeacherSchedulingPreference.tenant_id == tenant.id,
                TimetableTeacherSchedulingPreference.academic_year_id == config.academic_year_id,
                TimetableTeacherSchedulingPreference.term_id == config.term_id,
                TimetableTeacherSchedulingPreference.is_active.is_(True),
                TimetableTeacherSchedulingPreference.strength == "hard",
            )
        )
        or 0
    )

    override_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TimetableGenerationOverride)
            .where(
                TimetableGenerationOverride.tenant_id == tenant.id,
                TimetableGenerationOverride.configuration_id == config.id,
                TimetableGenerationOverride.is_active.is_(True),
            )
        )
        or 0
    )

    lock_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TimetableGenerationLock)
            .where(
                TimetableGenerationLock.tenant_id == tenant.id,
                TimetableGenerationLock.configuration_id == config.id,
                TimetableGenerationLock.is_active.is_(True),
            )
        )
        or 0
    )

    parallel_block_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TimetableParallelLessonBlock)
            .where(
                TimetableParallelLessonBlock.tenant_id == tenant.id,
                TimetableParallelLessonBlock.academic_year_id == config.academic_year_id,
                TimetableParallelLessonBlock.term_id == config.term_id,
                TimetableParallelLessonBlock.is_active.is_(True),
            )
        )
        or 0
    )

    return {
        "configuration": _configuration_payload(config),
        "validation": validation_summary,
        "policy_readiness_generation_allowed": validation_summary.get("policy_generation_allowed", False),
        "preference_count": preference_count,
        "hard_preference_count": hard_preference_count,
        "override_count": override_count,
        "lock_count": lock_count,
        "parallel_block_count": parallel_block_count,
        "repair_settings": config.repair_scope_json,
        "future_solver_eligibility": bool(config.lifecycle_status == "approved" and validation_summary.get("is_valid") and validation_summary.get("policy_generation_allowed")),
        "explicit_non_actions": {
            "solver_started": False,
            "candidate_generated": False,
            "timetable_published": False,
        },
    }
