from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    UUID,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.db.base import Base


class WeeklyStudentReport(Base):
    __tablename__ = "weekly_student_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    timezone_used: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "student_id", "week_start", name="uq_weekly_report_per_student_week"),
        CheckConstraint(
            "status IN ('draft','generating','pending_review','changes_requested','approved','published','generation_failed','validation_failed','archived')",
            name="valid_weekly_report_status",
        ),
        CheckConstraint("row_version >= 1", name="valid_weekly_report_row_version"),
    )


class WeeklyStudentReportVersion(Base):
    __tablename__ = "weekly_student_report_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_student_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")

    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="passed")
    validation_errors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("report_id", "version_number", name="uq_weekly_report_version_number"),
        CheckConstraint("source_type IN ('manual','ai_generated','staff_revision')", name="valid_weekly_report_source_type"),
        CheckConstraint("validation_status IN ('passed','failed')", name="valid_weekly_report_validation_status"),
    )


class WeeklyStudentReportReviewEvent(Base):
    __tablename__ = "weekly_student_report_review_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_student_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_student_report_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
