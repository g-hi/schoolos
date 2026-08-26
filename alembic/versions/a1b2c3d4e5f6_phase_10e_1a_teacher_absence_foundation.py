"""phase_10e_1a_teacher_absence_foundation

Revision ID: a1b2c3d4e5f6
Revises: 9a2e3d7c04b1
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9a2e3d7c04b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teacher_absences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("scope_type", sa.String(length=30), nullable=False, server_default="whole_day"),
        sa.Column("selected_periods", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=False),
        sa.Column("private_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="reported"),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("reported_by_user_id", sa.UUID(), nullable=True),
        sa.Column("confirmed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("cancelled_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reported_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_date >= start_date", name="ck_teacher_absences_date_range"),
        sa.CheckConstraint("status IN ('reported','confirmed','cancelled','closed')", name="ck_teacher_absences_status"),
        sa.CheckConstraint("scope_type IN ('whole_day','selected_periods')", name="ck_teacher_absences_scope_type"),
        sa.CheckConstraint(
            "(scope_type = 'whole_day' AND selected_periods IS NULL) OR "
            "(scope_type = 'selected_periods' AND selected_periods IS NOT NULL)",
            name="ck_teacher_absences_selected_periods_scope",
        ),
    )
    op.create_index("ix_teacher_absences_tenant_id", "teacher_absences", ["tenant_id"])
    op.create_index("ix_teacher_absences_teacher_id", "teacher_absences", ["teacher_id"])
    op.create_index("ix_teacher_absences_tenant_date", "teacher_absences", ["tenant_id", "start_date", "end_date"])
    op.create_index("ix_teacher_absences_tenant_teacher_date", "teacher_absences", ["tenant_id", "teacher_id", "start_date", "end_date"])


def downgrade() -> None:
    op.drop_index("ix_teacher_absences_tenant_teacher_date", table_name="teacher_absences")
    op.drop_index("ix_teacher_absences_tenant_date", table_name="teacher_absences")
    op.drop_index("ix_teacher_absences_teacher_id", table_name="teacher_absences")
    op.drop_index("ix_teacher_absences_tenant_id", table_name="teacher_absences")
    op.drop_table("teacher_absences")
