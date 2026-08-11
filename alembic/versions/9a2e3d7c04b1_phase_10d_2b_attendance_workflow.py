"""phase_10d_2b_attendance_workflow

Revision ID: 9a2e3d7c04b1
Revises: b7c3d9e1f4a2

Adds the lifecycle columns that carry the workflow state for a submitted/finalized
attendance register and the minutes-late capture on each record.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9a2e3d7c04b1"
down_revision: Union[str, None] = "b7c3d9e1f4a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attendance_registers",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_registers",
        sa.Column("submitted_by", sa.UUID(), nullable=True),
    )
    op.add_column(
        "attendance_registers",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_registers",
        sa.Column("finalized_by", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_attendance_registers_submitted_by_users",
        "attendance_registers",
        "users",
        ["submitted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_attendance_registers_finalized_by_users",
        "attendance_registers",
        "users",
        ["finalized_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "attendance_records",
        sa.Column("minutes_late", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_attendance_records_minutes_late_nonnegative",
        "attendance_records",
        "minutes_late IS NULL OR minutes_late >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_attendance_records_minutes_late_nonnegative",
        "attendance_records",
        type_="check",
    )
    op.drop_column("attendance_records", "minutes_late")

    op.drop_constraint(
        "fk_attendance_registers_finalized_by_users",
        "attendance_registers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_attendance_registers_submitted_by_users",
        "attendance_registers",
        type_="foreignkey",
    )
    op.drop_column("attendance_registers", "finalized_by")
    op.drop_column("attendance_registers", "finalized_at")
    op.drop_column("attendance_registers", "submitted_by")
    op.drop_column("attendance_registers", "submitted_at")
