"""phase_9b2_teacher_assignment_schema

Revision ID: 7d1b8a5c4e10
Revises: 4f2e1d9b7c30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d1b8a5c4e10"
down_revision: Union[str, None] = "4f2e1d9b7c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teacher_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_offering_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subject_offerings.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("assignment_type", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("assignment_type IN ('homeroom', 'subject_teacher')", name="ck_teacher_assignments_type"),
        sa.CheckConstraint(
            "(assignment_type = 'homeroom' AND subject_offering_id IS NULL) OR "
            "(assignment_type = 'subject_teacher' AND subject_offering_id IS NOT NULL)",
            name="ck_teacher_assignments_subject_scope",
        ),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_teacher_assignments_date_range"),
    )

    op.create_index("uq_teacher_assignments_active_homeroom_class", "teacher_assignments", ["tenant_id", "academic_year_id", "class_id"], unique=True, postgresql_where=sa.text("is_active IS TRUE AND assignment_type = 'homeroom'"))
    op.create_index("uq_teacher_assignments_active_subject_teacher", "teacher_assignments", ["tenant_id", "academic_year_id", "teacher_id", "class_id", "subject_offering_id"], unique=True, postgresql_where=sa.text("is_active IS TRUE AND assignment_type = 'subject_teacher'"))

    op.create_index("ix_teacher_assignments_tenant_id", "teacher_assignments", ["tenant_id"])
    op.create_index("ix_teacher_assignments_academic_year_id", "teacher_assignments", ["academic_year_id"])
    op.create_index("ix_teacher_assignments_teacher_id", "teacher_assignments", ["teacher_id"])
    op.create_index("ix_teacher_assignments_class_id", "teacher_assignments", ["class_id"])
    op.create_index("ix_teacher_assignments_subject_offering_id", "teacher_assignments", ["subject_offering_id"])
    op.create_index("ix_teacher_assignments_assignment_type", "teacher_assignments", ["assignment_type"])
    op.create_index("ix_teacher_assignments_is_active", "teacher_assignments", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_teacher_assignments_is_active", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_assignment_type", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_subject_offering_id", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_class_id", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_teacher_id", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_academic_year_id", table_name="teacher_assignments")
    op.drop_index("ix_teacher_assignments_tenant_id", table_name="teacher_assignments")
    op.drop_index("uq_teacher_assignments_active_subject_teacher", table_name="teacher_assignments")
    op.drop_index("uq_teacher_assignments_active_homeroom_class", table_name="teacher_assignments")
    op.drop_table("teacher_assignments")
