from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.ai.family_timeline import write_timeline_event
from services.gateway.ai.messenger import send_to_user
from services.gateway.authorization.teacher_scope import teacher_has_homeroom_scope
from services.gateway.authorization.student_enrollment_scope import resolve_student_class
from shared.auth.dependencies import (
    resolve_authenticated_leadership,
    resolve_authenticated_parent,
    resolve_authenticated_teacher,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Class, PickupRequest, Student, StudentParent, Teacher, Tenant, User
from shared.db.parent_models import Family

router = APIRouter(prefix="", tags=["Pickup"])

ACTIVE_TRANSITIONS = {
    "requested": {"acknowledged", "cancelled"},
    "acknowledged": {"called", "cancelled"},
    "called": {"prepared", "cancelled"},
    "prepared": {"completed", "cancelled"},
}
TERMINAL_STATUSES = {"completed", "cancelled", "released", "rejected_outside_geofence"}


def _assert_user_belongs_to_tenant(*, user: User, tenant: Tenant) -> None:
    if user.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ParentPickupCreateRequest(BaseModel):
    student_id: uuid.UUID
    command_text: str = Field(min_length=1)
    channel: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class PickupTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None


class PickupCompleteRequest(PickupTransitionRequest):
    verification_method: str
    verification_note: str


class PickupLegacyCreateRequest(BaseModel):
    parent_phone: str
    command_text: str
    latitude: float
    longitude: float
    channel: str | None = None
    requested_at: str | None = None
    academic_year: str = "2025-2026"


class PickupLegacyReleaseRequest(BaseModel):
    pickup_id: str
    teacher_phone: str | None = None
    notes: str | None = None


def _serialize_pickup(p: PickupRequest, *, include_sensitive: bool = False) -> dict:
    payload = {
        "pickup_id": str(p.id),
        "student_id": str(p.student_id),
        "parent_id": str(p.parent_id),
        "class_id": str(p.class_id),
        "teacher_id": str(p.teacher_id) if p.teacher_id else None,
        "status": p.status,
        "channel": p.channel,
        "requested_at": p.requested_at.isoformat() if p.requested_at else None,
        "acknowledged_at": p.acknowledged_at.isoformat() if p.acknowledged_at else None,
        "called_at": p.called_at.isoformat() if p.called_at else None,
        "prepared_at": p.prepared_at.isoformat() if p.prepared_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        "cancelled_at": p.cancelled_at.isoformat() if p.cancelled_at else None,
        "verified_by": str(p.verified_by) if p.verified_by else None,
        "verified_at": p.verified_at.isoformat() if p.verified_at else None,
        "verification_method": p.verification_method,
        "verification_note": p.verification_note,
        "notes": p.notes,
        "within_geofence": p.within_geofence,
        "distance_meters": p.distance_meters,
        "early_pickup": p.early_pickup,
    }
    if include_sensitive:
        payload["parent_latitude"] = p.parent_latitude
        payload["parent_longitude"] = p.parent_longitude
    return payload


async def _resolve_teacher_profile(db: AsyncSession, tenant_id: uuid.UUID, teacher_user_id: uuid.UUID) -> Teacher | None:
    result = await db.execute(
        select(Teacher).where(Teacher.tenant_id == tenant_id, Teacher.user_id == teacher_user_id)
    )
    return result.scalar_one_or_none()


async def _resolve_family_for_parent(db: AsyncSession, tenant_id: uuid.UUID, parent_id: uuid.UUID) -> Family | None:
    result = await db.execute(
        select(Family)
        .join(StudentParent, StudentParent.family_id == Family.id)
        .where(
            StudentParent.parent_id == parent_id,
            Family.tenant_id == tenant_id,
            Family.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _notify_parent_pickup_status(
    *,
    db: AsyncSession,
    pickup: PickupRequest,
    status_label: str,
) -> None:
    parent = await db.get(User, pickup.parent_id)
    if parent is None:
        return
    await send_to_user(
        parent,
        f"[SchoolOS] Pickup status for student {pickup.student_id} is now {status_label}.",
        "pickup_status_update",
        db,
        student_id=pickup.student_id,
        email_subject="[SchoolOS] Pickup Status Updated",
    )


async def _write_pickup_timeline(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pickup: PickupRequest,
    event_type: str,
    title: str,
    description: str,
) -> None:
    family = await _resolve_family_for_parent(db, tenant_id, pickup.parent_id)
    if family is None:
        return
    await write_timeline_event(
        db=db,
        tenant_id=tenant_id,
        family_id=family.id,
        event_type=event_type,
        event_category="pickup",
        title=title,
        occurred_at=datetime.now(timezone.utc),
        source_module="pickup",
        source_reference=str(pickup.id),
        student_id=pickup.student_id,
        description=description,
        action_url="/parent",
    )


def _assert_transition_allowed(current_status: str, target_status: str) -> None:
    if current_status == target_status:
        return
    if current_status in TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pickup request is in a terminal status.")
    allowed = ACTIVE_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Illegal pickup lifecycle transition.")


def _apply_transition(
    pickup: PickupRequest,
    target_status: str,
    *,
    actor_id: uuid.UUID,
    note: str | None,
    verification_method: str | None = None,
    verification_note: str | None = None,
) -> bool:
    current_status = pickup.status
    _assert_transition_allowed(current_status, target_status)
    if current_status == target_status:
        return False

    if target_status == "completed":
        if not verification_method or not verification_method.strip():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="verification_method is required for completion.")
        if not verification_note or not verification_note.strip():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="verification_note is required for completion.")

    now = datetime.now(timezone.utc)
    pickup.status = target_status
    pickup.notes = note if note is not None else pickup.notes

    if target_status == "acknowledged":
        pickup.acknowledged_at = now
    elif target_status == "called":
        pickup.called_at = now
    elif target_status == "prepared":
        pickup.prepared_at = now
    elif target_status == "completed":
        pickup.completed_at = now
        pickup.verified_by = actor_id
        pickup.verified_at = now
        pickup.verification_method = verification_method.strip()
        pickup.verification_note = verification_note.strip()
    elif target_status == "cancelled":
        pickup.cancelled_at = now
        pickup.cancelled_by = actor_id

    return True


async def _load_pickup_for_update(db: AsyncSession, tenant_id: uuid.UUID, pickup_id: uuid.UUID) -> PickupRequest | None:
    result = await db.execute(
        select(PickupRequest)
        .where(PickupRequest.tenant_id == tenant_id, PickupRequest.id == pickup_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _parent_student_pickup_access(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parent_id: uuid.UUID,
    student_id: uuid.UUID,
) -> StudentParent:
    result = await db.execute(
        select(StudentParent)
        .join(Student, Student.id == StudentParent.student_id)
        .where(
            StudentParent.parent_id == parent_id,
            StudentParent.student_id == student_id,
            Student.tenant_id == tenant_id,
        )
    )
    sp = result.scalar_one_or_none()
    if sp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    if not bool(sp.can_pickup):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Pickup is not allowed for this student.")
    return sp


async def _teacher_can_access_pickup(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    teacher_profile: Teacher,
    pickup: PickupRequest,
) -> bool:
    result = await db.execute(
        select(Class).where(
            Class.tenant_id == tenant_id,
            Class.id == pickup.class_id,
        )
    )
    klass = result.scalar_one_or_none()
    if klass is None:
        return False

    effective_date = (pickup.requested_at or datetime.now(timezone.utc)).date()
    decision = await teacher_has_homeroom_scope(
        db=db,
        tenant_id=tenant_id,
        teacher_id=teacher_profile.id,
        klass=klass,
        effective_date=effective_date,
    )
    return decision.authorized


async def _parent_create_pickup(
    *,
    body: ParentPickupCreateRequest,
    tenant: Tenant,
    parent: User,
    db: AsyncSession,
) -> dict:
    await _parent_student_pickup_access(
        db=db,
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=body.student_id,
    )

    student_result = await db.execute(
        select(Student).where(Student.id == body.student_id, Student.tenant_id == tenant.id)
    )
    student = student_result.scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    action_date = datetime.now(timezone.utc).date()
    resolution = await resolve_student_class(
        db=db,
        tenant_id=tenant.id,
        student_id=student.id,
        effective_date=action_date,
    )
    if resolution.class_id is None:
        if resolution.denied_due_to_canonical_history:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student has no active canonical enrollment.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student class not found.")

    class_result = await db.execute(
        select(Class).where(Class.id == resolution.class_id, Class.tenant_id == tenant.id)
    )
    klass = class_result.scalar_one_or_none()
    if klass is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student class not found.")

    teacher_id = klass.class_teacher_id

    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_id,
        channel=(body.channel or "app"),
        command_text=body.command_text,
        parent_latitude=body.latitude or 0.0,
        parent_longitude=body.longitude or 0.0,
        distance_meters=0.0,
        geofence_radius_m=int((tenant.settings or {}).get("pickup_radius_m", 150)),
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.add(pickup)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="pickup.requested",
        entity_type="PickupRequest",
        entity_id=pickup.id,
        actor_id=parent.id,
        details={"student_id": str(student.id), "class_id": str(klass.id)},
    )
    await _write_pickup_timeline(
        db=db,
        tenant_id=tenant.id,
        pickup=pickup,
        event_type="pickup.requested",
        title="Pickup requested",
        description="A parent submitted a pickup request.",
    )
    await db.commit()
    return _serialize_pickup(pickup)


@router.post("/parent/pickup-requests", summary="Create pickup request")
async def create_parent_pickup_request(
    body: ParentPickupCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=parent, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    return await _parent_create_pickup(body=body, tenant=tenant, parent=parent, db=db)


@router.get("/parent/pickup-requests", summary="List parent pickup requests")
async def list_parent_pickup_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=parent, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    stmt = select(PickupRequest).where(PickupRequest.tenant_id == tenant.id, PickupRequest.parent_id == parent.id)
    if status_filter:
        stmt = stmt.where(PickupRequest.status == status_filter)
    stmt = stmt.order_by(PickupRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"items": [_serialize_pickup(r) for r in rows], "page": page, "page_size": page_size}


@router.get("/parent/pickup-requests/{pickup_id}", summary="Get parent pickup request")
async def get_parent_pickup_request(
    pickup_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=parent, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(PickupRequest).where(
            PickupRequest.id == pickup_id,
            PickupRequest.tenant_id == tenant.id,
            PickupRequest.parent_id == parent.id,
        )
    )
    pickup = result.scalar_one_or_none()
    if pickup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")
    return _serialize_pickup(pickup)


@router.post("/parent/pickup-requests/{pickup_id}/cancel", summary="Cancel parent pickup request")
async def cancel_parent_pickup_request(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=parent, tenant=tenant)
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        pickup = await _load_pickup_for_update(db, tenant.id, pickup_id)
        if pickup is None or pickup.parent_id != parent.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")
        changed = _apply_transition(pickup, "cancelled", actor_id=parent.id, note=body.note)
        if changed:
            await log_action(
                db=db,
                tenant_id=tenant.id,
                action="pickup.cancelled",
                entity_type="PickupRequest",
                entity_id=pickup.id,
                actor_id=parent.id,
                details={"status": pickup.status},
            )
            await _write_pickup_timeline(
                db=db,
                tenant_id=tenant.id,
                pickup=pickup,
                event_type="pickup.cancelled",
                title="Pickup cancelled",
                description="A parent cancelled this pickup request.",
            )
    return _serialize_pickup(pickup)


async def _teacher_pickup_scope_or_403(db: AsyncSession, tenant_id: uuid.UUID, teacher_user: User) -> Teacher:
    teacher_profile = await _resolve_teacher_profile(db, tenant_id, teacher_user.id)
    if teacher_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    return teacher_profile


@router.get("/teacher/pickup-requests", summary="List teacher pickup requests")
async def list_teacher_pickup_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=teacher_user, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _teacher_pickup_scope_or_403(db, tenant.id, teacher_user)
    stmt = select(PickupRequest).where(PickupRequest.tenant_id == tenant.id)
    if status_filter:
        stmt = stmt.where(PickupRequest.status == status_filter)
    stmt = stmt.order_by(PickupRequest.requested_at.desc())
    result = await db.execute(stmt)
    scoped: list[PickupRequest] = []
    for row in result.scalars().all():
        if await _teacher_can_access_pickup(db=db, tenant_id=tenant.id, teacher_profile=teacher_profile, pickup=row):
            scoped.append(row)
    start = (page - 1) * page_size
    end = start + page_size
    paged = scoped[start:end]
    return {"items": [_serialize_pickup(r) for r in paged], "page": page, "page_size": page_size}


@router.get("/teacher/pickup-requests/{pickup_id}", summary="Get teacher pickup request")
async def get_teacher_pickup_request(
    pickup_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=teacher_user, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    teacher_profile = await _teacher_pickup_scope_or_403(db, tenant.id, teacher_user)
    result = await db.execute(
        select(PickupRequest).where(PickupRequest.id == pickup_id, PickupRequest.tenant_id == tenant.id)
    )
    pickup = result.scalar_one_or_none()
    if pickup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")
    if not await _teacher_can_access_pickup(db=db, tenant_id=tenant.id, teacher_profile=teacher_profile, pickup=pickup):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
    return _serialize_pickup(pickup)


async def _teacher_transition(
    *,
    pickup_id: uuid.UUID,
    target_status: str,
    body: PickupTransitionRequest,
    tenant: Tenant,
    teacher_user: User,
    db: AsyncSession,
) -> dict:
    _assert_user_belongs_to_tenant(user=teacher_user, tenant=tenant)
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        teacher_profile = await _teacher_pickup_scope_or_403(db, tenant.id, teacher_user)
        pickup = await _load_pickup_for_update(db, tenant.id, pickup_id)
        if pickup is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")
        if not await _teacher_can_access_pickup(db=db, tenant_id=tenant.id, teacher_profile=teacher_profile, pickup=pickup):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
        changed = _apply_transition(pickup, target_status, actor_id=teacher_user.id, note=body.note)
        if changed:
            await log_action(
                db=db,
                tenant_id=tenant.id,
                action=f"pickup.{target_status}",
                entity_type="PickupRequest",
                entity_id=pickup.id,
                actor_id=teacher_user.id,
                details={"status": pickup.status},
            )
            await _write_pickup_timeline(
                db=db,
                tenant_id=tenant.id,
                pickup=pickup,
                event_type=f"pickup.{target_status}",
                title=f"Pickup {target_status}",
                description=f"A teacher marked this pickup as {target_status}.",
            )
            await _notify_parent_pickup_status(db=db, pickup=pickup, status_label=target_status)
    return _serialize_pickup(pickup)


@router.post("/teacher/pickup-requests/{pickup_id}/acknowledge", summary="Acknowledge pickup")
async def teacher_acknowledge_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _teacher_transition(
        pickup_id=pickup_id,
        target_status="acknowledged",
        body=body,
        tenant=tenant,
        teacher_user=teacher_user,
        db=db,
    )


@router.post("/teacher/pickup-requests/{pickup_id}/call", summary="Mark pickup called")
async def teacher_call_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _teacher_transition(
        pickup_id=pickup_id,
        target_status="called",
        body=body,
        tenant=tenant,
        teacher_user=teacher_user,
        db=db,
    )


@router.post("/teacher/pickup-requests/{pickup_id}/prepare", summary="Mark pickup prepared")
async def teacher_prepare_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    teacher_user: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _teacher_transition(
        pickup_id=pickup_id,
        target_status="prepared",
        body=body,
        tenant=tenant,
        teacher_user=teacher_user,
        db=db,
    )


@router.get("/leadership/pickup-requests", summary="List leadership pickup requests")
async def list_leadership_pickup_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    stmt = select(PickupRequest).where(PickupRequest.tenant_id == tenant.id)
    if status_filter:
        stmt = stmt.where(PickupRequest.status == status_filter)
    stmt = stmt.order_by(PickupRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"items": [_serialize_pickup(r) for r in rows], "page": page, "page_size": page_size}


@router.get("/leadership/pickup-requests/{pickup_id}", summary="Get leadership pickup request")
async def get_leadership_pickup_request(
    pickup_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _assert_user_belongs_to_tenant(user=actor, tenant=tenant)
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(PickupRequest).where(PickupRequest.id == pickup_id, PickupRequest.tenant_id == tenant.id)
    )
    pickup = result.scalar_one_or_none()
    if pickup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")
    return _serialize_pickup(pickup)


async def _leadership_transition(
    *,
    pickup_id: uuid.UUID,
    target_status: str,
    body: PickupTransitionRequest,
    tenant: Tenant,
    actor: User,
    db: AsyncSession,
    complete_payload: PickupCompleteRequest | None = None,
) -> dict:
    _assert_user_belongs_to_tenant(user=actor, tenant=tenant)
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        pickup = await _load_pickup_for_update(db, tenant.id, pickup_id)
        if pickup is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")

        if target_status == "completed":
            if actor.role not in {"principal", "school_admin"}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this resource.")
            changed = _apply_transition(
                pickup,
                target_status,
                actor_id=actor.id,
                note=complete_payload.note if complete_payload else None,
                verification_method=complete_payload.verification_method if complete_payload else None,
                verification_note=complete_payload.verification_note if complete_payload else None,
            )
        else:
            changed = _apply_transition(pickup, target_status, actor_id=actor.id, note=body.note)

        if changed:
            await log_action(
                db=db,
                tenant_id=tenant.id,
                action=f"pickup.{target_status}",
                entity_type="PickupRequest",
                entity_id=pickup.id,
                actor_id=actor.id,
                details={"status": pickup.status},
            )
            await _write_pickup_timeline(
                db=db,
                tenant_id=tenant.id,
                pickup=pickup,
                event_type=f"pickup.{target_status}",
                title=f"Pickup {target_status}",
                description=f"Leadership marked this pickup as {target_status}.",
            )
            await _notify_parent_pickup_status(db=db, pickup=pickup, status_label=target_status)
    return _serialize_pickup(pickup)


@router.post("/leadership/pickup-requests/{pickup_id}/acknowledge", summary="Leadership acknowledge pickup")
async def leadership_acknowledge_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _leadership_transition(
        pickup_id=pickup_id,
        target_status="acknowledged",
        body=body,
        tenant=tenant,
        actor=actor,
        db=db,
    )


@router.post("/leadership/pickup-requests/{pickup_id}/call", summary="Leadership call pickup")
async def leadership_call_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _leadership_transition(
        pickup_id=pickup_id,
        target_status="called",
        body=body,
        tenant=tenant,
        actor=actor,
        db=db,
    )


@router.post("/leadership/pickup-requests/{pickup_id}/prepare", summary="Leadership prepare pickup")
async def leadership_prepare_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _leadership_transition(
        pickup_id=pickup_id,
        target_status="prepared",
        body=body,
        tenant=tenant,
        actor=actor,
        db=db,
    )


@router.post("/leadership/pickup-requests/{pickup_id}/complete", summary="Leadership complete pickup")
async def leadership_complete_pickup(
    pickup_id: uuid.UUID,
    body: PickupCompleteRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _leadership_transition(
        pickup_id=pickup_id,
        target_status="completed",
        body=body,
        tenant=tenant,
        actor=actor,
        db=db,
        complete_payload=body,
    )


@router.post("/leadership/pickup-requests/{pickup_id}/cancel", summary="Leadership cancel pickup")
async def leadership_cancel_pickup(
    pickup_id: uuid.UUID,
    body: PickupTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _leadership_transition(
        pickup_id=pickup_id,
        target_status="cancelled",
        body=body,
        tenant=tenant,
        actor=actor,
        db=db,
    )


@router.post("/pickup/request", summary="Legacy pickup request endpoint (deprecated)")
async def legacy_pickup_request_deprecated(
    body: PickupLegacyCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Deprecated endpoint. Use POST /parent/pickup-requests with authenticated parent context.",
    )


@router.post("/pickup/release", summary="Legacy pickup release endpoint (deprecated)")
async def legacy_pickup_release_deprecated(
    body: PickupLegacyReleaseRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Deprecated endpoint. Use authenticated leadership complete workflow.",
    )


@router.get("/pickup/log", summary="Legacy pickup log endpoint (deprecated)")
async def legacy_pickup_log_deprecated(
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Deprecated endpoint. Use role-scoped pickup request listing endpoints.",
    )
