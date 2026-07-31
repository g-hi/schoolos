"""phase_9b3_student_enrollments

Revision ID: 8c3f2b1e9d77
Revises: 7d1b8a5c4e10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c3f2b1e9d77"
down_revision: Union[str, None] = "7d1b8a5c4e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grade_level_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("enrolled_on", sa.Date(), nullable=False),
        sa.Column("exited_on", sa.Date(), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'transferred', 'withdrawn', 'completed')", name="ck_student_enrollments_status"),
        sa.CheckConstraint(
            "(status = 'active' AND exited_on IS NULL) OR "
            "(status IN ('transferred', 'withdrawn', 'completed') AND exited_on IS NOT NULL)",
            name="ck_student_enrollments_exit_presence",
        ),
        sa.CheckConstraint("exited_on IS NULL OR exited_on >= enrolled_on", name="ck_student_enrollments_date_range"),
    )

    op.create_index(
        "uq_student_enrollments_active_student_year",
        "student_enrollments",
        ["tenant_id", "academic_year_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_index("ix_student_enrollments_tenant_id", "student_enrollments", ["tenant_id"])
    op.create_index("ix_student_enrollments_academic_year_id", "student_enrollments", ["academic_year_id"])
    op.create_index("ix_student_enrollments_student_id", "student_enrollments", ["student_id"])
    op.create_index("ix_student_enrollments_class_id", "student_enrollments", ["class_id"])
    op.create_index("ix_student_enrollments_grade_level_id", "student_enrollments", ["grade_level_id"])
    op.create_index("ix_student_enrollments_status", "student_enrollments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_student_enrollments_status", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_grade_level_id", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_class_id", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_student_id", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_academic_year_id", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_tenant_id", table_name="student_enrollments")
    op.drop_index("uq_student_enrollments_active_student_year", table_name="student_enrollments")
    op.drop_table("student_enrollments")
