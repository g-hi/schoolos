"""phase_10a_timetable_data_intake_foundation

Revision ID: 9a10b1c2d3e4
Revises: c4f7a8e2d911
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a10b1c2d3e4"
down_revision: Union[str, None] = "c4f7a8e2d911"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("teaching_day_effect", sa.String(length=40), nullable=False, server_default="no_change"),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="pending_review"),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_source_text", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("end_date >= start_date", name="ck_operational_calendar_event_date_range"),
        sa.CheckConstraint("event_type IN ('teaching_day_override','public_holiday','school_holiday','examination_period','professional_development','parent_conference','school_event','half_day','special_schedule','term_boundary','information_only')", name="ck_operational_calendar_event_type"),
        sa.CheckConstraint("teaching_day_effect IN ('no_change','non_teaching_day','teaching_day','special_schedule')", name="ck_operational_calendar_teaching_day_effect"),
        sa.CheckConstraint("source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')", name="ck_operational_calendar_source_type"),
        sa.CheckConstraint("review_status IN ('pending_review','approved','rejected')", name="ck_operational_calendar_review_status"),
    )
    op.create_index("ix_operational_calendar_events_tenant_id", "operational_calendar_events", ["tenant_id"])
    op.create_index("ix_operational_calendar_events_campus_id", "operational_calendar_events", ["campus_id"])
    op.create_index("ix_operational_calendar_events_academic_year_id", "operational_calendar_events", ["academic_year_id"])
    op.create_index("ix_operational_calendar_events_term_id", "operational_calendar_events", ["term_id"])
    op.create_index("ix_operational_calendar_events_event_type", "operational_calendar_events", ["event_type"])
    op.create_index("ix_operational_calendar_events_review_status", "operational_calendar_events", ["review_status"])
    op.create_index("ix_operational_calendar_events_import_batch_id", "operational_calendar_events", ["import_batch_id"])
    op.create_index(
        "uq_operational_calendar_event_active_identity",
        "operational_calendar_events",
        ["tenant_id", "campus_id", "academic_year_id", "term_id", "event_name", "start_date", "end_date", "event_type"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "school_week_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("operational_weekdays", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="approved"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')", name="ck_school_week_source_type"),
        sa.CheckConstraint("review_status IN ('pending_review','approved','rejected')", name="ck_school_week_review_status"),
    )
    op.create_index("ix_school_week_configs_tenant_id", "school_week_configs", ["tenant_id"])
    op.create_index("ix_school_week_configs_campus_id", "school_week_configs", ["campus_id"])
    op.create_index("ix_school_week_configs_academic_year_id", "school_week_configs", ["academic_year_id"])
    op.create_index("ix_school_week_configs_term_id", "school_week_configs", ["term_id"])
    op.create_index(
        "uq_school_week_default_active_scope",
        "school_week_configs",
        ["tenant_id", "campus_id", "academic_year_id", "term_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE AND is_default IS TRUE"),
    )

    op.create_table(
        "bell_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("school_week_config_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("school_week_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("schedule_type", sa.String(length=50), nullable=False, server_default="normal"),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="approved"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date", name="ck_bell_schedule_effective_date_range"),
        sa.CheckConstraint("source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')", name="ck_bell_schedule_source_type"),
        sa.CheckConstraint("review_status IN ('pending_review','approved','rejected')", name="ck_bell_schedule_review_status"),
    )
    op.create_index("ix_bell_schedules_tenant_id", "bell_schedules", ["tenant_id"])
    op.create_index("ix_bell_schedules_campus_id", "bell_schedules", ["campus_id"])
    op.create_index("ix_bell_schedules_academic_year_id", "bell_schedules", ["academic_year_id"])
    op.create_index("ix_bell_schedules_term_id", "bell_schedules", ["term_id"])
    op.create_index("ix_bell_schedules_school_week_config_id", "bell_schedules", ["school_week_config_id"])
    op.create_index(
        "uq_bell_schedule_default_active_scope",
        "bell_schedules",
        ["tenant_id", "campus_id", "academic_year_id", "term_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE AND is_default IS TRUE"),
    )

    op.create_table(
        "bell_schedule_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bell_schedule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bell_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("applicable_grade_level_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grade_levels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("is_teaching_period", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_break", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_lunch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("period_number > 0", name="ck_bell_schedule_period_number_positive"),
    )
    op.create_index("ix_bell_schedule_periods_tenant_id", "bell_schedule_periods", ["tenant_id"])
    op.create_index("ix_bell_schedule_periods_bell_schedule_id", "bell_schedule_periods", ["bell_schedule_id"])
    op.create_index("ix_bell_schedule_periods_applicable_grade_level_id", "bell_schedule_periods", ["applicable_grade_level_id"])
    op.create_index(
        "uq_bell_schedule_period_number_active",
        "bell_schedule_periods",
        ["tenant_id", "bell_schedule_id", "period_number"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "teaching_rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("room_code", sa.String(length=50), nullable=False),
        sa.Column("room_name", sa.String(length=255), nullable=False),
        sa.Column("room_type", sa.String(length=50), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("floor_or_location", sa.String(length=120), nullable=True),
        sa.Column("specialist_capabilities", sa.JSON(), nullable=False),
        sa.Column("accessibility_notes", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="approved"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("capacity >= 0", name="ck_teaching_rooms_capacity_non_negative"),
        sa.CheckConstraint("room_type IN ('standard_classroom','science_lab','computer_lab','art_room','music_room','sports_space','library','examination_hall','multipurpose','virtual')", name="ck_teaching_rooms_room_type"),
        sa.CheckConstraint("source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')", name="ck_teaching_rooms_source_type"),
        sa.CheckConstraint("review_status IN ('pending_review','approved','rejected')", name="ck_teaching_rooms_review_status"),
        sa.UniqueConstraint("tenant_id", "campus_id", "room_code", name="uq_teaching_rooms_code_per_scope"),
    )
    op.create_index("ix_teaching_rooms_tenant_id", "teaching_rooms", ["tenant_id"])
    op.create_index("ix_teaching_rooms_campus_id", "teaching_rooms", ["campus_id"])

    op.create_table(
        "weekly_teaching_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sessions_per_week", sa.Integer(), nullable=False),
        sa.Column("periods_per_session", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_daily_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_daily_sessions", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("double_period_mode", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("specialist_room_type", sa.String(length=50), nullable=True),
        sa.Column("preferred_period_numbers", sa.JSON(), nullable=False),
        sa.Column("forbidden_period_numbers", sa.JSON(), nullable=False),
        sa.Column("has_fixed_sessions", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fixed_session_rules", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="approved"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sessions_per_week > 0", name="ck_weekly_teaching_requirements_sessions_positive"),
        sa.CheckConstraint("periods_per_session > 0", name="ck_weekly_teaching_requirements_periods_per_session_positive"),
        sa.CheckConstraint("min_daily_sessions >= 0", name="ck_weekly_teaching_requirements_min_daily_non_negative"),
        sa.CheckConstraint("max_daily_sessions >= min_daily_sessions", name="ck_weekly_teaching_requirements_daily_bounds"),
        sa.CheckConstraint("priority > 0", name="ck_weekly_teaching_requirements_priority_positive"),
        sa.CheckConstraint("double_period_mode IN ('none','preferred','required')", name="ck_weekly_teaching_requirements_double_period_mode"),
        sa.CheckConstraint("source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')", name="ck_weekly_teaching_requirements_source_type"),
        sa.CheckConstraint("review_status IN ('pending_review','approved','rejected')", name="ck_weekly_teaching_requirements_review_status"),
    )
    op.create_index("ix_weekly_teaching_requirements_tenant_id", "weekly_teaching_requirements", ["tenant_id"])
    op.create_index("ix_weekly_teaching_requirements_campus_id", "weekly_teaching_requirements", ["campus_id"])
    op.create_index("ix_weekly_teaching_requirements_academic_year_id", "weekly_teaching_requirements", ["academic_year_id"])
    op.create_index("ix_weekly_teaching_requirements_term_id", "weekly_teaching_requirements", ["term_id"])
    op.create_index("ix_weekly_teaching_requirements_class_id", "weekly_teaching_requirements", ["class_id"])
    op.create_index("ix_weekly_teaching_requirements_subject_id", "weekly_teaching_requirements", ["subject_id"])
    op.create_index("ix_weekly_teaching_requirements_teacher_id", "weekly_teaching_requirements", ["teacher_id"])
    op.create_index(
        "uq_weekly_teaching_requirements_active_identity",
        "weekly_teaching_requirements",
        ["tenant_id", "campus_id", "academic_year_id", "term_id", "class_id", "subject_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_weekly_teaching_requirements_active_identity", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_teacher_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_subject_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_class_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_term_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_academic_year_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_campus_id", table_name="weekly_teaching_requirements")
    op.drop_index("ix_weekly_teaching_requirements_tenant_id", table_name="weekly_teaching_requirements")
    op.drop_table("weekly_teaching_requirements")

    op.drop_index("ix_teaching_rooms_campus_id", table_name="teaching_rooms")
    op.drop_index("ix_teaching_rooms_tenant_id", table_name="teaching_rooms")
    op.drop_table("teaching_rooms")

    op.drop_index("uq_bell_schedule_period_number_active", table_name="bell_schedule_periods")
    op.drop_index("ix_bell_schedule_periods_applicable_grade_level_id", table_name="bell_schedule_periods")
    op.drop_index("ix_bell_schedule_periods_bell_schedule_id", table_name="bell_schedule_periods")
    op.drop_index("ix_bell_schedule_periods_tenant_id", table_name="bell_schedule_periods")
    op.drop_table("bell_schedule_periods")

    op.drop_index("uq_bell_schedule_default_active_scope", table_name="bell_schedules")
    op.drop_index("ix_bell_schedules_school_week_config_id", table_name="bell_schedules")
    op.drop_index("ix_bell_schedules_term_id", table_name="bell_schedules")
    op.drop_index("ix_bell_schedules_academic_year_id", table_name="bell_schedules")
    op.drop_index("ix_bell_schedules_campus_id", table_name="bell_schedules")
    op.drop_index("ix_bell_schedules_tenant_id", table_name="bell_schedules")
    op.drop_table("bell_schedules")

    op.drop_index("uq_school_week_default_active_scope", table_name="school_week_configs")
    op.drop_index("ix_school_week_configs_term_id", table_name="school_week_configs")
    op.drop_index("ix_school_week_configs_academic_year_id", table_name="school_week_configs")
    op.drop_index("ix_school_week_configs_campus_id", table_name="school_week_configs")
    op.drop_index("ix_school_week_configs_tenant_id", table_name="school_week_configs")
    op.drop_table("school_week_configs")

    op.drop_index("uq_operational_calendar_event_active_identity", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_import_batch_id", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_review_status", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_event_type", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_term_id", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_academic_year_id", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_campus_id", table_name="operational_calendar_events")
    op.drop_index("ix_operational_calendar_events_tenant_id", table_name="operational_calendar_events")
    op.drop_table("operational_calendar_events")
