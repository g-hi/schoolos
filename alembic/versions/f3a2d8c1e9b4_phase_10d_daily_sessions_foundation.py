"""phase_10d_daily_sessions_foundation

Revision ID: f3a2d8c1e9b4
Revises: e7b1c9d4a2f0
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a2d8c1e9b4"
down_revision: Union[str, None] = "e7b1c9d4a2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_school_days",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # timetable_id: the canonical scope (tenant+term+campus).
        # This is the primary operational identity — NOT the version.
        # The version is provenance stored in timetable_version_id.
        sa.Column("timetable_id", sa.UUID(), nullable=False),
        sa.Column("timetable_version_id", sa.UUID(), nullable=False),
        sa.Column("campus_id", sa.UUID(), nullable=True),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("timetable_day_key", sa.String(length=20), nullable=True),
        sa.Column("bell_schedule_id", sa.UUID(), nullable=True),
        sa.Column("is_teaching_day", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("non_teaching_reason", sa.String(length=80), nullable=True),
        # calendar_override_event_id: the OperationalCalendarEvent that caused a
        # non-teaching override (part of the source fingerprint).
        sa.Column("calendar_override_event_id", sa.UUID(), nullable=True),
        sa.Column("calendar_event_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "materialization_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timetable_id"], ["timetables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timetable_version_id"], ["timetable_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bell_schedule_id"], ["bell_schedules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["calendar_override_event_id"],
            ["operational_calendar_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_event_version_id"],
            ["calendar_event_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_operational_school_days_day_of_week",
        ),
        sa.CheckConstraint(
            "materialization_status IN ('pending','complete','stale')",
            name="ck_operational_school_days_mat_status",
        ),
        sa.CheckConstraint(
            "non_teaching_reason IS NULL OR non_teaching_reason IN ("
            "'not_operational_weekday','calendar_non_teaching','public_holiday',"
            "'school_holiday','cancelled','other')",
            name="ck_osd_non_teaching_reason",
        ),
        # Primary identity: one operational day per timetable scope per date.
        # Two published versions (V1, V2) for the same timetable on the same date
        # share one OSD row; timetable_version_id records which version was used.
        sa.UniqueConstraint(
            "tenant_id",
            "timetable_id",
            "school_date",
            name="uq_operational_school_days_timetable_date",
        ),
    )
    op.create_index(
        "ix_operational_school_days_tenant_id",
        "operational_school_days", ["tenant_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_timetable_id",
        "operational_school_days", ["timetable_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_timetable_version_id",
        "operational_school_days", ["timetable_version_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_campus_id",
        "operational_school_days", ["campus_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_school_date",
        "operational_school_days", ["school_date"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_bell_schedule_id",
        "operational_school_days", ["bell_schedule_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_is_teaching_day",
        "operational_school_days", ["is_teaching_day"], unique=False,
    )
    op.create_index(
        "ix_osd_materialization_status",
        "operational_school_days", ["materialization_status"], unique=False,
    )
    op.create_index(
        "ix_osd_calendar_override_event_id",
        "operational_school_days", ["calendar_override_event_id"], unique=False,
    )
    op.create_index(
        "ix_operational_school_days_tenant_date",
        "operational_school_days", ["tenant_id", "school_date"], unique=False,
    )

    op.create_table(
        "daily_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("operational_school_day_id", sa.UUID(), nullable=False),
        sa.Column("timetable_version_assignment_id", sa.UUID(), nullable=True),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column("class_id", sa.String(length=120), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=True),
        sa.Column("teacher_id", sa.String(length=120), nullable=True),
        sa.Column("room_id", sa.String(length=120), nullable=True),
        sa.Column("bell_period_id", sa.UUID(), nullable=True),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("period_start_time", sa.String(length=5), nullable=True),
        sa.Column("period_end_time", sa.String(length=5), nullable=True),
        sa.Column("periods_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parallel_block_id", sa.String(length=120), nullable=True),
        sa.Column("parallel_child_id", sa.String(length=120), nullable=True),
        sa.Column("session_key", sa.String(length=260), nullable=False),
        # class_facing_session_key: deterministic class-facing slot identity.
        # Ordinary sessions: unique per (date, class, period).
        # Parallel children of the same block share the same key.
        # Used by attendance to avoid duplicate class registers.
        sa.Column("class_facing_session_key", sa.String(length=64), nullable=True),
        sa.Column("session_status", sa.String(length=30), nullable=False, server_default="scheduled"),
        sa.Column("override_reason", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operational_school_day_id"], ["operational_school_days.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["timetable_version_assignment_id"],
            ["timetable_version_assignments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["bell_period_id"], ["bell_schedule_periods.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("periods_span > 0", name="ck_daily_sessions_periods_span_positive"),
        sa.CheckConstraint("period_number > 0", name="ck_daily_sessions_period_number_positive"),
        sa.CheckConstraint(
            "session_status IN ('scheduled','cancelled','modified')",
            name="ck_daily_sessions_session_status",
        ),
        sa.UniqueConstraint(
            "tenant_id", "operational_school_day_id", "session_key",
            name="uq_daily_sessions_osd_session_key",
        ),
    )
    op.create_index("ix_daily_sessions_tenant_id", "daily_sessions", ["tenant_id"], unique=False)
    op.create_index(
        "ix_daily_sessions_operational_school_day_id",
        "daily_sessions", ["operational_school_day_id"], unique=False,
    )
    op.create_index(
        "ix_daily_sessions_tva_id",
        "daily_sessions", ["timetable_version_assignment_id"], unique=False,
    )
    op.create_index("ix_daily_sessions_school_date", "daily_sessions", ["school_date"], unique=False)
    op.create_index("ix_daily_sessions_class_id", "daily_sessions", ["class_id"], unique=False)
    op.create_index("ix_daily_sessions_teacher_id", "daily_sessions", ["teacher_id"], unique=False)
    op.create_index(
        "ix_daily_sessions_session_status", "daily_sessions", ["session_status"], unique=False,
    )
    op.create_index(
        "ix_daily_sessions_parallel_block_id", "daily_sessions", ["parallel_block_id"], unique=False,
    )
    op.create_index(
        "ix_daily_sessions_class_facing_key",
        "daily_sessions", ["class_facing_session_key"], unique=False,
    )
    op.create_index(
        "ix_daily_sessions_tenant_date_class",
        "daily_sessions", ["tenant_id", "school_date", "class_id"], unique=False,
    )
    op.create_index(
        "ix_daily_sessions_tenant_date_teacher",
        "daily_sessions", ["tenant_id", "school_date", "teacher_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_sessions_tenant_date_teacher", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_tenant_date_class", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_class_facing_key", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_parallel_block_id", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_session_status", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_teacher_id", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_class_id", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_school_date", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_tva_id", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_operational_school_day_id", table_name="daily_sessions")
    op.drop_index("ix_daily_sessions_tenant_id", table_name="daily_sessions")
    op.drop_table("daily_sessions")

    op.drop_index("ix_operational_school_days_tenant_date", table_name="operational_school_days")
    op.drop_index("ix_osd_calendar_override_event_id", table_name="operational_school_days")
    op.drop_index("ix_osd_materialization_status", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_is_teaching_day", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_bell_schedule_id", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_school_date", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_campus_id", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_timetable_version_id", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_timetable_id", table_name="operational_school_days")
    op.drop_index("ix_operational_school_days_tenant_id", table_name="operational_school_days")
    op.drop_table("operational_school_days")
