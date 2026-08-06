from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.policy_registry import (
    CONSTRAINT_CATEGORIES,
    ENFORCEMENT_LEVELS,
    LIFECYCLE_STATUSES,
    SCOPE_TYPES,
    SOURCE_TYPES,
    get_constraint_type_or_none,
    list_constraint_types,
    validate_constraint_parameters,
)
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    BellSchedulePeriod,
    Campus,
    Class,
    Subject,
    Teacher,
    TeachingRoom,
    Tenant,
    Term,
    TimetablePolicyConstraint,
    TimetablePolicyConstraintVersion,
    TimetablePolicyException,
    TimetablePolicySet,
    TimetablePolicySetVersion,
    User,
)


router = APIRouter(prefix="/leadership/timetable-policies", tags=["Timetable Policies"])


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


class PolicySetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None
    source_type: str = "manual"


class PolicySetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None


class ConstraintCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_type: str
    category: str
    enforcement_level: str
    scope_type: str
    scope_reference_id: uuid.UUID | None = None
    scope_reference_code: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    weight: float | None = None
    priority: int | None = None
    explanation: str | None = None
    source_type: str = "manual"
    confidence_score: int | None = None
    requires_approval: bool | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None


class ConstraintPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enforcement_level: str | None = None
    scope_type: str | None = None
    scope_reference_id: uuid.UUID | None = None
    scope_reference_code: str | None = None
    parameters: dict[str, Any] | None = None
    weight: float | None = None
    priority: int | None = None
    explanation: str | None = None
    effective_start_date: date_type | None = None
    effective_end_date: date_type | None = None


class PolicyExceptionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_set_id: uuid.UUID | None = None
    constraint_id: uuid.UUID | None = None
    scope_type: str
    scope_reference_id: uuid.UUID | None = None
    scope_reference_code: str | None = None
    reason: str
    start_date: date_type | None = None
    end_date: date_type | None = None
    expires_at: datetime | None = None


class LifecycleReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _validate_date_range(start_date: date_type | None, end_date: date_type | None) -> None:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="effective_end_date cannot be before effective_start_date.")


async def _resolve_scope_keys_for_policy_set(
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


async def _validate_constraint_scope_reference(
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

    if scope_type in {"department", "grade"}:
        if not (scope_reference_code or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{scope_type} scope requires scope_reference_code.")
        return

    if scope_reference_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{scope_type} scope requires scope_reference_id.")

    model_lookup = {
        "campus": Campus,
        "class": Class,
        "subject": Subject,
        "teacher": Teacher,
        "room": TeachingRoom,
        "period": BellSchedulePeriod,
        "policy_set": TimetablePolicySet,
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


async def _validate_constraint_request(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    body: ConstraintCreateRequest | ConstraintPatchRequest,
    existing_policy_set_id: uuid.UUID,
    effective_enforcement: str,
    effective_scope_type: str,
    effective_scope_reference_id: uuid.UUID | None,
    effective_scope_reference_code: str | None,
    effective_parameters: dict[str, Any],
    effective_category: str,
    effective_constraint_type: str,
    effective_weight: float,
    effective_priority: int,
) -> None:
    if effective_category not in CONSTRAINT_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported category.")
    if effective_enforcement not in ENFORCEMENT_LEVELS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported enforcement_level.")
    if effective_weight <= 0 or effective_weight > 1000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="weight must be > 0 and <= 1000.")
    if effective_priority <= 0 or effective_priority > 1000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="priority must be > 0 and <= 1000.")

    definition = get_constraint_type_or_none(effective_constraint_type)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported constraint_type.")

    if definition["category"] != effective_category:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Constraint category is incompatible with constraint_type.")

    if effective_enforcement not in definition["allowed_enforcement_levels"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enforcement level is incompatible with constraint_type.")

    if effective_scope_type not in definition["supported_scopes"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Scope type is incompatible with constraint_type.")

    await _validate_constraint_scope_reference(
        db=db,
        tenant_id=tenant_id,
        scope_type=effective_scope_type,
        scope_reference_id=effective_scope_reference_id,
        scope_reference_code=effective_scope_reference_code,
    )

    parameter_errors = validate_constraint_parameters(definition, effective_parameters)
    if parameter_errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": "Invalid constraint parameters.", "errors": parameter_errors})

    duplicate = await db.scalar(
        select(TimetablePolicyConstraint.id).where(
            TimetablePolicyConstraint.tenant_id == tenant_id,
            TimetablePolicyConstraint.policy_set_id == existing_policy_set_id,
            TimetablePolicyConstraint.constraint_type == effective_constraint_type,
            TimetablePolicyConstraint.scope_type == effective_scope_type,
            TimetablePolicyConstraint.scope_reference_id == effective_scope_reference_id,
            TimetablePolicyConstraint.scope_reference_code == effective_scope_reference_code,
            TimetablePolicyConstraint.enforcement_level == effective_enforcement,
            TimetablePolicyConstraint.parameters_json == effective_parameters,
            TimetablePolicyConstraint.is_active.is_(True),
            TimetablePolicyConstraint.lifecycle_status.in_(["draft", "pending_review", "approved", "active"]),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate active constraint already exists for the same scope and parameters.")


def _policy_set_payload(item: TimetablePolicySet) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": str(item.campus_id) if item.campus_id else None,
        "name": item.name,
        "description": item.description,
        "lifecycle_status": item.lifecycle_status,
        "version_number": item.version_number,
        "is_active": item.is_active,
        "effective_start_date": item.effective_start_date,
        "effective_end_date": item.effective_end_date,
        "source_type": item.source_type,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "approved_by_user_id": str(item.approved_by_user_id) if item.approved_by_user_id else None,
        "approved_at": item.approved_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _constraint_payload(item: TimetablePolicyConstraint) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "policy_set_id": str(item.policy_set_id),
        "constraint_type": item.constraint_type,
        "category": item.category,
        "enforcement_level": item.enforcement_level,
        "lifecycle_status": item.lifecycle_status,
        "scope_type": item.scope_type,
        "scope_reference_id": str(item.scope_reference_id) if item.scope_reference_id else None,
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
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "approved_by_user_id": str(item.approved_by_user_id) if item.approved_by_user_id else None,
        "approved_at": item.approved_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _exception_payload(item: TimetablePolicyException) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "policy_set_id": str(item.policy_set_id) if item.policy_set_id else None,
        "constraint_id": str(item.constraint_id) if item.constraint_id else None,
        "scope_type": item.scope_type,
        "scope_reference_id": str(item.scope_reference_id) if item.scope_reference_id else None,
        "scope_reference_code": item.scope_reference_code,
        "reason": item.reason,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "approval_state": item.approval_state,
        "requested_by_user_id": str(item.requested_by_user_id) if item.requested_by_user_id else None,
        "approved_by_user_id": str(item.approved_by_user_id) if item.approved_by_user_id else None,
        "approved_at": item.approved_at,
        "expires_at": item.expires_at,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _append_policy_version(
    *,
    db: AsyncSession,
    policy_set: TimetablePolicySet,
    actor: User,
    change_type: str,
    reason: str | None,
    previous_values: dict[str, Any],
    approval_actor_user_id: uuid.UUID | None = None,
) -> None:
    db.add(
        TimetablePolicySetVersion(
            id=uuid.uuid4(),
            tenant_id=policy_set.tenant_id,
            policy_set_id=policy_set.id,
            version_number=policy_set.version_number,
            change_type=change_type,
            reason=reason,
            previous_values=previous_values,
            new_values=_policy_set_payload(policy_set),
            actor_user_id=actor.id,
            approval_actor_user_id=approval_actor_user_id,
        )
    )


async def _append_constraint_version(
    *,
    db: AsyncSession,
    constraint: TimetablePolicyConstraint,
    actor: User,
    change_type: str,
    reason: str | None,
    previous_values: dict[str, Any],
    approval_actor_user_id: uuid.UUID | None = None,
) -> None:
    db.add(
        TimetablePolicyConstraintVersion(
            id=uuid.uuid4(),
            tenant_id=constraint.tenant_id,
            constraint_id=constraint.id,
            version_number=constraint.version_number,
            change_type=change_type,
            reason=reason,
            previous_values=previous_values,
            new_values=_constraint_payload(constraint),
            actor_user_id=actor.id,
            approval_actor_user_id=approval_actor_user_id,
        )
    )


def _assert_transition(current: str, *, allowed: set[str], action: str) -> None:
    if current not in allowed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot {action} while lifecycle_status is '{current}'.")


@router.get("/policy-sets", summary="List timetable policy sets")
async def list_policy_sets(
    lifecycle_status: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(TimetablePolicySet).where(TimetablePolicySet.tenant_id == tenant.id).order_by(TimetablePolicySet.created_at.desc())
    if lifecycle_status is not None:
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported lifecycle_status.")
        stmt = stmt.where(TimetablePolicySet.lifecycle_status == lifecycle_status)
    rows = (await db.execute(stmt)).scalars().all()
    return [_policy_set_payload(item) for item in rows]


@router.post("/policy-sets", summary="Create timetable policy set draft")
async def create_policy_set(
    body: PolicySetCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported source_type.")
    _validate_date_range(body.effective_start_date, body.effective_end_date)
    await _resolve_scope_keys_for_policy_set(
        db=db,
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
    )

    item = TimetablePolicySet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=body.academic_year_id,
        term_id=body.term_id,
        campus_id=body.campus_id,
        name=_clean_required_text(body.name, label="name"),
        description=body.description,
        lifecycle_status="draft",
        version_number=1,
        is_active=False,
        effective_start_date=body.effective_start_date,
        effective_end_date=body.effective_end_date,
        source_type=body.source_type,
        created_by_user_id=actor.id,
    )
    db.add(item)
    await _append_policy_version(
        db=db,
        policy_set=item,
        actor=actor,
        change_type="created",
        reason="initial draft",
        previous_values={},
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.policy_set.created",
        entity_type="TimetablePolicySet",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lifecycle_status": item.lifecycle_status, "source_type": item.source_type},
    )
    await db.commit()
    await db.refresh(item)
    return _policy_set_payload(item)


@router.get("/policy-sets/{policy_set_id}", summary="Get timetable policy set")
async def get_policy_set(
    policy_set_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy set not found.")
    return _policy_set_payload(item)


@router.patch("/policy-sets/{policy_set_id}", summary="Edit timetable policy set")
async def patch_policy_set(
    policy_set_id: uuid.UUID,
    body: PolicySetPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy set not found.")
    if item.lifecycle_status in {"retired"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Retired policy sets cannot be edited.")

    prev = _policy_set_payload(item)
    if body.name is not None:
        item.name = _clean_required_text(body.name, label="name")
    if body.description is not None:
        item.description = body.description
    if body.effective_start_date is not None:
        item.effective_start_date = body.effective_start_date
    if body.effective_end_date is not None:
        item.effective_end_date = body.effective_end_date
    _validate_date_range(item.effective_start_date, item.effective_end_date)

    item.version_number += 1
    await _append_policy_version(db=db, policy_set=item, actor=actor, change_type="edited", reason="manual update", previous_values=prev)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.policy_set.changed",
        entity_type="TimetablePolicySet",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lifecycle_status": item.lifecycle_status},
    )
    await db.commit()
    await db.refresh(item)
    return _policy_set_payload(item)


async def _policy_set_lifecycle(
    *,
    db: AsyncSession,
    tenant: Tenant,
    actor: User,
    policy_set_id: uuid.UUID,
    action: str,
    reason: str | None,
) -> dict[str, Any]:
    item = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy set not found.")

    prev = _policy_set_payload(item)

    if action == "submit":
        _assert_transition(item.lifecycle_status, allowed={"draft"}, action=action)
        item.lifecycle_status = "pending_review"
        change_type = "submitted"
    elif action == "approve":
        _assert_transition(item.lifecycle_status, allowed={"pending_review"}, action=action)
        item.lifecycle_status = "approved"
        item.approved_by_user_id = actor.id
        item.approved_at = _now()
        change_type = "approved"
    elif action == "activate":
        _assert_transition(item.lifecycle_status, allowed={"approved", "suspended"}, action=action)
        existing = await db.scalar(
            select(TimetablePolicySet.id).where(
                TimetablePolicySet.tenant_id == tenant.id,
                TimetablePolicySet.id != item.id,
                TimetablePolicySet.academic_year_id == item.academic_year_id,
                TimetablePolicySet.term_id == item.term_id,
                TimetablePolicySet.campus_id == item.campus_id,
                TimetablePolicySet.is_active.is_(True),
                TimetablePolicySet.lifecycle_status == "active",
            )
        )
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another active policy set already exists for the same scope.")
        item.lifecycle_status = "active"
        item.is_active = True
        change_type = "activated"
    elif action == "suspend":
        _assert_transition(item.lifecycle_status, allowed={"active"}, action=action)
        item.lifecycle_status = "suspended"
        item.is_active = False
        change_type = "suspended"
    elif action == "retire":
        _assert_transition(item.lifecycle_status, allowed={"approved", "active", "suspended"}, action=action)
        item.lifecycle_status = "retired"
        item.is_active = False
        change_type = "retired"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported lifecycle action.")

    item.version_number += 1
    await _append_policy_version(
        db=db,
        policy_set=item,
        actor=actor,
        change_type=change_type,
        reason=reason,
        previous_values=prev,
        approval_actor_user_id=actor.id if action in {"approve", "activate"} else None,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=f"timetable_policy.policy_set.{change_type}",
        entity_type="TimetablePolicySet",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": reason},
    )
    await db.commit()
    await db.refresh(item)
    return _policy_set_payload(item)


@router.post("/policy-sets/{policy_set_id}/submit", summary="Submit policy set for review")
async def submit_policy_set(
    policy_set_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy_set_id, action="submit", reason=body.reason)


@router.post("/policy-sets/{policy_set_id}/approve", summary="Approve policy set")
async def approve_policy_set(
    policy_set_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy_set_id, action="approve", reason=body.reason)


@router.post("/policy-sets/{policy_set_id}/activate", summary="Activate policy set")
async def activate_policy_set(
    policy_set_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy_set_id, action="activate", reason=body.reason)


@router.post("/policy-sets/{policy_set_id}/suspend", summary="Suspend policy set")
async def suspend_policy_set(
    policy_set_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy_set_id, action="suspend", reason=body.reason)


@router.post("/policy-sets/{policy_set_id}/retire", summary="Retire policy set")
async def retire_policy_set(
    policy_set_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy_set_id, action="retire", reason=body.reason)


@router.get("/policy-sets/{policy_set_id}/versions", summary="List policy set versions")
async def list_policy_set_versions(
    policy_set_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    rows = (
        await db.execute(
            select(TimetablePolicySetVersion)
            .where(TimetablePolicySetVersion.tenant_id == tenant.id, TimetablePolicySetVersion.policy_set_id == policy_set_id)
            .order_by(TimetablePolicySetVersion.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(item.id),
            "policy_set_id": str(item.policy_set_id),
            "version_number": item.version_number,
            "change_type": item.change_type,
            "reason": item.reason,
            "previous_values": item.previous_values,
            "new_values": item.new_values,
            "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
            "approval_actor_user_id": str(item.approval_actor_user_id) if item.approval_actor_user_id else None,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@router.get("/policy-sets/{policy_set_id}/constraints", summary="List constraints in a policy set")
async def list_constraints(
    policy_set_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    rows = (
        await db.execute(
            select(TimetablePolicyConstraint)
            .where(TimetablePolicyConstraint.tenant_id == tenant.id, TimetablePolicyConstraint.policy_set_id == policy_set_id)
            .order_by(TimetablePolicyConstraint.created_at.asc())
        )
    ).scalars().all()
    return [_constraint_payload(item) for item in rows]


@router.post("/policy-sets/{policy_set_id}/constraints", summary="Create constraint draft")
async def create_constraint(
    policy_set_id: uuid.UUID,
    body: ConstraintCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    policy_set = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
    if policy_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy set not found.")

    definition = get_constraint_type_or_none(body.constraint_type)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported constraint_type.")

    if body.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported source_type.")
    _validate_date_range(body.effective_start_date, body.effective_end_date)

    weight_value = float(body.weight if body.weight is not None else definition["default_weight"])
    priority_value = int(body.priority if body.priority is not None else definition["default_priority"])
    requires_approval_value = bool(definition["approval_required"] if body.requires_approval is None else body.requires_approval)

    if body.confidence_score is not None and (body.confidence_score < 0 or body.confidence_score > 100):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="confidence_score must be between 0 and 100.")

    await _validate_constraint_request(
        db=db,
        tenant_id=tenant.id,
        body=body,
        existing_policy_set_id=policy_set_id,
        effective_enforcement=body.enforcement_level,
        effective_scope_type=body.scope_type,
        effective_scope_reference_id=body.scope_reference_id,
        effective_scope_reference_code=body.scope_reference_code,
        effective_parameters=body.parameters,
        effective_category=body.category,
        effective_constraint_type=body.constraint_type,
        effective_weight=weight_value,
        effective_priority=priority_value,
    )

    item = TimetablePolicyConstraint(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        policy_set_id=policy_set_id,
        constraint_type=body.constraint_type,
        category=body.category,
        enforcement_level=body.enforcement_level,
        lifecycle_status="draft",
        scope_type=body.scope_type,
        scope_reference_id=body.scope_reference_id,
        scope_reference_code=body.scope_reference_code,
        parameters_json=body.parameters,
        weight=weight_value,
        priority=priority_value,
        is_active=True,
        effective_start_date=body.effective_start_date,
        effective_end_date=body.effective_end_date,
        explanation=body.explanation,
        source_type=body.source_type,
        confidence_score=body.confidence_score,
        requires_approval=requires_approval_value,
        created_by_user_id=actor.id,
    )
    db.add(item)
    await _append_constraint_version(
        db=db,
        constraint=item,
        actor=actor,
        change_type="created",
        reason="initial draft",
        previous_values={},
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.constraint.created",
        entity_type="TimetablePolicyConstraint",
        entity_id=item.id,
        actor_id=actor.id,
        details={"constraint_type": item.constraint_type, "enforcement_level": item.enforcement_level},
    )
    await db.commit()
    await db.refresh(item)
    return _constraint_payload(item)


@router.get("/constraints/{constraint_id}", summary="Get one constraint")
async def get_constraint(
    constraint_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyConstraint).where(TimetablePolicyConstraint.id == constraint_id, TimetablePolicyConstraint.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constraint not found.")
    return _constraint_payload(item)


@router.patch("/constraints/{constraint_id}", summary="Edit constraint")
async def patch_constraint(
    constraint_id: uuid.UUID,
    body: ConstraintPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyConstraint).where(TimetablePolicyConstraint.id == constraint_id, TimetablePolicyConstraint.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constraint not found.")
    if item.lifecycle_status in {"retired"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Retired constraints cannot be edited.")

    prev = _constraint_payload(item)

    effective_enforcement = body.enforcement_level if body.enforcement_level is not None else item.enforcement_level
    effective_scope_type = body.scope_type if body.scope_type is not None else item.scope_type
    effective_scope_reference_id = body.scope_reference_id if body.scope_reference_id is not None else item.scope_reference_id
    effective_scope_reference_code = body.scope_reference_code if body.scope_reference_code is not None else item.scope_reference_code
    effective_parameters = body.parameters if body.parameters is not None else dict(item.parameters_json or {})
    effective_weight = float(body.weight if body.weight is not None else item.weight)
    effective_priority = int(body.priority if body.priority is not None else item.priority)

    await _validate_constraint_request(
        db=db,
        tenant_id=tenant.id,
        body=body,
        existing_policy_set_id=item.policy_set_id,
        effective_enforcement=effective_enforcement,
        effective_scope_type=effective_scope_type,
        effective_scope_reference_id=effective_scope_reference_id,
        effective_scope_reference_code=effective_scope_reference_code,
        effective_parameters=effective_parameters,
        effective_category=item.category,
        effective_constraint_type=item.constraint_type,
        effective_weight=effective_weight,
        effective_priority=effective_priority,
    )

    item.enforcement_level = effective_enforcement
    item.scope_type = effective_scope_type
    item.scope_reference_id = effective_scope_reference_id
    item.scope_reference_code = effective_scope_reference_code
    item.parameters_json = effective_parameters
    item.weight = effective_weight
    item.priority = effective_priority
    if body.explanation is not None:
        item.explanation = body.explanation
    if body.effective_start_date is not None:
        item.effective_start_date = body.effective_start_date
    if body.effective_end_date is not None:
        item.effective_end_date = body.effective_end_date
    _validate_date_range(item.effective_start_date, item.effective_end_date)

    item.version_number += 1
    await _append_constraint_version(db=db, constraint=item, actor=actor, change_type="edited", reason="manual update", previous_values=prev)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.constraint.changed",
        entity_type="TimetablePolicyConstraint",
        entity_id=item.id,
        actor_id=actor.id,
        details={"constraint_type": item.constraint_type},
    )
    await db.commit()
    await db.refresh(item)
    return _constraint_payload(item)


async def _constraint_lifecycle(
    *,
    db: AsyncSession,
    tenant: Tenant,
    actor: User,
    constraint_id: uuid.UUID,
    action: str,
    reason: str | None,
) -> dict[str, Any]:
    item = await db.scalar(select(TimetablePolicyConstraint).where(TimetablePolicyConstraint.id == constraint_id, TimetablePolicyConstraint.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constraint not found.")

    policy_set = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == item.policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
    if policy_set is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Constraint policy set is invalid.")

    prev = _constraint_payload(item)

    if action == "submit":
        _assert_transition(item.lifecycle_status, allowed={"draft"}, action=action)
        item.lifecycle_status = "pending_review"
        change_type = "submitted"
    elif action == "approve":
        _assert_transition(item.lifecycle_status, allowed={"pending_review"}, action=action)
        item.lifecycle_status = "approved"
        item.approved_by_user_id = actor.id
        item.approved_at = _now()
        change_type = "approved"
    elif action == "activate":
        _assert_transition(item.lifecycle_status, allowed={"approved", "suspended"}, action=action)
        if policy_set.lifecycle_status != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Policy set must be active before activating constraints.")
        item.lifecycle_status = "active"
        item.is_active = True
        change_type = "activated"
    elif action == "suspend":
        _assert_transition(item.lifecycle_status, allowed={"active"}, action=action)
        item.lifecycle_status = "suspended"
        item.is_active = False
        change_type = "suspended"
    elif action == "retire":
        _assert_transition(item.lifecycle_status, allowed={"approved", "active", "suspended"}, action=action)
        item.lifecycle_status = "retired"
        item.is_active = False
        change_type = "retired"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported lifecycle action.")

    item.version_number += 1
    await _append_constraint_version(
        db=db,
        constraint=item,
        actor=actor,
        change_type=change_type,
        reason=reason,
        previous_values=prev,
        approval_actor_user_id=actor.id if action in {"approve", "activate"} else None,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action=f"timetable_policy.constraint.{change_type}",
        entity_type="TimetablePolicyConstraint",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": reason},
    )
    await db.commit()
    await db.refresh(item)
    return _constraint_payload(item)


@router.post("/constraints/{constraint_id}/submit", summary="Submit constraint for review")
async def submit_constraint(
    constraint_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint_id, action="submit", reason=body.reason)


@router.post("/constraints/{constraint_id}/approve", summary="Approve constraint")
async def approve_constraint(
    constraint_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint_id, action="approve", reason=body.reason)


@router.post("/constraints/{constraint_id}/activate", summary="Activate constraint")
async def activate_constraint(
    constraint_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint_id, action="activate", reason=body.reason)


@router.post("/constraints/{constraint_id}/suspend", summary="Suspend constraint")
async def suspend_constraint(
    constraint_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint_id, action="suspend", reason=body.reason)


@router.post("/constraints/{constraint_id}/retire", summary="Retire constraint")
async def retire_constraint(
    constraint_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    return await _constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint_id, action="retire", reason=body.reason)


@router.get("/constraints/{constraint_id}/versions", summary="List constraint versions")
async def list_constraint_versions(
    constraint_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    rows = (
        await db.execute(
            select(TimetablePolicyConstraintVersion)
            .where(TimetablePolicyConstraintVersion.tenant_id == tenant.id, TimetablePolicyConstraintVersion.constraint_id == constraint_id)
            .order_by(TimetablePolicyConstraintVersion.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(item.id),
            "constraint_id": str(item.constraint_id),
            "version_number": item.version_number,
            "change_type": item.change_type,
            "reason": item.reason,
            "previous_values": item.previous_values,
            "new_values": item.new_values,
            "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
            "approval_actor_user_id": str(item.approval_actor_user_id) if item.approval_actor_user_id else None,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@router.get("/exceptions", summary="List policy exceptions")
async def list_exceptions(
    approval_state: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(TimetablePolicyException).where(TimetablePolicyException.tenant_id == tenant.id).order_by(TimetablePolicyException.created_at.desc())
    if approval_state is not None:
        if approval_state not in {"draft", "pending_review", "approved", "rejected", "revoked"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported approval_state.")
        stmt = stmt.where(TimetablePolicyException.approval_state == approval_state)

    rows = (await db.execute(stmt)).scalars().all()
    return [_exception_payload(item) for item in rows]


@router.post("/exceptions", summary="Create policy exception request")
async def create_exception(
    body: PolicyExceptionCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.policy_set_id is None and body.constraint_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Either policy_set_id or constraint_id is required.")
    if body.policy_set_id is not None and body.constraint_id is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provide only one of policy_set_id or constraint_id.")

    _validate_date_range(body.start_date, body.end_date)
    if body.expires_at is not None and body.expires_at <= _now():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="expires_at must be in the future.")

    await _validate_constraint_scope_reference(
        db=db,
        tenant_id=tenant.id,
        scope_type=body.scope_type,
        scope_reference_id=body.scope_reference_id,
        scope_reference_code=body.scope_reference_code,
    )

    if body.policy_set_id is not None:
        policy_set = await db.scalar(select(TimetablePolicySet).where(TimetablePolicySet.id == body.policy_set_id, TimetablePolicySet.tenant_id == tenant.id))
        if policy_set is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="policy_set_id is outside tenant scope.")

    if body.constraint_id is not None:
        constraint = await db.scalar(select(TimetablePolicyConstraint).where(TimetablePolicyConstraint.id == body.constraint_id, TimetablePolicyConstraint.tenant_id == tenant.id))
        if constraint is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="constraint_id is outside tenant scope.")

    item = TimetablePolicyException(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        policy_set_id=body.policy_set_id,
        constraint_id=body.constraint_id,
        scope_type=body.scope_type,
        scope_reference_id=body.scope_reference_id,
        scope_reference_code=body.scope_reference_code,
        reason=_clean_required_text(body.reason, label="reason"),
        start_date=body.start_date,
        end_date=body.end_date,
        approval_state="draft",
        requested_by_user_id=actor.id,
        expires_at=body.expires_at,
        is_active=True,
    )
    db.add(item)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.exception.requested",
        entity_type="TimetablePolicyException",
        entity_id=item.id,
        actor_id=actor.id,
        details={"scope_type": item.scope_type},
    )
    await db.commit()
    await db.refresh(item)
    return _exception_payload(item)


@router.get("/exceptions/{exception_id}", summary="Get policy exception")
async def get_exception(
    exception_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyException).where(TimetablePolicyException.id == exception_id, TimetablePolicyException.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")
    return _exception_payload(item)


@router.post("/exceptions/{exception_id}/submit", summary="Submit exception request")
async def submit_exception(
    exception_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyException).where(TimetablePolicyException.id == exception_id, TimetablePolicyException.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")
    _assert_transition(item.approval_state, allowed={"draft"}, action="submit")
    item.approval_state = "pending_review"
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.exception.submitted",
        entity_type="TimetablePolicyException",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _exception_payload(item)


@router.post("/exceptions/{exception_id}/approve", summary="Approve exception request")
async def approve_exception(
    exception_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyException).where(TimetablePolicyException.id == exception_id, TimetablePolicyException.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")
    _assert_transition(item.approval_state, allowed={"pending_review"}, action="approve")
    if item.expires_at is not None and item.expires_at <= _now():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Exception has already expired.")

    item.approval_state = "approved"
    item.approved_by_user_id = actor.id
    item.approved_at = _now()
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.exception.approved",
        entity_type="TimetablePolicyException",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _exception_payload(item)


@router.post("/exceptions/{exception_id}/reject", summary="Reject exception request")
async def reject_exception(
    exception_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyException).where(TimetablePolicyException.id == exception_id, TimetablePolicyException.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")
    _assert_transition(item.approval_state, allowed={"pending_review"}, action="reject")

    item.approval_state = "rejected"
    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.exception.rejected",
        entity_type="TimetablePolicyException",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _exception_payload(item)


@router.post("/exceptions/{exception_id}/revoke", summary="Revoke approved exception")
async def revoke_exception(
    exception_id: uuid.UUID,
    body: LifecycleReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(TimetablePolicyException).where(TimetablePolicyException.id == exception_id, TimetablePolicyException.tenant_id == tenant.id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")
    _assert_transition(item.approval_state, allowed={"approved"}, action="revoke")

    item.approval_state = "revoked"
    item.is_active = False
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_policy.exception.revoked",
        entity_type="TimetablePolicyException",
        entity_id=item.id,
        actor_id=actor.id,
        details={"reason": body.reason},
    )
    await db.commit()
    await db.refresh(item)
    return _exception_payload(item)


@router.get("/constraint-types", summary="List supported constraint types")
async def get_constraint_types(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
):
    _ensure_actor_tenant(actor, tenant)
    return list_constraint_types()


@router.get("/constraint-types/{constraint_type}", summary="Get one supported constraint type")
async def get_constraint_type(
    constraint_type: str,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
):
    _ensure_actor_tenant(actor, tenant)
    definition = get_constraint_type_or_none(constraint_type)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constraint type not found.")
    return definition
