"""phase_10b_timetable_policy_constraints_foundation

Revision ID: a84f2c1d9e30
Revises: f91c2d7a6b55
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a84f2c1d9e30"
down_revision: Union[str, None] = "f91c2d7a6b55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timetable_policy_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("term_id", sa.UUID(), nullable=False),
        sa.Column("campus_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campus_id"], ["campuses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft','pending_review','approved','active','suspended','retired')",
            name="ck_timetable_policy_sets_lifecycle_status",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_timetable_policy_sets_version_positive"),
        sa.CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_policy_sets_effective_date_range",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_default','approved_exception')",
            name="ck_timetable_policy_sets_source_type",
        ),
    )
    op.create_index("ix_timetable_policy_sets_tenant_id", "timetable_policy_sets", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_policy_sets_academic_year_id", "timetable_policy_sets", ["academic_year_id"], unique=False)
    op.create_index("ix_timetable_policy_sets_term_id", "timetable_policy_sets", ["term_id"], unique=False)
    op.create_index("ix_timetable_policy_sets_campus_id", "timetable_policy_sets", ["campus_id"], unique=False)
    op.create_index("ix_timetable_policy_sets_lifecycle_status", "timetable_policy_sets", ["lifecycle_status"], unique=False)
    op.create_index("ix_timetable_policy_sets_is_active", "timetable_policy_sets", ["is_active"], unique=False)
    op.create_index(
        "uq_timetable_policy_sets_active_scope",
        "timetable_policy_sets",
        ["tenant_id", "academic_year_id", "term_id", "campus_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE AND lifecycle_status = 'active'"),
    )

    op.create_table(
        "timetable_policy_set_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("policy_set_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("new_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("approval_actor_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_set_id"], ["timetable_policy_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version_number > 0", name="ck_timetable_policy_set_versions_version_positive"),
        sa.CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','activated','suspended','retired')",
            name="ck_timetable_policy_set_versions_change_type",
        ),
        sa.UniqueConstraint("policy_set_id", "version_number", "change_type", name="uq_timetable_policy_set_versions_event_version_change"),
    )
    op.create_index("ix_timetable_policy_set_versions_tenant_id", "timetable_policy_set_versions", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_policy_set_versions_policy_set_id", "timetable_policy_set_versions", ["policy_set_id"], unique=False)
    op.create_index("ix_timetable_policy_set_versions_change_type", "timetable_policy_set_versions", ["change_type"], unique=False)

    op.create_table(
        "timetable_policy_constraints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("policy_set_id", sa.UUID(), nullable=False),
        sa.Column("constraint_type", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("enforcement_level", sa.String(length=20), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("scope_reference_id", sa.UUID(), nullable=True),
        sa.Column("scope_reference_code", sa.String(length=120), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_set_id"], ["timetable_policy_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ('resource','teacher','class','subject','room','time','workload','distribution','curriculum','campus','policy','preference')",
            name="ck_timetable_policy_constraints_category",
        ),
        sa.CheckConstraint(
            "enforcement_level IN ('hard','soft','preference','advisory')",
            name="ck_timetable_policy_constraints_enforcement_level",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft','pending_review','approved','active','suspended','retired')",
            name="ck_timetable_policy_constraints_lifecycle_status",
        ),
        sa.CheckConstraint(
            "scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','period','policy_set')",
            name="ck_timetable_policy_constraints_scope_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual','imported','agent_proposal','system_default','approved_exception')",
            name="ck_timetable_policy_constraints_source_type",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_timetable_policy_constraints_version_positive"),
        sa.CheckConstraint("weight > 0 AND weight <= 1000", name="ck_timetable_policy_constraints_weight_bounds"),
        sa.CheckConstraint("priority > 0 AND priority <= 1000", name="ck_timetable_policy_constraints_priority_bounds"),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)",
            name="ck_timetable_policy_constraints_confidence_score",
        ),
        sa.CheckConstraint(
            "effective_end_date IS NULL OR effective_start_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_timetable_policy_constraints_effective_date_range",
        ),
    )
    op.create_index("ix_timetable_policy_constraints_tenant_id", "timetable_policy_constraints", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_policy_constraints_policy_set_id", "timetable_policy_constraints", ["policy_set_id"], unique=False)
    op.create_index("ix_timetable_policy_constraints_constraint_type", "timetable_policy_constraints", ["constraint_type"], unique=False)
    op.create_index("ix_timetable_policy_constraints_category", "timetable_policy_constraints", ["category"], unique=False)
    op.create_index("ix_timetable_policy_constraints_enforcement_level", "timetable_policy_constraints", ["enforcement_level"], unique=False)
    op.create_index("ix_timetable_policy_constraints_lifecycle_status", "timetable_policy_constraints", ["lifecycle_status"], unique=False)
    op.create_index("ix_timetable_policy_constraints_scope_type", "timetable_policy_constraints", ["scope_type"], unique=False)
    op.create_index("ix_timetable_policy_constraints_scope_reference_id", "timetable_policy_constraints", ["scope_reference_id"], unique=False)
    op.create_index("ix_timetable_policy_constraints_is_active", "timetable_policy_constraints", ["is_active"], unique=False)

    op.create_table(
        "timetable_policy_constraint_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("constraint_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("new_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("approval_actor_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["constraint_id"], ["timetable_policy_constraints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version_number > 0", name="ck_timetable_policy_constraint_versions_version_positive"),
        sa.CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','activated','suspended','retired')",
            name="ck_timetable_policy_constraint_versions_change_type",
        ),
        sa.UniqueConstraint("constraint_id", "version_number", "change_type", name="uq_timetable_policy_constraint_versions_event_version_change"),
    )
    op.create_index("ix_timetable_policy_constraint_versions_tenant_id", "timetable_policy_constraint_versions", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_policy_constraint_versions_constraint_id", "timetable_policy_constraint_versions", ["constraint_id"], unique=False)
    op.create_index("ix_timetable_policy_constraint_versions_change_type", "timetable_policy_constraint_versions", ["change_type"], unique=False)

    op.create_table(
        "timetable_policy_exceptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("policy_set_id", sa.UUID(), nullable=True),
        sa.Column("constraint_id", sa.UUID(), nullable=True),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("scope_reference_id", sa.UUID(), nullable=True),
        sa.Column("scope_reference_code", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("approval_state", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_set_id"], ["timetable_policy_sets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["constraint_id"], ["timetable_policy_constraints.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "scope_type IN ('whole_school','campus','department','grade','class','subject','teacher','room','period','policy_set')",
            name="ck_timetable_policy_exceptions_scope_type",
        ),
        sa.CheckConstraint(
            "approval_state IN ('draft','pending_review','approved','rejected','revoked')",
            name="ck_timetable_policy_exceptions_approval_state",
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_timetable_policy_exceptions_date_range",
        ),
        sa.CheckConstraint(
            "(policy_set_id IS NOT NULL) <> (constraint_id IS NOT NULL)",
            name="ck_timetable_policy_exceptions_single_target",
        ),
    )
    op.create_index("ix_timetable_policy_exceptions_tenant_id", "timetable_policy_exceptions", ["tenant_id"], unique=False)
    op.create_index("ix_timetable_policy_exceptions_policy_set_id", "timetable_policy_exceptions", ["policy_set_id"], unique=False)
    op.create_index("ix_timetable_policy_exceptions_constraint_id", "timetable_policy_exceptions", ["constraint_id"], unique=False)
    op.create_index("ix_timetable_policy_exceptions_scope_type", "timetable_policy_exceptions", ["scope_type"], unique=False)
    op.create_index("ix_timetable_policy_exceptions_scope_reference_id", "timetable_policy_exceptions", ["scope_reference_id"], unique=False)
    op.create_index("ix_timetable_policy_exceptions_approval_state", "timetable_policy_exceptions", ["approval_state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_timetable_policy_exceptions_approval_state", table_name="timetable_policy_exceptions")
    op.drop_index("ix_timetable_policy_exceptions_scope_reference_id", table_name="timetable_policy_exceptions")
    op.drop_index("ix_timetable_policy_exceptions_scope_type", table_name="timetable_policy_exceptions")
    op.drop_index("ix_timetable_policy_exceptions_constraint_id", table_name="timetable_policy_exceptions")
    op.drop_index("ix_timetable_policy_exceptions_policy_set_id", table_name="timetable_policy_exceptions")
    op.drop_index("ix_timetable_policy_exceptions_tenant_id", table_name="timetable_policy_exceptions")
    op.drop_table("timetable_policy_exceptions")

    op.drop_index("ix_timetable_policy_constraint_versions_change_type", table_name="timetable_policy_constraint_versions")
    op.drop_index("ix_timetable_policy_constraint_versions_constraint_id", table_name="timetable_policy_constraint_versions")
    op.drop_index("ix_timetable_policy_constraint_versions_tenant_id", table_name="timetable_policy_constraint_versions")
    op.drop_table("timetable_policy_constraint_versions")

    op.drop_index("ix_timetable_policy_constraints_is_active", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_scope_reference_id", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_scope_type", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_lifecycle_status", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_enforcement_level", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_category", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_constraint_type", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_policy_set_id", table_name="timetable_policy_constraints")
    op.drop_index("ix_timetable_policy_constraints_tenant_id", table_name="timetable_policy_constraints")
    op.drop_table("timetable_policy_constraints")

    op.drop_index("ix_timetable_policy_set_versions_change_type", table_name="timetable_policy_set_versions")
    op.drop_index("ix_timetable_policy_set_versions_policy_set_id", table_name="timetable_policy_set_versions")
    op.drop_index("ix_timetable_policy_set_versions_tenant_id", table_name="timetable_policy_set_versions")
    op.drop_table("timetable_policy_set_versions")

    op.drop_index("uq_timetable_policy_sets_active_scope", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_is_active", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_lifecycle_status", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_campus_id", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_term_id", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_academic_year_id", table_name="timetable_policy_sets")
    op.drop_index("ix_timetable_policy_sets_tenant_id", table_name="timetable_policy_sets")
    op.drop_table("timetable_policy_sets")
