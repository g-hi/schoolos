"""
SchoolOS – Family Timeline Service  (Phase 8.1)
================================================
Provides write_timeline_event() — the single entry point for persisting
family timeline events.

Usage
-----
    from services.gateway.ai.family_timeline import write_timeline_event

    await write_timeline_event(
        db=db,
        tenant_id=tenant.id,
        family_id=family.id,
        event_type="pickup.released",
        event_category="pickup",
        title="Omar released safely",
        occurred_at=datetime.now(timezone.utc),
        source_module="pickup",
        source_reference=str(pickup_request.id),
        student_id=student.id,
        priority="informational",
        action_url="/parent/pickup",
    )

Idempotency
-----------
If the same event has already been written (same tenant + idempotency_key),
the call is a no-op and the existing record is returned.

The idempotency_key is computed as:
    "{source_module}:{source_reference}:{event_type}"  — for events with source
    explicit event_key argument                          — for events without source

Callers MUST supply source_reference OR event_key.
Supplying neither is a programming error and raises ValueError.

action_url validation
---------------------
Only internal /parent/* paths are permitted.
javascript:, http://, https://, // are rejected.

Phase 8.1 operational status
-----------------------------
The helper is implemented and idempotent.
No production callers exist yet in Phase 8.1.
Writers are added in Phases 8.5–8.6 as each module integrates.
The /families/me/timeline endpoint returns an empty collection until then.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.parent_models import FamilyTimelineEvent, validate_timeline_action_url

logger = logging.getLogger(__name__)


async def write_timeline_event(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    family_id: uuid.UUID,
    event_type: str,
    event_category: str,
    title: str,
    occurred_at: datetime,
    source_module: str,
    # Provide source_reference for events linked to a DB record.
    # Provide event_key for synthetic or aggregate events with no single source.
    # Exactly one of the two must be supplied.
    source_reference: str | None = None,
    event_key: str | None = None,
    student_id: uuid.UUID | None = None,
    description: str | None = None,
    priority: str = "informational",
    action_url: str | None = None,
    visibility: str = "family",
) -> FamilyTimelineEvent:
    """
    Idempotently writes one FamilyTimelineEvent.

    Returns the existing record if the idempotency_key is already present.
    Returns the newly created record otherwise.

    Raises
    ------
    ValueError
        If neither source_reference nor event_key is supplied.
    ValueError
        If action_url is provided but is not a valid /parent/* path.
    """
    if source_reference is None and event_key is None:
        raise ValueError(
            "write_timeline_event requires either source_reference or event_key. "
            f"Got neither for event_type={event_type!r}, source_module={source_module!r}."
        )

    if source_reference is not None:
        idempotency_key = f"{source_module}:{source_reference}:{event_type}"
    else:
        idempotency_key = str(event_key)

    # Validate action_url before persistence
    validated_url = validate_timeline_action_url(action_url)

    # Ensure occurred_at is timezone-aware
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    # Check for existing record (idempotency)
    result = await db.execute(
        select(FamilyTimelineEvent).where(
            FamilyTimelineEvent.tenant_id == tenant_id,
            FamilyTimelineEvent.idempotency_key == idempotency_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        logger.debug(
            "timeline.event_already_exists | key=%s tenant=%s",
            idempotency_key,
            str(tenant_id),
        )
        return existing

    event = FamilyTimelineEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        family_id=family_id,
        student_id=student_id,
        idempotency_key=idempotency_key,
        event_type=event_type,
        event_category=event_category,
        title=title,
        description=description,
        occurred_at=occurred_at,
        source_module=source_module,
        source_reference=source_reference,
        priority=priority,
        action_url=validated_url,
        visibility=visibility,
    )
    db.add(event)

    try:
        await db.flush()
    except IntegrityError:
        # Concurrent insert with the same idempotency_key — treat as no-op.
        await db.rollback()
        logger.debug(
            "timeline.concurrent_duplicate | key=%s tenant=%s",
            idempotency_key,
            str(tenant_id),
        )
        result = await db.execute(
            select(FamilyTimelineEvent).where(
                FamilyTimelineEvent.tenant_id == tenant_id,
                FamilyTimelineEvent.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one()

    logger.info(
        "timeline.event_written | type=%s category=%s module=%s tenant=%s",
        event_type,
        event_category,
        source_module,
        str(tenant_id),
    )
    return event
