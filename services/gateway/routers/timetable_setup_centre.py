from __future__ import annotations

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.centre import (
    ALLOWED_ACTIVITY_ACTION_TYPES,
    ALLOWED_ACTIVITY_ENTITY_TYPES,
    ALLOWED_ISSUE_SOURCES,
    ALLOWED_ISSUE_SEVERITIES,
    ALLOWED_IMPORT_STATUS_NAMES,
    STEP_DEFINITIONS,
    build_setup_centre_payload,
    collect_approval_queue,
    get_approvals_queue,
    get_recent_activity,
)
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Tenant, User


router = APIRouter(prefix="/leadership/timetable-setup/centre", tags=["Timetable Setup Centre"])


def _ensure_actor_tenant(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _paginate(items: list[dict], *, page: int, page_size: int) -> dict[str, object]:
    total = len(items)
    start = max(0, (page - 1) * page_size)
    return {"items": items[start : start + page_size], "total": total, "page": page, "page_size": page_size}


def _validate_member(value: str | None, allowed: set[str], *, field_name: str) -> None:
    if value is None:
        return
    if value not in allowed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported {field_name}: {value}.")


def _filter_issues(
    items: list[dict],
    *,
    severity: str | None,
    setup_step: str | None,
    source: str | None,
    resolved: bool | None,
    requires_approval: bool | None,
) -> list[dict]:
    filtered = items
    if severity is not None:
        filtered = [item for item in filtered if item.get("severity") == severity]
    if setup_step is not None:
        filtered = [item for item in filtered if item.get("step_key") == setup_step]
    if source is not None:
        filtered = [item for item in filtered if item.get("source") == source]
    if resolved is not None:
        filtered = [item for item in filtered if bool(item.get("resolved", False)) is resolved]
    if requires_approval is not None:
        filtered = [item for item in filtered if bool(item.get("requires_human_authorization", False)) is requires_approval]
    return filtered


def _filter_queue(
    items: list[dict],
    *,
    type_filter: str | None,
    urgency: str | None,
    setup_step: str | None,
) -> list[dict]:
    filtered = items
    if type_filter is not None:
        filtered = [item for item in filtered if item.get("type") == type_filter]
    if urgency is not None:
        filtered = [item for item in filtered if item.get("urgency") == urgency]
    if setup_step is not None:
        filtered = [item for item in filtered if item.get("setup_step") == setup_step]
    return filtered


@router.get("/summary", summary="Get unified timetable setup centre summary")
async def get_centre_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    return {
        "generated_at": payload["generated_at"],
        "progress": payload.get("progress", {}),
        "generation": payload.get("generation", {}),
        "provenance": payload.get("provenance", {"source_breakdown": {}, "review_breakdown": {}, "lifecycle_counts": {}}),
        "source_breakdown": payload.get("source_breakdown", {}),
        "review_breakdown": payload.get("review_breakdown", {}),
        "import_summaries": payload.get("import_summaries", {"workbook": {}, "pdf": {}}),
        "approval_queue": payload.get("approval_queue", {"items": [], "pending_total": 0, "direct_route": "/leadership/timetable-setup/centre/approvals"}),
        "policy_diagnostics": payload.get("policy_diagnostics", {"summary": {}, "generation": {}, "conflicts": [], "feasibility": [], "impact": [], "resolution_guidance": [], "policy_counts": {}}),
        "policy_readiness": payload.get("policy_readiness"),
        "policy": payload.get("policy", {}),
        "counts": {
            "calendar_approved": payload.get("metrics", {}).get("calendar_approved", 0),
            "school_week_approved": payload.get("metrics", {}).get("school_week_approved", 0),
            "bell_schedule_approved": payload.get("metrics", {}).get("bell_schedule_approved", 0),
            "teaching_periods_active": payload.get("metrics", {}).get("teaching_periods_active", 0),
            "rooms_approved": payload.get("metrics", {}).get("rooms_approved", 0),
            "classes_active": payload.get("metrics", {}).get("classes_active", 0),
            "subjects_total": payload.get("metrics", {}).get("subjects_total", 0),
            "teachers_active": payload.get("metrics", {}).get("teachers_active", 0),
            "requirements_approved": payload.get("metrics", {}).get("requirements_approved", 0),
            "imports_total": payload.get("metrics", {}).get("imports_total", 0),
        },
        "progress_explanation": payload.get("progress_explanation"),
    }


@router.get("/steps", summary="List setup centre steps with deterministic status")
async def list_centre_steps(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    return {
        "generated_at": payload["generated_at"],
        "progress": payload.get("progress", {}),
        "steps": payload.get("steps", []),
        "progress_explanation": payload.get("progress_explanation"),
    }


@router.get("/steps/{step_key}", summary="Get one setup centre step")
async def get_centre_step(
    step_key: str,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    step = next((item for item in payload["steps"] if item["step_key"] == step_key), None)
    if step is None:
        valid_keys = [item["step_key"] for item in STEP_DEFINITIONS]
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"message": "Unknown step_key.", "valid_step_keys": valid_keys},
        )
    related_issues = [item for item in payload["issues"] if item.get("step_key") in {step_key, "approvals_and_readiness"}]
    return {"generated_at": payload["generated_at"], "step": step, "related_issues": related_issues}


@router.get("/issues", summary="List aggregated setup issues")
async def list_centre_issues(
    severity: str | None = Query(default=None),
    setup_step: str | None = Query(default=None),
    status: str | None = Query(default=None),
    step_key: str | None = Query(default=None),
    source: str | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    requires_approval: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    if setup_step is None:
        setup_step = step_key
    _validate_member(severity, ALLOWED_ISSUE_SEVERITIES, field_name="severity")
    _validate_member(source, ALLOWED_ISSUE_SOURCES, field_name="source")
    if status is not None and status not in {"blocking", "warning", "pending_review", "resolved"}:
        raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported status: {status}.")
    issues = _filter_issues(
        payload["issues"],
        severity=severity,
        setup_step=setup_step,
        source=source,
        resolved=resolved if resolved is not None else (status == "resolved" if status is not None else None),
        requires_approval=requires_approval,
    )
    if status is not None:
        issues = [item for item in issues if item.get("status") == status]
    return {
        "generated_at": payload["generated_at"],
        "total": len(issues),
        "page": page,
        "page_size": page_size,
        "items": _paginate(issues, page=page, page_size=page_size)["items"],
        "direct_route": "/leadership/timetable-setup/centre/issues",
    }


@router.get("/approvals", summary="Get pending human-approval queue")
async def list_centre_approvals(
    type_filter: str | None = Query(default=None, alias="type"),
    urgency: str | None = Query(default=None),
    setup_step: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    queue = payload.get("approval_queue")
    if not queue:
        queue = await get_approvals_queue(payload.get("metrics", {}))
    direct_route = queue.get("direct_route", "/leadership/timetable-setup/centre/approvals")
    filtered = _filter_queue(queue["items"], type_filter=type_filter, urgency=urgency, setup_step=setup_step)
    pending_total = sum(int(item.get("pending_count", 1)) for item in filtered)
    return {
        "generated_at": payload["generated_at"],
        "pending_total": pending_total,
        "items": _paginate(filtered, page=page, page_size=page_size)["items"],
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
        "direct_route": direct_route,
    }


@router.get("/activity", summary="Get recent timetable setup activity")
async def list_centre_activity(
    action_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    _validate_member(action_type, ALLOWED_ACTIVITY_ACTION_TYPES, field_name="action_type")
    _validate_member(entity_type, ALLOWED_ACTIVITY_ENTITY_TYPES, field_name="entity_type")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_date cannot be before start_date.")
    payload = await get_recent_activity(
        db,
        tenant.id,
        page=page,
        page_size=page_size,
        action_type=action_type,
        entity_type=entity_type,
        start_date=start_date,
        end_date=end_date,
    )
    return payload


@router.get("/recommendations", summary="Get policy-aware setup recommendations")
async def list_centre_recommendations(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    return {
        "generated_at": payload["generated_at"],
        "generation": payload["generation"],
        "recommendations": payload["recommendations"],
        "policy": payload["policy"],
    }


@router.post("/revalidate", summary="Re-run deterministic setup validation")
async def revalidate_centre(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    payload = await build_setup_centre_payload(db, tenant.id)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.centre.revalidated",
        entity_type="TimetableSetupCentre",
        entity_id=uuid.uuid4(),
        actor_id=actor.id,
        details={
            "generation_allowed": payload["generation"]["generation_allowed"],
            "readiness_status": payload["generation"]["readiness_status"],
            "blocker_count": payload["generation"]["blocker_count"],
            "pending_approval_count": payload["generation"]["pending_approval_count"],
        },
    )
    await db.commit()
    return {
        "revalidated": True,
        "generated_at": payload["generated_at"],
        "generation": payload["generation"],
        "progress": payload["progress"],
    }
