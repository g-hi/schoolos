from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.gateway.ai.audit import log_action
from services.gateway.ai.family_timeline import write_timeline_event
from services.gateway.ai.messenger import send_to_user
from shared.db.models import (
    Announcement,
    AnnouncementTarget,
    Class,
    Message,
    Notification,
    Student,
    StudentParent,
    User,
)
from shared.db.parent_models import Family, ParentPreferences

logger = logging.getLogger(__name__)

LEGAL_TRANSITIONS = {
    "draft": {"scheduled", "published"},
    "scheduled": {"draft", "published"},
    "published": {"archived"},
    "archived": set(),
}
TARGET_TYPES = {"school", "grade", "class", "family", "student"}
RETRYABLE_STATUSES = {"pending", "failed"}
RECOVERABLE_ERROR_CODES = {"DELIVERY_FAILED", "DELIVERY_EXCEPTION", "TWILIO_ERROR", "SENDGRID_ERROR"}
CLAIM_STALE_AFTER_SECONDS = 300


def _normalize_error_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper().replace(" ", "_")
    return normalized[:100]


def _next_retry_time(attempt_count: int) -> datetime:
    backoff_minutes = min(60, 5 * max(1, 2 ** (attempt_count - 1)))
    return datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)


def _session_factory_from_session(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = db.get_bind()
    return async_sessionmaker(bind=bind, expire_on_commit=False)


def validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="timezone must be a valid IANA timezone") from exc


def validate_scheduled_at(value: datetime) -> None:
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="scheduled_at must be timezone-aware")
    if value <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="scheduled_at must be in the future")


def validate_target(target_type: str, *, grade=None, class_id=None, family_id=None, student_id=None) -> None:
    values = {"grade": grade, "class": class_id, "family": family_id, "student": student_id}
    if target_type not in TARGET_TYPES:
        raise HTTPException(status_code=422, detail="Invalid announcement target type")
    expected = {"school": None, "grade": "grade", "class": "class", "family": "family", "student": "student"}[target_type]
    if (expected is None and any(values.values())) or (expected is not None and values[expected] is None) or (expected is not None and any(value is not None for key, value in values.items() if key != expected)):
        raise HTTPException(status_code=422, detail="Target fields do not match target_type")


def validate_transition(current: str, target: str) -> None:
    if target not in LEGAL_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=422, detail="Illegal announcement lifecycle transition")


async def _target_rows(db: AsyncSession, tenant_id: uuid.UUID, announcement_id: uuid.UUID) -> list[AnnouncementTarget]:
    result = await db.execute(select(AnnouncementTarget).where(AnnouncementTarget.tenant_id == tenant_id, AnnouncementTarget.announcement_id == announcement_id))
    return list(result.scalars().all())


async def _validate_target_tenant(db: AsyncSession, tenant_id: uuid.UUID, target: AnnouncementTarget) -> None:
    if target.target_type == "class":
        result = await db.execute(select(Class.id).where(Class.id == target.class_id, Class.tenant_id == tenant_id))
    elif target.target_type == "family":
        result = await db.execute(select(Family.id).where(Family.id == target.family_id, Family.tenant_id == tenant_id))
    elif target.target_type == "student":
        result = await db.execute(select(Student.id).where(Student.id == target.student_id, Student.tenant_id == tenant_id))
    else:
        return
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=422, detail="Announcement target is outside the tenant")


async def resolve_recipients(db: AsyncSession, tenant_id: uuid.UUID, targets: list[AnnouncementTarget]) -> list[User]:
    users: dict[uuid.UUID, User] = {}
    for target in targets:
        await _validate_target_tenant(db, tenant_id, target)
        stmt = (
            select(User)
            .join(StudentParent, StudentParent.parent_id == User.id)
            .join(Student, Student.id == StudentParent.student_id)
            .join(Class, Class.id == Student.class_id)
            .where(User.tenant_id == tenant_id, User.role == "parent", User.is_active.is_(True))
        )
        if target.target_type == "grade":
            stmt = stmt.where(Class.grade == target.grade)
        elif target.target_type == "class":
            stmt = stmt.where(Student.class_id == target.class_id)
        elif target.target_type == "family":
            stmt = stmt.where(StudentParent.family_id == target.family_id)
        elif target.target_type == "student":
            stmt = stmt.where(Student.id == target.student_id)
        for user in (await db.execute(stmt)).scalars().all():
            users[user.id] = user
    return list(users.values())


async def _families_for_users(db: AsyncSession, tenant_id: uuid.UUID, users: list[User]) -> dict[uuid.UUID, set[uuid.UUID]]:
    if not users:
        return {}
    result = await db.execute(
        select(StudentParent.parent_id, StudentParent.family_id).where(
            StudentParent.tenant_id == tenant_id,
            StudentParent.parent_id.in_([user.id for user in users]),
            StudentParent.family_id.is_not(None),
        )
    )
    families: dict[uuid.UUID, set[uuid.UUID]] = {}
    for parent_id, family_id in result.all():
        families.setdefault(parent_id, set()).add(family_id)
    return families


async def _write_publication_side_effects(db: AsyncSession, tenant_id: uuid.UUID, announcement: Announcement, users: list[User]) -> None:
    await log_action(db=db, tenant_id=tenant_id, action="announcement.published", entity_type="Announcement", entity_id=announcement.id, actor_id=announcement.author_user_id, details={"published_at": announcement.published_at.isoformat()})
    family_map = await _families_for_users(db, tenant_id, users)
    families = {family_id for family_ids in family_map.values() for family_id in family_ids}
    for family_id in families:
        await write_timeline_event(
            db=db,
            tenant_id=tenant_id,
            family_id=family_id,
            event_type="announcement.published",
            event_category="announcement",
            title=announcement.title,
            occurred_at=announcement.published_at,
            source_module="announcements",
            event_key=f"announcement:{announcement.id}:family:{family_id}:published:{announcement.published_at.isoformat()}",
            description=announcement.body,
            priority="informational",
            action_url="/parent/announcements",
            visibility="family",
        )


async def deliver_notification(db: AsyncSession, notification_id: uuid.UUID, tenant_id: uuid.UUID) -> Notification:
    try:
        async with db.begin():
            notification = (await db.execute(select(Notification).where(Notification.id == notification_id, Notification.tenant_id == tenant_id).with_for_update())).scalar_one()
            user = await db.get(User, notification.recipient_user_id)
            if user is None or user.tenant_id != tenant_id:
                notification.delivery_status = "failed"
                notification.attempt_count += 1
                notification.last_attempt_at = datetime.now(timezone.utc)
                notification.last_error_code = "RECIPIENT_NOT_FOUND"
                notification.next_attempt_at = None
                notification.updated_at = datetime.now(timezone.utc)
                return notification
            preferences = (await db.execute(select(ParentPreferences).where(ParentPreferences.tenant_id == tenant_id, ParentPreferences.user_id == user.id))).scalar_one_or_none()
            channel = user.preferred_channel or "sms"
            if preferences is not None and not preferences.in_app_notifications:
                notification.delivery_status = "skipped"
                notification.last_error_code = "PREFERENCE_DISABLED"
                notification.next_attempt_at = None
                notification.updated_at = datetime.now(timezone.utc)
                return notification
            if channel == "email" and preferences is not None and not preferences.email_notifications:
                notification.delivery_status = "skipped"
                notification.last_error_code = "PREFERENCE_DISABLED"
                notification.next_attempt_at = None
                notification.updated_at = datetime.now(timezone.utc)
                return notification
            notification.attempt_count += 1
            notification.last_attempt_at = datetime.now(timezone.utc)
            message = await send_to_user(user, notification.body, "announcement", db, notification_id=notification.id, email_subject=f"[SchoolOS] {notification.title}")
            if message.status in {"sent", "delivered"}:
                notification.delivery_status = "delivered"
                notification.last_error_code = None
                notification.next_attempt_at = None
            elif message.status == "skipped":
                notification.delivery_status = "skipped"
                notification.last_error_code = _normalize_error_code(message.error)
                notification.next_attempt_at = None
            else:
                notification.delivery_status = "failed"
                notification.last_error_code = _normalize_error_code(message.error) or "DELIVERY_FAILED"
                if notification.last_error_code in RECOVERABLE_ERROR_CODES:
                    notification.next_attempt_at = _next_retry_time(notification.attempt_count)
                else:
                    notification.next_attempt_at = None
            notification.updated_at = datetime.now(timezone.utc)
            return notification
    except Exception:
        await db.rollback()
        logger.warning("announcement notification delivery failed", exc_info=False)
        raise


async def publish_announcement(db: AsyncSession, tenant_id: uuid.UUID, announcement_id: uuid.UUID) -> Announcement:
    notification_ids: list[uuid.UUID] = []
    async with db.begin():
        announcement = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
        if announcement is None:
            raise HTTPException(status_code=404, detail="Announcement not found")
        if announcement.status == "published":
            return announcement
        if announcement.status in {"draft", "scheduled"}:
            validate_transition(announcement.status, "published")
        elif announcement.status != "publishing":
            raise HTTPException(status_code=422, detail="Illegal announcement lifecycle transition")
        targets = await _target_rows(db, tenant_id, announcement.id)
        if not targets:
            raise HTTPException(status_code=422, detail="Announcement requires at least one target")
        users = await resolve_recipients(db, tenant_id, targets)
        now = datetime.now(timezone.utc)
        announcement.status = "published"
        announcement.published_at = announcement.published_at or now
        announcement.publication_claimed_at = None
        announcement.publication_claimed_by = None
        announcement.updated_at = now
        for user in users:
            existing = (await db.execute(select(Notification).where(Notification.tenant_id == tenant_id, Notification.announcement_id == announcement.id, Notification.recipient_user_id == user.id))).scalar_one_or_none()
            if existing is None:
                created = Notification(id=uuid.uuid4(), tenant_id=tenant_id, recipient_user_id=user.id, announcement_id=announcement.id, source_type="announcement", source_id=announcement.id, category="announcement", title=announcement.title, body=announcement.body)
                db.add(created)
                notification_ids.append(created.id)
            else:
                notification_ids.append(existing.id)
        await _write_publication_side_effects(db, tenant_id, announcement, users)
    session_factory = _session_factory_from_session(db)
    for notification_id in notification_ids:
        try:
            async with session_factory() as delivery_db:
                await deliver_notification(delivery_db, notification_id, tenant_id)
        except Exception:
            continue
    return announcement


async def transition_announcement(db: AsyncSession, tenant_id: uuid.UUID, announcement_id: uuid.UUID, target: str, actor_id: uuid.UUID) -> Announcement:
    async with db.begin():
        announcement = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
        if announcement is None:
            raise HTTPException(status_code=404, detail="Announcement not found")
        validate_transition(announcement.status, target)
        now = datetime.now(timezone.utc)
        announcement.status = target
        announcement.updated_at = now
        if target == "scheduled":
            if announcement.scheduled_at is None:
                raise HTTPException(status_code=422, detail="scheduled_at is required")
        elif target == "draft":
            announcement.scheduled_at = None
        elif target == "archived":
            announcement.archived_at = now
        await log_action(db=db, tenant_id=tenant_id, action=f"announcement.{target if target != 'draft' else 'unscheduled'}", entity_type="Announcement", entity_id=announcement.id, actor_id=actor_id, details={"status": target})
    return announcement


async def claim_due_announcement_ids(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 20, claimant_id: str = "announcement-worker") -> list[uuid.UUID]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=CLAIM_STALE_AFTER_SECONDS)
    async with db.begin():
        result = await db.execute(
            select(Announcement)
            .where(
                Announcement.tenant_id == tenant_id,
                or_(
                    (Announcement.status == "scheduled") & (Announcement.scheduled_at <= now),
                    (Announcement.status == "publishing") & (Announcement.publication_claimed_at <= stale_before),
                ),
            )
            .order_by(Announcement.scheduled_at.asc(), Announcement.id.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.status = "publishing"
            row.publication_claimed_at = now
            row.publication_claimed_by = claimant_id
            row.updated_at = now
        return [row.id for row in rows]


async def claim_due_notification_ids(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 100) -> list[uuid.UUID]:
    now = datetime.now(timezone.utc)
    async with db.begin():
        result = await db.execute(
            select(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.delivery_status.in_(RETRYABLE_STATUSES),
                or_(
                    Notification.next_attempt_at.is_(None),
                    Notification.next_attempt_at <= now,
                ),
            )
            .order_by(Notification.created_at.asc(), Notification.id.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = list(result.scalars().all())
        return [row.id for row in rows]
