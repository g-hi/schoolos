"""weekly_reports_phase_8_4

Revision ID: d42f0d6ab9e1
Revises: b5f3e8c9a12d
Create Date: 2026-07-17 00:00:00.000000

Adds the Weekly Student Reports schema for Parent Experience Phase 8.4.

New tables:
  weekly_student_reports
  weekly_student_report_versions
  weekly_student_report_review_events

The migration is additive and preserves existing data.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "d42f0d6ab9e1"
down_revision: Union[str, None] = "b5f3e8c9a12d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_student_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("timezone_used", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("approved_version_number", sa.Integer(), nullable=True),
        sa.Column("published_version_number", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_reviewer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("published_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "student_id", "week_start", name="uq_weekly_report_per_student_week"),
        sa.CheckConstraint(
            "status IN ('draft','generating','pending_review','changes_requested','approved','published','generation_failed','validation_failed','archived')",
            name="valid_weekly_report_status",
        ),
        sa.CheckConstraint("row_version >= 1", name="valid_weekly_report_row_version"),
    )
    op.create_index("ix_weekly_student_reports_tenant_id", "weekly_student_reports", ["tenant_id"])
    op.create_index("ix_weekly_student_reports_student_id", "weekly_student_reports", ["student_id"])
    op.create_index("ix_weekly_student_reports_week_start", "weekly_student_reports", ["week_start"])
    op.create_index("ix_weekly_student_reports_status", "weekly_student_reports", ["status"])
    op.create_index("ix_weekly_student_reports_updated_at", "weekly_student_reports", ["updated_at"])
    op.create_index("ix_weekly_student_reports_archived_at", "weekly_student_reports", ["archived_at"])

    op.create_table(
        "weekly_student_report_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_student_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("validation_status", sa.String(length=20), nullable=False, server_default=sa.text("'passed'")),
        sa.Column("validation_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("report_id", "version_number", name="uq_weekly_report_version_number"),
        sa.CheckConstraint("source_type IN ('manual','ai_generated','staff_revision')", name="valid_weekly_report_source_type"),
        sa.CheckConstraint("validation_status IN ('passed','failed')", name="valid_weekly_report_validation_status"),
    )
    op.create_index("ix_weekly_student_report_versions_report_id", "weekly_student_report_versions", ["report_id"])
    op.create_index("ix_weekly_student_report_versions_created_at", "weekly_student_report_versions", ["created_at"])

    op.create_table(
        "weekly_student_report_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_student_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "report_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_student_report_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=True),
        sa.Column("new_status", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_weekly_student_report_review_events_report_id", "weekly_student_report_review_events", ["report_id"])
    op.create_index("ix_weekly_student_report_review_events_report_version_id", "weekly_student_report_review_events", ["report_version_id"])
    op.create_index("ix_weekly_student_report_review_events_actor_user_id", "weekly_student_report_review_events", ["actor_user_id"])
    op.create_index("ix_weekly_student_report_review_events_event_type", "weekly_student_report_review_events", ["event_type"])
    op.create_index("ix_weekly_student_report_review_events_created_at", "weekly_student_report_review_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_weekly_student_report_review_events_created_at", table_name="weekly_student_report_review_events")
    op.drop_index("ix_weekly_student_report_review_events_event_type", table_name="weekly_student_report_review_events")
    op.drop_index("ix_weekly_student_report_review_events_actor_user_id", table_name="weekly_student_report_review_events")
    op.drop_index("ix_weekly_student_report_review_events_report_version_id", table_name="weekly_student_report_review_events")
    op.drop_index("ix_weekly_student_report_review_events_report_id", table_name="weekly_student_report_review_events")
    op.drop_table("weekly_student_report_review_events")

    op.drop_index("ix_weekly_student_report_versions_created_at", table_name="weekly_student_report_versions")
    op.drop_index("ix_weekly_student_report_versions_report_id", table_name="weekly_student_report_versions")
    op.drop_table("weekly_student_report_versions")

    op.drop_index("ix_weekly_student_reports_archived_at", table_name="weekly_student_reports")
    op.drop_index("ix_weekly_student_reports_updated_at", table_name="weekly_student_reports")
    op.drop_index("ix_weekly_student_reports_status", table_name="weekly_student_reports")
    op.drop_index("ix_weekly_student_reports_week_start", table_name="weekly_student_reports")
    op.drop_index("ix_weekly_student_reports_student_id", table_name="weekly_student_reports")
    op.drop_index("ix_weekly_student_reports_tenant_id", table_name="weekly_student_reports")
    op.drop_table("weekly_student_reports")
