from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.onboarding.readiness import OPTIONAL_SKIP_STEPS, STEP_CATALOGUE, STEP_GROUPS, compute_readiness
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import SchoolOnboardingRun, SchoolOnboardingStep, Tenant, User

router = APIRouter(prefix="/leadership/onboarding", tags=["Onboarding"])

ACTIVE_STATUSES = {"in_progress", "paused", "ready"}
TERMINAL_STATUSES = {"completed", "cancelled"}
MANUAL_ACK_STEPS = {"family_relationships", "data_imports", "readiness_review"}


class CurrentStepUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_key: str


class StepAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None


class StepSkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class _Pagination(BaseModel):
    page: int
    page_size: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_step_key(step_key: str) -> str:
    value = step_key.strip()
    if value not in STEP_CATALOGUE:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid step key.")
    return value


def _sanitize_note(value: str | None, *, max_len: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _ensure_actor_tenant(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive users cannot access this resource.",
        )
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _load_active_run(db: AsyncSession, tenant_id: uuid.UUID, *, lock: bool = False) -> SchoolOnboardingRun | None:
    stmt = (
        select(SchoolOnboardingRun)
        .where(SchoolOnboardingRun.tenant_id == tenant_id, SchoolOnboardingRun.status.in_(list(ACTIVE_STATUSES)))
        .order_by(SchoolOnboardingRun.created_at.desc())
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def _load_run_by_id(db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> SchoolOnboardingRun | None:
    return await db.scalar(select(SchoolOnboardingRun).where(SchoolOnboardingRun.id == run_id, SchoolOnboardingRun.tenant_id == tenant_id))


async def _load_step(db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID, step_key: str, *, lock: bool = False) -> SchoolOnboardingStep | None:
    stmt = select(SchoolOnboardingStep).where(
        SchoolOnboardingStep.tenant_id == tenant_id,
        SchoolOnboardingStep.onboarding_run_id == run_id,
        SchoolOnboardingStep.step_key == step_key,
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


def _group_steps(step_rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for group, keys in STEP_GROUPS.items():
        group_rows = [row for row in step_rows if row["step_key"] in keys]
        grouped[group] = {
            "total": len(group_rows),
            "completed": sum(1 for row in group_rows if row["status"] in {"completed", "skipped"}),
            "blocked": sum(1 for row in group_rows if row["status"] == "blocked"),
            "in_progress": sum(1 for row in group_rows if row["status"] == "in_progress"),
            "not_started": sum(1 for row in group_rows if row["status"] == "not_started"),
        }
    return grouped


def _step_effective_status(*, step_key: str, persisted_status: str, computed_status: str, current_step_key: str | None) -> str:
    if persisted_status == "skipped":
        return "skipped"
    if computed_status == "blocked":
        return "blocked"
    if computed_status == "completed":
        return "completed"
    if current_step_key == step_key:
        return "in_progress"
    return "not_started"


async def _build_run_status_payload(db: AsyncSession, tenant: Tenant, run: SchoolOnboardingRun) -> dict[str, Any]:
    readiness = await compute_readiness(db, tenant.id)

    step_models = (
        await db.execute(
            select(SchoolOnboardingStep)
            .where(SchoolOnboardingStep.tenant_id == tenant.id, SchoolOnboardingStep.onboarding_run_id == run.id)
            .order_by(SchoolOnboardingStep.created_at.asc())
        )
    ).scalars().all()

    step_rows: list[dict[str, Any]] = []
    for step_key in STEP_CATALOGUE:
        model = next((item for item in step_models if item.step_key == step_key), None)
        if model is None:
            continue
        computed = readiness["step_statuses"].get(step_key, "not_started")
        effective = _step_effective_status(
            step_key=step_key,
            persisted_status=model.status,
            computed_status=computed,
            current_step_key=run.current_step_key,
        )
        step_rows.append(
            {
                "step_key": step_key,
                "status": effective,
                "persisted_status": model.status,
                "completion_source": model.completion_source,
                "acknowledged_by_user_id": str(model.acknowledged_by_user_id) if model.acknowledged_by_user_id else None,
                "acknowledged_at": model.acknowledged_at,
                "blocked_reason": model.blocked_reason,
            }
        )

    completed_step_count = sum(1 for row in step_rows if row["status"] in {"completed", "skipped"})
    blocked_step_count = sum(1 for row in step_rows if row["status"] == "blocked")

    next_recommended_step = None
    for key in STEP_CATALOGUE:
        row = next((item for item in step_rows if item["step_key"] == key), None)
        if row and row["status"] not in {"completed", "skipped"}:
            next_recommended_step = key
            break

    available_actions: list[str] = []
    if run.status in {"in_progress", "ready"}:
        available_actions.extend(["pause", "cancel", "set_current_step", "acknowledge_step", "skip_optional_step"])
        if readiness["blocker_count"] == 0:
            available_actions.append("complete")
    elif run.status == "paused":
        available_actions.extend(["resume", "cancel"])

    return {
        "run": {
            "id": str(run.id),
            "status": run.status,
            "current_step_key": run.current_step_key,
            "started_by_user_id": str(run.started_by_user_id),
            "completed_by_user_id": str(run.completed_by_user_id) if run.completed_by_user_id else None,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "paused_at": run.paused_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
        "run_status": run.status,
        "current_step": run.current_step_key,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "readiness_percentage": readiness["readiness_percentage"],
        "completed_step_count": completed_step_count,
        "blocked_step_count": blocked_step_count,
        "warning_count": readiness["warning_count"],
        "next_recommended_step": next_recommended_step,
        "ordered_steps": step_rows,
        "grouped_progress": _group_steps(step_rows),
        "available_actions": available_actions,
    }


@router.get("/status", summary="Get onboarding status")
async def onboarding_status(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    run = await _load_active_run(db, tenant.id)
    if run is None:
        readiness = await compute_readiness(db, tenant.id)
        return {
            "run": None,
            "run_status": "not_started",
            "current_step": None,
            "started_at": None,
            "completed_at": None,
            "readiness_percentage": readiness["readiness_percentage"],
            "completed_step_count": 0,
            "blocked_step_count": 0,
            "warning_count": readiness["warning_count"],
            "next_recommended_step": readiness["recommended_next_actions"][0]["step_key"] if readiness["recommended_next_actions"] else "campus",
            "ordered_steps": [{"step_key": key, "status": readiness["step_statuses"].get(key, "not_started")} for key in STEP_CATALOGUE],
            "grouped_progress": _group_steps([{"step_key": key, "status": readiness["step_statuses"].get(key, "not_started")} for key in STEP_CATALOGUE]),
            "available_actions": ["start"],
        }
    return await _build_run_status_payload(db, tenant, run)


@router.get("/readiness", summary="Get onboarding readiness")
async def onboarding_readiness(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    readiness = await compute_readiness(db, tenant.id)
    run = await _load_active_run(db, tenant.id)

    if run is None:
        state = "not_started"
    elif run.status == "completed":
        state = "completed"
    elif readiness["blocker_count"] > 0:
        state = "blocked"
    elif run.status == "ready":
        state = "ready"
    else:
        state = "in_progress"

    return {
        "state": state,
        "readiness_percentage": readiness["readiness_percentage"],
        "blocker_count": readiness["blocker_count"],
        "warning_count": readiness["warning_count"],
        "informational_count": readiness["informational_count"],
        "grouped_readiness_checks": readiness["grouped_checks"],
        "recommended_next_actions": readiness["recommended_next_actions"],
        "safe_routes": ["/academic-structure", "/people", "/data", "/timetable"],
    }


@router.post("/start", summary="Start onboarding run")
async def start_onboarding(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    active = await _load_active_run(db, tenant.id, lock=True)
    if active is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active onboarding run already exists.")

    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="campus",
        started_by_user_id=actor.id,
        completed_by_user_id=None,
        started_at=_now(),
        completed_at=None,
        paused_at=None,
    )
    db.add(run)
    await db.flush()

    for step_key in STEP_CATALOGUE:
        step = SchoolOnboardingStep(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            onboarding_run_id=run.id,
            step_key=step_key,
            status="in_progress" if step_key == "campus" else "not_started",
            completion_source=None,
            acknowledged_by_user_id=None,
            acknowledged_at=None,
            blocked_reason=None,
            metadata_json=None,
        )
        db.add(step)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.started",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={"onboarding_run_id": str(run.id), "status": run.status, "step_key": run.current_step_key},
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.patch("/current-step", summary="Update onboarding current step")
async def update_current_step(
    body: CurrentStepUpdateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    step_key = _validate_step_key(body.step_key)

    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completed or cancelled run cannot be changed.")

    run.current_step_key = step_key
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.current_step.changed",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={"onboarding_run_id": str(run.id), "step_key": step_key, "status": run.status},
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/steps/{step_key}/acknowledge", summary="Acknowledge onboarding step")
async def acknowledge_step(
    step_key: str,
    body: StepAcknowledgeRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    key = _validate_step_key(step_key)
    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")

    step = await _load_step(db, tenant.id, run.id, key, lock=True)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding step not found.")

    readiness = await compute_readiness(db, tenant.id)
    if readiness["step_statuses"].get(key) == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Blocking computed requirement cannot be manually overridden.")

    if key not in MANUAL_ACK_STEPS and step.status not in {"in_progress", "not_started"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This step cannot be acknowledged in its current state.")

    note = _sanitize_note(body.note)
    step.status = "completed"
    step.completion_source = "manual"
    step.acknowledged_by_user_id = actor.id
    step.acknowledged_at = _now()
    step.blocked_reason = None
    step.metadata_json = {"note": note} if note else {}

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.step.acknowledged",
        entity_type="SchoolOnboardingStep",
        entity_id=step.id,
        actor_id=actor.id,
        details={
            "onboarding_run_id": str(run.id),
            "step_key": key,
            "status": step.status,
            "blocker_count": readiness["blocker_count"],
            "warning_count": readiness["warning_count"],
        },
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/steps/{step_key}/skip", summary="Skip optional onboarding step")
async def skip_step(
    step_key: str,
    body: StepSkipRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    key = _validate_step_key(step_key)
    if key not in OPTIONAL_SKIP_STEPS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This step cannot be skipped.")

    reason = _sanitize_note(body.reason, max_len=1000)
    if not reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="reason is required.")

    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")

    step = await _load_step(db, tenant.id, run.id, key, lock=True)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding step not found.")

    readiness = await compute_readiness(db, tenant.id)
    if readiness["step_statuses"].get(key) == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Blocking computed requirement cannot be skipped.")

    step.status = "skipped"
    step.completion_source = "manual"
    step.acknowledged_by_user_id = actor.id
    step.acknowledged_at = _now()
    step.blocked_reason = reason
    step.metadata_json = {"reason": reason}

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.step.skipped",
        entity_type="SchoolOnboardingStep",
        entity_id=step.id,
        actor_id=actor.id,
        details={
            "onboarding_run_id": str(run.id),
            "step_key": key,
            "status": step.status,
            "blocker_count": readiness["blocker_count"],
            "warning_count": readiness["warning_count"],
        },
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/pause", summary="Pause onboarding run")
async def pause_onboarding(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")
    if run.status not in {"in_progress", "ready"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only in_progress or ready runs can be paused.")

    run.status = "paused"
    run.paused_at = _now()
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.paused",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={"onboarding_run_id": str(run.id), "status": run.status},
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/resume", summary="Resume onboarding run")
async def resume_onboarding(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None or run.status != "paused":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only paused runs can be resumed.")

    readiness = await compute_readiness(db, tenant.id)
    run.status = "ready" if readiness["blocker_count"] == 0 else "in_progress"
    run.paused_at = None
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.resumed",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={
            "onboarding_run_id": str(run.id),
            "status": run.status,
            "blocker_count": readiness["blocker_count"],
            "warning_count": readiness["warning_count"],
        },
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/complete", summary="Complete onboarding run")
async def complete_onboarding(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")

    readiness = await compute_readiness(db, tenant.id)
    if readiness["blocker_count"] > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Onboarding cannot be completed while blocking requirements remain.")

    run.status = "completed"
    run.completed_by_user_id = actor.id
    run.completed_at = _now()
    run.paused_at = None
    run.current_step_key = "readiness_review"

    review_step = await _load_step(db, tenant.id, run.id, "readiness_review", lock=True)
    if review_step is not None:
        review_step.status = "completed"
        review_step.completion_source = "manual"
        review_step.acknowledged_by_user_id = actor.id
        review_step.acknowledged_at = _now()
        review_step.metadata_json = {"completed": True}

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.completed",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={
            "onboarding_run_id": str(run.id),
            "status": run.status,
            "blocker_count": readiness["blocker_count"],
            "warning_count": readiness["warning_count"],
        },
    )
    await db.commit()
    await db.refresh(run)
    return await _build_run_status_payload(db, tenant, run)


@router.post("/cancel", summary="Cancel onboarding run")
async def cancel_onboarding(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    run = await _load_active_run(db, tenant.id, lock=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active onboarding run.")

    run.status = "cancelled"
    run.completed_at = _now()
    run.completed_by_user_id = actor.id
    run.paused_at = None

    readiness = await compute_readiness(db, tenant.id)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="onboarding.cancelled",
        entity_type="SchoolOnboardingRun",
        entity_id=run.id,
        actor_id=actor.id,
        details={
            "onboarding_run_id": str(run.id),
            "status": run.status,
            "blocker_count": readiness["blocker_count"],
            "warning_count": readiness["warning_count"],
        },
    )
    await db.commit()
    await db.refresh(run)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "completed_at": run.completed_at,
    }


@router.get("/history", summary="List onboarding run history")
async def onboarding_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(SchoolOnboardingRun)
            .where(SchoolOnboardingRun.tenant_id == tenant.id)
            .order_by(SchoolOnboardingRun.created_at.desc())
        )
    ).scalars().all()

    start = (page - 1) * page_size
    selected = rows[start : start + page_size]

    items = []
    for run in selected:
        readiness = await compute_readiness(db, tenant.id)
        items.append(
            {
                "run_id": str(run.id),
                "status": run.status,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "paused_at": run.paused_at,
                "started_by_user_id": str(run.started_by_user_id),
                "completed_by_user_id": str(run.completed_by_user_id) if run.completed_by_user_id else None,
                "completion_percentage": readiness["readiness_percentage"],
                "blocker_count": readiness["blocker_count"],
                "warning_count": readiness["warning_count"],
            }
        )

    return {
        "items": items,
        "total": len(rows),
        "page": page,
        "page_size": page_size,
    }
