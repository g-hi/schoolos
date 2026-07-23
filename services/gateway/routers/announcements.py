from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.announcements import (
    _target_rows,
    _validate_target_tenant,
    publish_announcement,
    transition_announcement,
    validate_scheduled_at,
    validate_target,
    validate_timezone,
)
from shared.auth.dependencies import resolve_authenticated_leadership, resolve_authenticated_parent, resolve_family
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Announcement, AnnouncementTarget, Notification, Tenant, User

router = APIRouter(prefix="", tags=["Announcements"])


class AnnouncementTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: str
    grade: str | None = None
    class_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None

    @field_validator("target_type")
    @classmethod
    def target_type_valid(cls, value: str) -> str:
        if value not in {"school", "grade", "class", "family", "student"}:
            raise ValueError("Invalid announcement target type")
        return value

    @model_validator(mode="after")
    def target_shape_valid(self):
        try:
            validate_target(self.target_type, grade=self.grade, class_id=self.class_id, family_id=self.family_id, student_id=self.student_id)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc
        return self


class AnnouncementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    body: str
    timezone: str = "UTC"
    targets: list[AnnouncementTargetRequest]


class AnnouncementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    body: str | None = None
    timezone: str | None = None
    targets: list[AnnouncementTargetRequest] | None = None


def _announcement_response(announcement: Announcement) -> dict:
    return {"id": str(announcement.id), "title": announcement.title, "body": announcement.body, "status": announcement.status, "timezone": announcement.timezone, "scheduled_at": announcement.scheduled_at, "published_at": announcement.published_at, "archived_at": announcement.archived_at, "created_at": announcement.created_at, "updated_at": announcement.updated_at}


def _target_response(target: AnnouncementTarget) -> dict:
    return {"target_type": target.target_type, "grade": target.grade, "class_id": str(target.class_id) if target.class_id else None, "family_id": str(target.family_id) if target.family_id else None, "student_id": str(target.student_id) if target.student_id else None}


def _target_key_from_request(request: AnnouncementTargetRequest) -> str:
    if request.target_type == "school":
        return "school"
    if request.target_type == "grade":
        return f"grade:{request.grade}"
    if request.target_type == "class":
        return f"class:{request.class_id}"
    if request.target_type == "family":
        return f"family:{request.family_id}"
    return f"student:{request.student_id}"


async def _create_targets(db: AsyncSession, tenant_id: uuid.UUID, announcement_id: uuid.UUID, targets: list[AnnouncementTargetRequest]) -> None:
    if not targets:
        raise HTTPException(status_code=422, detail="Announcement requires at least one target")
    for request in targets:
        validate_target(request.target_type, grade=request.grade, class_id=request.class_id, family_id=request.family_id, student_id=request.student_id)
        target = AnnouncementTarget(tenant_id=tenant_id, announcement_id=announcement_id, target_type=request.target_type, target_key=_target_key_from_request(request), grade=request.grade, class_id=request.class_id, family_id=request.family_id, student_id=request.student_id)
        await _validate_target_tenant(db, tenant_id, target)
        db.add(target)


@router.post("/announcements")
async def create_announcement(body: AnnouncementCreateRequest, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    validate_timezone(body.timezone)
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        announcement = Announcement(tenant_id=tenant.id, author_user_id=actor.id, title=body.title, body=body.body, timezone=body.timezone)
        db.add(announcement)
        await db.flush()
        await _create_targets(db, tenant.id, announcement.id, body.targets)
        await log_action(db=db, tenant_id=tenant.id, action="announcement.created", entity_type="Announcement", entity_id=announcement.id, actor_id=actor.id, details={"title": announcement.title})
    return _announcement_response(announcement)


@router.get("/announcements")
async def list_announcements(status_filter: str | None = Query(default=None, alias="status"), date_from: datetime | None = None, date_to: datetime | None = None, target_type: str | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    query = select(Announcement).where(Announcement.tenant_id == tenant.id)
    if status_filter:
        query = query.where(Announcement.status == status_filter)
    if date_from:
        query = query.where(Announcement.created_at >= date_from)
    if date_to:
        query = query.where(Announcement.created_at <= date_to)
    if target_type:
        query = query.where(Announcement.id.in_(select(AnnouncementTarget.announcement_id).where(AnnouncementTarget.tenant_id == tenant.id, AnnouncementTarget.target_type == target_type)))
    query = query.order_by(Announcement.created_at.desc(), Announcement.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_announcement_response(row) for row in rows], "page": page, "page_size": page_size}


@router.get("/announcements/{announcement_id}")
async def get_announcement(announcement_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    announcement = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant.id))).scalar_one_or_none()
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    targets = await _target_rows(db, tenant.id, announcement.id)
    return {**_announcement_response(announcement), "targets": [_target_response(target) for target in targets]}


@router.patch("/announcements/{announcement_id}")
async def update_announcement(announcement_id: uuid.UUID, body: AnnouncementUpdateRequest, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        announcement = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant.id).with_for_update())).scalar_one_or_none()
        if announcement is None:
            raise HTTPException(status_code=404, detail="Announcement not found")
        if announcement.status not in {"draft", "scheduled"}:
            raise HTTPException(status_code=422, detail="Only draft and scheduled announcements may be edited")
        if body.timezone is not None:
            validate_timezone(body.timezone)
            announcement.timezone = body.timezone
        if body.title is not None:
            announcement.title = body.title
        if body.body is not None:
            announcement.body = body.body
        if body.targets is not None:
            await db.execute(delete(AnnouncementTarget).where(AnnouncementTarget.announcement_id == announcement.id, AnnouncementTarget.tenant_id == tenant.id))
            await _create_targets(db, tenant.id, announcement.id, body.targets)
        announcement.updated_at = datetime.now(timezone.utc)
        await log_action(db=db, tenant_id=tenant.id, action="announcement.updated", entity_type="Announcement", entity_id=announcement.id, actor_id=actor.id, details={"status": announcement.status})
    return _announcement_response(announcement)


@router.post("/announcements/{announcement_id}/schedule")
async def schedule_announcement(announcement_id: uuid.UUID, scheduled_at: datetime, timezone_name: str = Query(default="UTC", alias="timezone"), tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    scheduled_at_utc = scheduled_at.astimezone(timezone.utc) if scheduled_at.tzinfo is not None else scheduled_at
    validate_timezone(timezone_name)
    validate_scheduled_at(scheduled_at_utc)
    async with db.begin():
        await set_tenant_context(db, tenant.id)
        announcement = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant.id).with_for_update())).scalar_one_or_none()
        if announcement is None:
            raise HTTPException(status_code=404, detail="Announcement not found")
        if announcement.status != "draft":
            raise HTTPException(status_code=422, detail="Only draft announcements may be scheduled")
        announcement.scheduled_at = scheduled_at_utc
        announcement.timezone = timezone_name
        announcement.status = "scheduled"
        announcement.updated_at = datetime.now(timezone.utc)
        await log_action(db=db, tenant_id=tenant.id, action="announcement.scheduled", entity_type="Announcement", entity_id=announcement.id, actor_id=actor.id, details={"scheduled_at": scheduled_at_utc.isoformat()})
    return _announcement_response(announcement)


@router.post("/announcements/{announcement_id}/unschedule")
async def unschedule_announcement(announcement_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    return _announcement_response(await transition_announcement(db, tenant.id, announcement_id, "draft", actor.id))


@router.post("/announcements/{announcement_id}/publish")
async def publish_announcement_route(announcement_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    return _announcement_response(await publish_announcement(db, tenant.id, announcement_id))


@router.post("/announcements/{announcement_id}/archive")
async def archive_announcement(announcement_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    return _announcement_response(await transition_announcement(db, tenant.id, announcement_id, "archived", actor.id))


@router.get("/announcements/{announcement_id}/deliveries")
async def list_announcement_deliveries(announcement_id: uuid.UUID, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant), actor: User = Depends(resolve_authenticated_leadership), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    query = select(Notification).where(Notification.tenant_id == tenant.id, Notification.announcement_id == announcement_id).order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()
    return {"items": [{"id": str(row.id), "recipient_user_id": str(row.recipient_user_id), "delivery_status": row.delivery_status, "read_at": row.read_at, "attempt_count": row.attempt_count, "last_error_code": row.last_error_code} for row in rows], "page": page, "page_size": page_size}


@router.get("/parent/announcements")
async def list_parent_announcements(status_filter: str | None = Query(default=None, alias="status"), date_from: datetime | None = None, date_to: datetime | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant), parent: User = Depends(resolve_authenticated_parent), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    query = select(Announcement, Notification).join(Notification, Notification.announcement_id == Announcement.id).where(Announcement.tenant_id == tenant.id, Notification.tenant_id == tenant.id, Notification.recipient_user_id == parent.id)
    if status_filter:
        query = query.where(Announcement.status == status_filter)
    if date_from:
        query = query.where(Announcement.published_at >= date_from)
    if date_to:
        query = query.where(Announcement.published_at <= date_to)
    query = query.order_by(Announcement.published_at.desc(), Announcement.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()
    return {"items": [{**_announcement_response(announcement), "read_at": notification.read_at} for announcement, notification in rows], "page": page, "page_size": page_size}


@router.get("/parent/announcements/{announcement_id}")
async def get_parent_announcement(announcement_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), parent: User = Depends(resolve_authenticated_parent), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    row = (await db.execute(select(Announcement, Notification).join(Notification, Notification.announcement_id == Announcement.id).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant.id, Notification.tenant_id == tenant.id, Notification.recipient_user_id == parent.id))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    announcement, notification = row
    return {**_announcement_response(announcement), "read_at": notification.read_at}


@router.get("/parent/notifications")
async def list_parent_notifications(read: bool | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant), parent: User = Depends(resolve_authenticated_parent), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    query = select(Notification).where(Notification.tenant_id == tenant.id, Notification.recipient_user_id == parent.id).order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    if read is True:
        query = query.where(Notification.read_at.is_not(None))
    elif read is False:
        query = query.where(Notification.read_at.is_(None))
    rows = (await db.execute(query)).scalars().all()
    return {"items": [{"id": str(row.id), "announcement_id": str(row.announcement_id) if row.announcement_id else None, "title": row.title, "body": row.body, "read_at": row.read_at, "delivery_status": row.delivery_status} for row in rows], "page": page, "page_size": page_size}


@router.post("/parent/notifications/{notification_id}/read")
async def mark_parent_notification_read(notification_id: uuid.UUID, tenant: Tenant = Depends(resolve_tenant), parent: User = Depends(resolve_authenticated_parent), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    notification = (await db.execute(select(Notification).where(Notification.id == notification_id, Notification.tenant_id == tenant.id, Notification.recipient_user_id == parent.id))).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = notification.read_at or datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(notification.id), "read_at": notification.read_at}


@router.post("/parent/notifications/read-all")
async def mark_all_parent_notifications_read(tenant: Tenant = Depends(resolve_tenant), parent: User = Depends(resolve_authenticated_parent), db: AsyncSession = Depends(get_db)):
    await set_tenant_context(db, tenant.id)
    rows = (await db.execute(select(Notification).where(Notification.tenant_id == tenant.id, Notification.recipient_user_id == parent.id, Notification.read_at.is_(None)))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.read_at = now
    await db.commit()
    return {"updated": len(rows)}
