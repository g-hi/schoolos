"""phase_10e_3a_operational_assignment_contract

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f6
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_assignment_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("assignment_type", sa.String(length=30), nullable=False),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column("teacher_absence_id", sa.UUID(), nullable=True),
        sa.Column("original_teacher_id", sa.UUID(), nullable=False),
        sa.Column("daily_session_id", sa.UUID(), nullable=True),
        sa.Column("duty_assignment_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_absence_id"], ["teacher_absences.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["original_teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["daily_session_id"], ["daily_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["duty_assignment_id"], ["duty_assignments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "assignment_type IN ('teaching_substitution','duty_reassignment')",
            name="ck_operational_assignment_requests_assignment_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','evaluated','pending_approval','approved','no_eligible_candidate','cancelled','completed')",
            name="ck_operational_assignment_requests_status",
        ),
        sa.CheckConstraint(
            "(assignment_type = 'teaching_substitution' AND daily_session_id IS NOT NULL AND duty_assignment_id IS NULL) OR "
            "(assignment_type = 'duty_reassignment' AND duty_assignment_id IS NOT NULL AND daily_session_id IS NULL)",
            name="ck_operational_assignment_requests_target_consistency",
        ),
    )
    op.create_index("ix_oar_tenant_school_date", "operational_assignment_requests", ["tenant_id", "school_date"])
    op.create_index("ix_oar_tenant_type_date", "operational_assignment_requests", ["tenant_id", "assignment_type", "school_date"])
    op.create_index("ix_oar_daily_session", "operational_assignment_requests", ["tenant_id", "daily_session_id"])
    op.create_index("ix_oar_duty_assignment", "operational_assignment_requests", ["tenant_id", "duty_assignment_id"])
    op.create_index("ix_oar_teacher_date", "operational_assignment_requests", ["tenant_id", "original_teacher_id", "school_date"])

    op.create_table(
        "operational_assignment_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("assignment_request_id", sa.UUID(), nullable=False),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column("assignment_type", sa.String(length=30), nullable=False),
        sa.Column("daily_session_id", sa.UUID(), nullable=True),
        sa.Column("duty_assignment_id", sa.UUID(), nullable=True),
        sa.Column("replacement_teacher_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_request_id"], ["operational_assignment_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["daily_session_id"], ["daily_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["duty_assignment_id"], ["duty_assignments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replacement_teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "assignment_type IN ('teaching_substitution','duty_reassignment')",
            name="ck_operational_assignment_overrides_assignment_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','cancelled','completed')",
            name="ck_operational_assignment_overrides_status",
        ),
        sa.CheckConstraint(
            "(assignment_type = 'teaching_substitution' AND daily_session_id IS NOT NULL AND duty_assignment_id IS NULL) OR "
            "(assignment_type = 'duty_reassignment' AND duty_assignment_id IS NOT NULL AND daily_session_id IS NULL)",
            name="ck_operational_assignment_overrides_target_consistency",
        ),
    )
    op.create_index("ix_oao_tenant_school_date", "operational_assignment_overrides", ["tenant_id", "school_date"])
    op.create_index("ix_oao_request_id", "operational_assignment_overrides", ["tenant_id", "assignment_request_id"])
    op.create_index("ix_oao_daily_session", "operational_assignment_overrides", ["tenant_id", "daily_session_id"])
    op.create_index("ix_oao_duty_assignment", "operational_assignment_overrides", ["tenant_id", "duty_assignment_id"])
    op.create_index("ix_oao_teacher_date", "operational_assignment_overrides", ["tenant_id", "replacement_teacher_id", "school_date"])


def downgrade() -> None:
    op.drop_index("ix_oao_teacher_date", table_name="operational_assignment_overrides")
    op.drop_index("ix_oao_duty_assignment", table_name="operational_assignment_overrides")
    op.drop_index("ix_oao_daily_session", table_name="operational_assignment_overrides")
    op.drop_index("ix_oao_request_id", table_name="operational_assignment_overrides")
    op.drop_index("ix_oao_tenant_school_date", table_name="operational_assignment_overrides")
    op.drop_table("operational_assignment_overrides")

    op.drop_index("ix_oar_teacher_date", table_name="operational_assignment_requests")
    op.drop_index("ix_oar_duty_assignment", table_name="operational_assignment_requests")
    op.drop_index("ix_oar_daily_session", table_name="operational_assignment_requests")
    op.drop_index("ix_oar_tenant_type_date", table_name="operational_assignment_requests")
    op.drop_index("ix_oar_tenant_school_date", table_name="operational_assignment_requests")
    op.drop_table("operational_assignment_requests")
