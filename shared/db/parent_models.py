"""
SchoolOS – Parent Experience Models  (Phase 8.1)
=================================================
New ORM tables for the Parent Experience Platform.

These models use string-based ForeignKey references where they point to
tables defined in shared.db.models to avoid circular imports.

Family membership strategy (Version 1 — intentional limitation)
----------------------------------------------------------------
Family membership is inferred from StudentParent.family_id.  A parent
user belongs to a family by virtue of having at least one StudentParent
row that references a given Family.  This is the minimum viable model for
Version 1.

A dedicated FamilyMembership table is not created in this release.
If multiple parents need different permission sets within the same family
in a future release, a FamilyMembership join table can be introduced
without breaking this foundation.

Tenant isolation guarantee
--------------------------
Every model has:
  tenant_id  FK → tenants.id (CASCADE delete)

The application layer additionally validates that all Family, Parent User,
and Student rows share the same tenant_id before linking them.
This prevents cross-tenant relationship poisoning.

Alembic migration
-----------------
All schema changes are managed via Alembic.
Base.metadata.create_all() is used only in development and test
environments (app_env != "production").
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from shared.db.base import Base


# ─────────────────────────────────────────────────────────────────────────────
# Allowed action_url pattern for FamilyTimelineEvent
# Only internal /parent/* paths are permitted.
# ─────────────────────────────────────────────────────────────────────────────
_ALLOWED_ACTION_URL_RE = re.compile(r"^/parent(/[A-Za-z0-9/_\-\.%?=&]*)?$")


def validate_timeline_action_url(url: str | None) -> str | None:
    """
    Validates that action_url is an internal /parent/* path.

    Rejects:
    - javascript: URLs
    - http:// / https:// (external)
    - Protocol-relative URLs (//)
    - Any path not starting with /parent

    Called by write_timeline_event() before persistence.
    Raises ValueError if the URL is provided but invalid.
    """
    if url is None:
        return None
    url = url.strip()
    if not url:
        return None
    if not _ALLOWED_ACTION_URL_RE.match(url):
        raise ValueError(
            f"action_url must be an internal /parent/* path. Got: {url!r}"
        )
    return url


# ─────────────────────────────────────────────────────────────────────────────
# Family
# ─────────────────────────────────────────────────────────────────────────────

class Family(Base):
    """
    Groups one or more parent/guardian Users and their authorized Students
    into a single family unit.

    Family membership is inferred from StudentParent.family_id (Version 1).
    The family name is for display only and is NOT unique — different families
    within the same school may share a surname.
    The UUID id is the authoritative identifier.

    is_active: allows soft-disabling a family without deleting historical data.
    """

    __tablename__ = "families"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships — loaded lazily to avoid N+1 in list endpoints
    student_parents: Mapped[list["StudentParent"]] = relationship(  # type: ignore[name-defined]
        "StudentParent",
        foreign_keys="[StudentParent.family_id]",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ParentPreferences
# ─────────────────────────────────────────────────────────────────────────────

class ParentPreferences(Base):
    """
    Parent-specific display and notification preferences.

    Kept separate from User to avoid polluting the shared User model with
    parent-only configuration fields.

    The UniqueConstraint(tenant_id, user_id) ensures:
    1. Only one preferences row per user.
    2. The referenced user is scoped to the correct tenant.
       (tenant_id must match user.tenant_id — enforced at the application
       layer in resolve_or_create_parent_preferences().)
    """

    __tablename__ = "parent_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preferred_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en"
    )
    timezone: Mapped[str] = mapped_column(
        String(60), nullable=False, default="UTC"
    )
    theme: Mapped[str] = mapped_column(
        String(20), nullable=False, default="light"
    )
    weekly_report_digest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    email_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    in_app_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_parent_preferences_user"),
        CheckConstraint(
            "theme IN ('light','dark','system')",
            name="valid_theme",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FamilyTimelineEvent
# ─────────────────────────────────────────────────────────────────────────────

class FamilyTimelineEvent(Base):
    """
    Chronological event projection for the Family Timeline.

    Write strategy — write-on-event:
        When a business event occurs (pickup released, report published,
        appointment confirmed, etc.), write_timeline_event() in
        services.gateway.ai.family_timeline is called to append a row.

    Idempotency:
        The idempotency_key column (UniqueConstraint per tenant) prevents
        duplicate events for the same source record.
        - For events with a source_reference (e.g., a pickup_request UUID),
          the key is: "{source_module}:{source_reference}:{event_type}"
        - For events without a source_reference, the caller MUST supply an
          explicit idempotency_key. Passing None is a programming error.
        NULL source_reference is NOT used for duplicate prevention because
        PostgreSQL UNIQUE constraints permit multiple NULL values.

    Current operational status (Phase 8.1):
        The table is created and the write helper is registered.
        No production writers are active in Phase 8.1.
        The API returns an empty collection until Phases 8.5–8.6 add writers.

    action_url restriction:
        Must be an internal /parent/* path or NULL.
        Validated by validate_timeline_action_url() before persistence.
        javascript:, http://, https://, // are all rejected.
    """

    __tablename__ = "family_timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Idempotency key — always required; never NULL.
    # Format: "{source_module}:{source_reference}:{event_type}"
    # or an explicit caller-supplied key for events without a source record.
    idempotency_key: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    event_category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source_module: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="informational"
    )
    action_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="family"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Idempotency: one idempotency_key per tenant prevents duplicate events.
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_timeline_idempotency"
        ),
        CheckConstraint(
            "priority IN ('critical','important','informational')",
            name="valid_timeline_priority",
        ),
        CheckConstraint(
            "visibility IN ('family','student_only')",
            name="valid_timeline_visibility",
        ),
    )
