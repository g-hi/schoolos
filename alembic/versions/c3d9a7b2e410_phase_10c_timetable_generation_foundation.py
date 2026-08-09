"""phase_10c_timetable_generation_foundation

Revision ID: c3d9a7b2e410
Revises: a84f2c1d9e30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3d9a7b2e410"
down_revision: Union[str, None] = "a84f2c1d9e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"timetable_generation_configurations",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("academic_year_id", sa.UUID(), nullable=False),
		sa.Column("term_id", sa.UUID(), nullable=False),
		sa.Column("campus_id", sa.UUID(), nullable=True),
		sa.Column("bell_schedule_id", sa.UUID(), nullable=True),
		sa.Column("name", sa.String(length=160), nullable=False),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column("generation_mode", sa.String(length=30), nullable=False, server_default="standard"),
		sa.Column("stability_mode", sa.String(length=20), nullable=False, server_default="balanced"),
		sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="draft"),
		sa.Column("baseline_reference_type", sa.String(length=40), nullable=True),
		sa.Column("baseline_reference_id", sa.UUID(), nullable=True),
		sa.Column("effective_start_date", sa.Date(), nullable=True),
		sa.Column("effective_end_date", sa.Date(), nullable=True),
		sa.Column("objective_priorities_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("repair_scope_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("effective_context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("validation_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
		sa.Column("created_by_user_id", sa.UUID(), nullable=True),
		sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
		sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
		sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("superseded_by_configuration_id", sa.UUID(), nullable=True),
		sa.Column("cancellation_reason", sa.Text(), nullable=True),
		sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["bell_schedule_id"], ["bell_schedules.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["superseded_by_configuration_id"], ["timetable_generation_configurations.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"generation_mode IN ('standard','customized','repair')",
			name="ck_timetable_generation_configurations_mode",
		),
		sa.CheckConstraint(
			"stability_mode IN ('very_high','high','balanced','flexible')",
			name="ck_timetable_generation_configurations_stability_mode",
		),
		sa.CheckConstraint(
			"lifecycle_status IN ('draft','ready_for_review','approved','superseded','cancelled')",
			name="ck_timetable_generation_configurations_lifecycle_status",
		),
		sa.CheckConstraint(
			"source_type IN ('manual','imported','agent_proposal','system_generated')",
			name="ck_timetable_generation_configurations_source_type",
		),
		sa.CheckConstraint(
			"effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
			name="ck_timetable_generation_configurations_effective_date_range",
		),
		sa.CheckConstraint("version_number > 0", name="ck_timetable_generation_configurations_version_positive"),
		sa.CheckConstraint(
			"generation_mode <> 'repair' OR baseline_reference_id IS NOT NULL",
			name="ck_timetable_generation_configurations_repair_baseline_required",
		),
	)
	op.create_index("ix_timetable_generation_configurations_tenant_id", "timetable_generation_configurations", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_generation_configurations_academic_year_id", "timetable_generation_configurations", ["academic_year_id"], unique=False)
	op.create_index("ix_timetable_generation_configurations_term_id", "timetable_generation_configurations", ["term_id"], unique=False)
	op.create_index("ix_timetable_generation_configurations_campus_id", "timetable_generation_configurations", ["campus_id"], unique=False)
	op.create_index("ix_timetable_generation_configurations_bell_schedule_id", "timetable_generation_configurations", ["bell_schedule_id"], unique=False)
	op.create_index("ix_timetable_generation_configurations_generation_mode", "timetable_generation_configurations", ["generation_mode"], unique=False)
	op.create_index("ix_timetable_generation_configurations_lifecycle_status", "timetable_generation_configurations", ["lifecycle_status"], unique=False)
	op.create_index("ix_timetable_generation_configurations_baseline_reference_id", "timetable_generation_configurations", ["baseline_reference_id"], unique=False)
	op.create_index(
		"ix_timetable_generation_configurations_scope_status",
		"timetable_generation_configurations",
		["tenant_id", "academic_year_id", "term_id", "campus_id", "lifecycle_status"],
		unique=False,
	)

	op.create_table(
		"timetable_generation_objectives",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("configuration_id", sa.UUID(), nullable=False),
		sa.Column("objective_key", sa.String(length=60), nullable=False),
		sa.Column("priority_level", sa.String(length=20), nullable=False),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["configuration_id"], ["timetable_generation_configurations.id"], ondelete="CASCADE"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"objective_key IN ('satisfy_hard_constraints','teacher_preferences','workload_balance','subject_distribution','minimize_teacher_gaps','minimize_room_changes','minimize_timetable_disruption','preference_fairness','preserve_existing_assignments')",
			name="ck_timetable_generation_objectives_key",
		),
		sa.CheckConstraint(
			"priority_level IN ('critical','high','normal','low')",
			name="ck_timetable_generation_objectives_priority",
		),
		sa.UniqueConstraint("configuration_id", "objective_key", name="uq_timetable_generation_objectives_configuration_key"),
	)
	op.create_index("ix_timetable_generation_objectives_tenant_id", "timetable_generation_objectives", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_generation_objectives_configuration_id", "timetable_generation_objectives", ["configuration_id"], unique=False)

	op.create_table(
		"timetable_teacher_scheduling_preferences",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("teacher_id", sa.UUID(), nullable=False),
		sa.Column("academic_year_id", sa.UUID(), nullable=False),
		sa.Column("term_id", sa.UUID(), nullable=False),
		sa.Column("campus_id", sa.UUID(), nullable=True),
		sa.Column("preference_type", sa.String(length=40), nullable=False),
		sa.Column("strength", sa.String(length=20), nullable=False, server_default="normal"),
		sa.Column("weekdays_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
		sa.Column("period_numbers_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
		sa.Column("effective_start_date", sa.Date(), nullable=True),
		sa.Column("effective_end_date", sa.Date(), nullable=True),
		sa.Column("temporary_accommodation_text", sa.Text(), nullable=True),
		sa.Column("leadership_note", sa.Text(), nullable=True),
		sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
		sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("created_by_user_id", sa.UUID(), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"preference_type IN ('avoid_first_period','avoid_last_period','avoid_selected_periods','prefer_selected_periods','unavailable_selected_periods','prefer_grouped_free_periods','prefer_selected_days','avoid_selected_days','temporary_accommodation')",
			name="ck_timetable_teacher_preferences_type",
		),
		sa.CheckConstraint(
			"strength IN ('hard','strong','normal','low')",
			name="ck_timetable_teacher_preferences_strength",
		),
		sa.CheckConstraint(
			"source_type IN ('manual','imported','agent_proposal','system_generated')",
			name="ck_timetable_teacher_preferences_source_type",
		),
		sa.CheckConstraint(
			"effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
			name="ck_timetable_teacher_preferences_effective_date_range",
		),
	)
	op.create_index("ix_timetable_teacher_scheduling_preferences_tenant_id", "timetable_teacher_scheduling_preferences", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_teacher_id", "timetable_teacher_scheduling_preferences", ["teacher_id"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_academic_year_id", "timetable_teacher_scheduling_preferences", ["academic_year_id"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_term_id", "timetable_teacher_scheduling_preferences", ["term_id"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_campus_id", "timetable_teacher_scheduling_preferences", ["campus_id"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_preference_type", "timetable_teacher_scheduling_preferences", ["preference_type"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_strength", "timetable_teacher_scheduling_preferences", ["strength"], unique=False)
	op.create_index("ix_timetable_teacher_scheduling_preferences_is_active", "timetable_teacher_scheduling_preferences", ["is_active"], unique=False)

	op.create_table(
		"timetable_generation_overrides",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("configuration_id", sa.UUID(), nullable=False),
		sa.Column("override_type", sa.String(length=40), nullable=False),
		sa.Column("strength", sa.String(length=20), nullable=False, server_default="normal"),
		sa.Column("scope_type", sa.String(length=30), nullable=False),
		sa.Column("scope_reference_id", sa.UUID(), nullable=True),
		sa.Column("scope_reference_code", sa.String(length=120), nullable=True),
		sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
		sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("created_by_user_id", sa.UUID(), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["configuration_id"], ["timetable_generation_configurations.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"override_type IN ('teacher_free_period','class_subject_timing_preference','room_avoidance','repair_assignment_protection','other_override')",
			name="ck_timetable_generation_overrides_type",
		),
		sa.CheckConstraint(
			"strength IN ('hard','strong','normal','low')",
			name="ck_timetable_generation_overrides_strength",
		),
		sa.CheckConstraint(
			"scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','day','period','period_range','session_reference')",
			name="ck_timetable_generation_overrides_scope_type",
		),
		sa.CheckConstraint(
			"source_type IN ('manual','imported','agent_proposal','system_generated')",
			name="ck_timetable_generation_overrides_source_type",
		),
	)
	op.create_index("ix_timetable_generation_overrides_tenant_id", "timetable_generation_overrides", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_generation_overrides_configuration_id", "timetable_generation_overrides", ["configuration_id"], unique=False)
	op.create_index("ix_timetable_generation_overrides_override_type", "timetable_generation_overrides", ["override_type"], unique=False)
	op.create_index("ix_timetable_generation_overrides_strength", "timetable_generation_overrides", ["strength"], unique=False)
	op.create_index("ix_timetable_generation_overrides_scope_type", "timetable_generation_overrides", ["scope_type"], unique=False)
	op.create_index("ix_timetable_generation_overrides_scope_reference_id", "timetable_generation_overrides", ["scope_reference_id"], unique=False)
	op.create_index("ix_timetable_generation_overrides_is_active", "timetable_generation_overrides", ["is_active"], unique=False)

	op.create_table(
		"timetable_generation_locks",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("configuration_id", sa.UUID(), nullable=False),
		sa.Column("lock_state", sa.String(length=20), nullable=False, server_default="flexible"),
		sa.Column("target_type", sa.String(length=30), nullable=False),
		sa.Column("target_reference_id", sa.UUID(), nullable=True),
		sa.Column("target_reference_code", sa.String(length=120), nullable=True),
		sa.Column("day_of_week", sa.Integer(), nullable=True),
		sa.Column("period_number", sa.Integer(), nullable=True),
		sa.Column("period_end_number", sa.Integer(), nullable=True),
		sa.Column("is_manual_hard_lock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
		sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("created_by_user_id", sa.UUID(), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["configuration_id"], ["timetable_generation_configurations.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"lock_state IN ('locked','prefer_to_keep','flexible')",
			name="ck_timetable_generation_locks_state",
		),
		sa.CheckConstraint(
			"target_type IN ('session_reference','teacher','class','subject','grade','room','day','period','period_range')",
			name="ck_timetable_generation_locks_target_type",
		),
		sa.CheckConstraint("day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)", name="ck_timetable_generation_locks_day_of_week"),
		sa.CheckConstraint("period_number IS NULL OR period_number > 0", name="ck_timetable_generation_locks_period_number_positive"),
		sa.CheckConstraint(
			"period_end_number IS NULL OR period_number IS NULL OR period_end_number >= period_number",
			name="ck_timetable_generation_locks_period_range",
		),
		sa.CheckConstraint(
			"source_type IN ('manual','imported','agent_proposal','system_generated')",
			name="ck_timetable_generation_locks_source_type",
		),
	)
	op.create_index("ix_timetable_generation_locks_tenant_id", "timetable_generation_locks", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_generation_locks_configuration_id", "timetable_generation_locks", ["configuration_id"], unique=False)
	op.create_index("ix_timetable_generation_locks_lock_state", "timetable_generation_locks", ["lock_state"], unique=False)
	op.create_index("ix_timetable_generation_locks_target_type", "timetable_generation_locks", ["target_type"], unique=False)
	op.create_index("ix_timetable_generation_locks_target_reference_id", "timetable_generation_locks", ["target_reference_id"], unique=False)
	op.create_index("ix_timetable_generation_locks_is_active", "timetable_generation_locks", ["is_active"], unique=False)

	op.create_table(
		"timetable_parallel_lesson_blocks",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("academic_year_id", sa.UUID(), nullable=False),
		sa.Column("term_id", sa.UUID(), nullable=False),
		sa.Column("campus_id", sa.UUID(), nullable=True),
		sa.Column("class_id", sa.UUID(), nullable=False),
		sa.Column("display_label", sa.String(length=160), nullable=False),
		sa.Column("block_type", sa.String(length=30), nullable=False),
		sa.Column("synchronization_requirement", sa.String(length=30), nullable=False, server_default="same_period"),
		sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
		sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("created_by_user_id", sa.UUID(), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="RESTRICT"),
		sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"block_type IN ('foreign_language','electives','split_class','other_parallel')",
			name="ck_timetable_parallel_blocks_type",
		),
		sa.CheckConstraint(
			"synchronization_requirement IN ('same_period','same_day')",
			name="ck_timetable_parallel_blocks_sync_requirement",
		),
		sa.CheckConstraint(
			"source_type IN ('manual','imported','agent_proposal','system_generated')",
			name="ck_timetable_parallel_blocks_source_type",
		),
	)
	op.create_index("ix_timetable_parallel_lesson_blocks_tenant_id", "timetable_parallel_lesson_blocks", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_academic_year_id", "timetable_parallel_lesson_blocks", ["academic_year_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_term_id", "timetable_parallel_lesson_blocks", ["term_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_campus_id", "timetable_parallel_lesson_blocks", ["campus_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_class_id", "timetable_parallel_lesson_blocks", ["class_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_block_type", "timetable_parallel_lesson_blocks", ["block_type"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_blocks_is_active", "timetable_parallel_lesson_blocks", ["is_active"], unique=False)

	op.create_table(
		"timetable_parallel_lesson_children",
		sa.Column("id", sa.UUID(), nullable=False),
		sa.Column("tenant_id", sa.UUID(), nullable=False),
		sa.Column("parallel_block_id", sa.UUID(), nullable=False),
		sa.Column("requirement_id", sa.UUID(), nullable=True),
		sa.Column("subject_id", sa.UUID(), nullable=True),
		sa.Column("teacher_id", sa.UUID(), nullable=True),
		sa.Column("room_id", sa.UUID(), nullable=True),
		sa.Column("sequence_order", sa.Integer(), nullable=True),
		sa.Column("requirement_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["parallel_block_id"], ["timetable_parallel_lesson_blocks.id"], ondelete="CASCADE"),
		sa.ForeignKeyConstraint(["requirement_id"], ["weekly_teaching_requirements.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["room_id"], ["teaching_rooms.id"], ondelete="SET NULL"),
		sa.PrimaryKeyConstraint("id"),
		sa.CheckConstraint(
			"(requirement_id IS NOT NULL) OR (subject_id IS NOT NULL)",
			name="ck_timetable_parallel_children_requirement_or_subject",
		),
		sa.CheckConstraint(
			"sequence_order IS NULL OR sequence_order > 0",
			name="ck_timetable_parallel_children_sequence_positive",
		),
	)
	op.create_index("ix_timetable_parallel_lesson_children_tenant_id", "timetable_parallel_lesson_children", ["tenant_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_parallel_block_id", "timetable_parallel_lesson_children", ["parallel_block_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_requirement_id", "timetable_parallel_lesson_children", ["requirement_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_subject_id", "timetable_parallel_lesson_children", ["subject_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_teacher_id", "timetable_parallel_lesson_children", ["teacher_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_room_id", "timetable_parallel_lesson_children", ["room_id"], unique=False)
	op.create_index("ix_timetable_parallel_lesson_children_is_active", "timetable_parallel_lesson_children", ["is_active"], unique=False)


def downgrade() -> None:
	op.drop_index("ix_timetable_parallel_lesson_children_is_active", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_room_id", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_teacher_id", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_subject_id", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_requirement_id", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_parallel_block_id", table_name="timetable_parallel_lesson_children")
	op.drop_index("ix_timetable_parallel_lesson_children_tenant_id", table_name="timetable_parallel_lesson_children")
	op.drop_table("timetable_parallel_lesson_children")

	op.drop_index("ix_timetable_parallel_lesson_blocks_is_active", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_block_type", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_class_id", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_campus_id", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_term_id", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_academic_year_id", table_name="timetable_parallel_lesson_blocks")
	op.drop_index("ix_timetable_parallel_lesson_blocks_tenant_id", table_name="timetable_parallel_lesson_blocks")
	op.drop_table("timetable_parallel_lesson_blocks")

	op.drop_index("ix_timetable_generation_locks_is_active", table_name="timetable_generation_locks")
	op.drop_index("ix_timetable_generation_locks_target_reference_id", table_name="timetable_generation_locks")
	op.drop_index("ix_timetable_generation_locks_target_type", table_name="timetable_generation_locks")
	op.drop_index("ix_timetable_generation_locks_lock_state", table_name="timetable_generation_locks")
	op.drop_index("ix_timetable_generation_locks_configuration_id", table_name="timetable_generation_locks")
	op.drop_index("ix_timetable_generation_locks_tenant_id", table_name="timetable_generation_locks")
	op.drop_table("timetable_generation_locks")

	op.drop_index("ix_timetable_generation_overrides_is_active", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_scope_reference_id", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_scope_type", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_strength", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_override_type", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_configuration_id", table_name="timetable_generation_overrides")
	op.drop_index("ix_timetable_generation_overrides_tenant_id", table_name="timetable_generation_overrides")
	op.drop_table("timetable_generation_overrides")

	op.drop_index("ix_timetable_teacher_scheduling_preferences_is_active", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_strength", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_preference_type", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_campus_id", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_term_id", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_academic_year_id", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_teacher_id", table_name="timetable_teacher_scheduling_preferences")
	op.drop_index("ix_timetable_teacher_scheduling_preferences_tenant_id", table_name="timetable_teacher_scheduling_preferences")
	op.drop_table("timetable_teacher_scheduling_preferences")

	op.drop_index("ix_timetable_generation_objectives_configuration_id", table_name="timetable_generation_objectives")
	op.drop_index("ix_timetable_generation_objectives_tenant_id", table_name="timetable_generation_objectives")
	op.drop_table("timetable_generation_objectives")

	op.drop_index("ix_timetable_generation_configurations_scope_status", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_baseline_reference_id", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_lifecycle_status", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_generation_mode", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_bell_schedule_id", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_campus_id", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_term_id", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_academic_year_id", table_name="timetable_generation_configurations")
	op.drop_index("ix_timetable_generation_configurations_tenant_id", table_name="timetable_generation_configurations")
	op.drop_table("timetable_generation_configurations")
