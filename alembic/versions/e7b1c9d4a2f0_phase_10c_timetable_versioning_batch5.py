"""phase_10c_timetable_versioning_batch5

Revision ID: e7b1c9d4a2f0
Revises: c3d9a7b2e410
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7b1c9d4a2f0"
down_revision: Union[str, None] = "c3d9a7b2e410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timetables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("term_id", sa.UUID(), nullable=False),
        sa.Column("campus_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_timetables_status"),
        sa.UniqueConstraint("tenant_id", "academic_year_id", "term_id", "campus_id", name="uq_timetables_scope"),
    )
    op.create_index("ix_timetables_tenant_id", "timetables", ["tenant_id"], unique=False)
    op.create_index("ix_timetables_academic_year_id", "timetables", ["academic_year_id"], unique=False)
    op.create_index("ix_timetables_term_id", "timetables", ["term_id"], unique=False)
    op.create_index("ix_timetables_campus_id", "timetables", ["campus_id"], unique=False)
    op.create_index("ix_timetables_status", "timetables", ["status"], unique=False)
    op.create_index("ix_timetables_scope", "timetables", ["tenant_id", "academic_year_id", "term_id", "campus_id", "status"], unique=False)

    op.create_table(
        "timetable_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("timetable_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("generation_configuration_id", sa.UUID(), nullable=True),
        sa.Column("source_candidate_id", sa.String(length=80), nullable=True),
        sa.Column("source_problem_id", sa.String(length=120), nullable=True),
        sa.Column("source_problem_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("source_assignment_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("generation_mode", sa.String(length=30), nullable=False, server_default="standard"),
        sa.Column("baseline_version_id", sa.UUID(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="candidate"),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_user_id", sa.UUID(), nullable=True),
        sa.Column("superseded_by_version_id", sa.UUID(), nullable=True),
        sa.Column("candidate_profile", sa.String(length=60), nullable=True),
        sa.Column("quality_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("repair_impact_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("diff_summary_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("solver_provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["timetable_id"], ["timetables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_configuration_id"], ["timetable_generation_configurations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["baseline_version_id"], ["timetable_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_version_id"], ["timetable_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version_number > 0", name="ck_timetable_versions_version_positive"),
        sa.CheckConstraint("generation_mode IN ('standard','customized','repair')", name="ck_timetable_versions_generation_mode"),
        sa.CheckConstraint("lifecycle_status IN ('candidate','under_review','approved','published','superseded','cancelled')", name="ck_timetable_versions_lifecycle_status"),
        sa.CheckConstraint("effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from", name="ck_timetable_versions_effective_date_range"),
        sa.UniqueConstraint("timetable_id", "version_number", name="uq_timetable_versions_timetable_version_number"),
    )
    op.create_index("ix_timetable_versions_timetable_id", "timetable_versions", ["timetable_id"], unique=False)
    op.create_index("ix_timetable_versions_tenant_id", "timetable_versions", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_versions_generation_configuration_id", "timetable_versions", ["generation_configuration_id"], unique=False)
    op.create_index("ix_timetable_versions_source_candidate_id", "timetable_versions", ["source_candidate_id"], unique=False)
    op.create_index("ix_timetable_versions_generation_mode", "timetable_versions", ["generation_mode"], unique=False)
    op.create_index("ix_timetable_versions_baseline_version_id", "timetable_versions", ["baseline_version_id"], unique=False)
    op.create_index("ix_timetable_versions_lifecycle_status", "timetable_versions", ["lifecycle_status"], unique=False)
    op.create_index("ix_timetable_versions_effective_from", "timetable_versions", ["effective_from"], unique=False)
    op.create_index("ix_timetable_versions_effective_until", "timetable_versions", ["effective_until"], unique=False)
    op.create_index("ix_timetable_versions_superseded_by_version_id", "timetable_versions", ["superseded_by_version_id"], unique=False)
    op.create_index("ix_timetable_versions_created_at", "timetable_versions", ["created_at"], unique=False)
    op.create_index("ix_timetable_versions_scope", "timetable_versions", ["tenant_id", "timetable_id", "lifecycle_status", "effective_from", "effective_until"], unique=False)

    op.create_table(
        "timetable_version_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("timetable_version_id", sa.UUID(), nullable=False),
        sa.Column("occurrence_id", sa.String(length=180), nullable=False),
        sa.Column("requirement_id", sa.String(length=180), nullable=True),
        sa.Column("class_id", sa.String(length=120), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=True),
        sa.Column("teacher_id", sa.String(length=120), nullable=True),
        sa.Column("room_id", sa.String(length=120), nullable=True),
        sa.Column("day_key", sa.String(length=20), nullable=False),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("periods_per_session", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("occupied_period_keys_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("parallel_block_id", sa.String(length=120), nullable=True),
        sa.Column("parallel_child_id", sa.String(length=120), nullable=True),
        sa.Column("fixed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lock_state", sa.String(length=20), nullable=True),
        sa.Column("protection_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("assignment_key", sa.String(length=260), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timetable_version_id"], ["timetable_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("periods_per_session > 0", name="ck_timetable_version_assignments_periods_per_session_positive"),
        sa.CheckConstraint("lock_state IS NULL OR lock_state IN ('locked','prefer_to_keep','flexible')", name="ck_timetable_version_assignments_lock_state"),
        sa.UniqueConstraint("timetable_version_id", "assignment_key", name="uq_timetable_version_assignments_version_assignment_key"),
    )
    op.create_index("ix_timetable_version_assignments_tenant_id", "timetable_version_assignments", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_timetable_version_id", "timetable_version_assignments", ["timetable_version_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_class_id", "timetable_version_assignments", ["class_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_teacher_id", "timetable_version_assignments", ["teacher_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_room_id", "timetable_version_assignments", ["room_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_day_key", "timetable_version_assignments", ["day_key"], unique=False)
    op.create_index("ix_timetable_version_assignments_parallel_block_id", "timetable_version_assignments", ["parallel_block_id"], unique=False)
    op.create_index("ix_timetable_version_assignments_version_class_day", "timetable_version_assignments", ["timetable_version_id", "class_id", "day_key"], unique=False)
    op.create_index("ix_timetable_version_assignments_version_teacher_day", "timetable_version_assignments", ["timetable_version_id", "teacher_id", "day_key"], unique=False)

    op.add_column("timetable_generation_configurations", sa.Column("baseline_timetable_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_tt_gen_cfg_baseline_version",
        "timetable_generation_configurations",
        "timetable_versions",
        ["baseline_timetable_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tt_gen_cfg_baseline_version_id",
        "timetable_generation_configurations",
        ["baseline_timetable_version_id"],
        unique=False,
    )

    op.drop_constraint(
        "ck_timetable_generation_configurations_repair_baseline_required",
        "timetable_generation_configurations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_timetable_generation_configurations_repair_baseline_required",
        "timetable_generation_configurations",
        "generation_mode <> 'repair' OR baseline_reference_id IS NOT NULL OR baseline_timetable_version_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_timetable_generation_configurations_repair_baseline_required",
        "timetable_generation_configurations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_timetable_generation_configurations_repair_baseline_required",
        "timetable_generation_configurations",
        "generation_mode <> 'repair' OR baseline_reference_id IS NOT NULL",
    )

    op.drop_index("ix_tt_gen_cfg_baseline_version_id", table_name="timetable_generation_configurations")
    op.drop_constraint(
        "fk_tt_gen_cfg_baseline_version",
        "timetable_generation_configurations",
        type_="foreignkey",
    )
    op.drop_column("timetable_generation_configurations", "baseline_timetable_version_id")

    op.drop_index("ix_timetable_version_assignments_version_teacher_day", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_version_class_day", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_parallel_block_id", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_day_key", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_room_id", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_teacher_id", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_class_id", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_timetable_version_id", table_name="timetable_version_assignments")
    op.drop_index("ix_timetable_version_assignments_tenant_id", table_name="timetable_version_assignments")
    op.drop_table("timetable_version_assignments")

    op.drop_index("ix_timetable_versions_scope", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_created_at", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_superseded_by_version_id", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_effective_until", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_effective_from", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_lifecycle_status", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_baseline_version_id", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_generation_mode", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_source_candidate_id", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_generation_configuration_id", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_tenant_id", table_name="timetable_versions")
    op.drop_index("ix_timetable_versions_timetable_id", table_name="timetable_versions")
    op.drop_table("timetable_versions")

    op.drop_index("ix_timetables_scope", table_name="timetables")
    op.drop_index("ix_timetables_status", table_name="timetables")
    op.drop_index("ix_timetables_campus_id", table_name="timetables")
    op.drop_index("ix_timetables_term_id", table_name="timetables")
    op.drop_index("ix_timetables_academic_year_id", table_name="timetables")
    op.drop_index("ix_timetables_tenant_id", table_name="timetables")
    op.drop_table("timetables")
