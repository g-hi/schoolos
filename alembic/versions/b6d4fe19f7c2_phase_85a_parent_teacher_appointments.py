"""phase_85a_parent_teacher_appointments

Revision ID: b6d4fe19f7c2
Revises: d42f0d6ab9e1
Create Date: 2026-07-23 00:00:00.000000

Adds the Parent–Teacher Appointment backend schema for Phase 8.5A.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6d4fe19f7c2"
down_revision: Union[str, None] = "d42f0d6ab9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("timetable_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timetable_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=60), nullable=False),
        sa.Column("meeting_mode", sa.String(length=20), nullable=False),
        sa.Column("location_or_link", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("parent_notes", sa.Text(), nullable=True),
        sa.Column("staff_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("status IN ('requested','confirmed','declined','cancelled','completed')", name="valid_appointment_status"),
        sa.CheckConstraint("meeting_mode IN ('in_person','video','phone')", name="valid_appointment_meeting_mode"),
        sa.CheckConstraint("duration_minutes BETWEEN 10 AND 180", name="valid_appointment_duration"),
    )
    op.create_index("ix_appointments_tenant_id", "appointments", ["tenant_id"])
    op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_index("ix_appointments_requested_start_at", "appointments", ["requested_start_at"])
    op.create_index("ix_appointments_teacher_id", "appointments", ["teacher_id"])
    op.create_index("ix_appointments_scheduled_start_at", "appointments", ["scheduled_start_at"])
    op.create_index("ix_appointments_family_id", "appointments", ["family_id"])
    op.create_index("ix_appointments_student_id", "appointments", ["student_id"])
    op.create_index("ix_appointments_created_at", "appointments", ["created_at"])
    op.create_index("ix_appointments_parent_id", "appointments", ["parent_id"])
    op.create_index("ix_appointments_subject_id", "appointments", ["subject_id"])
    op.create_index("ix_appointments_timetable_entry_id", "appointments", ["timetable_entry_id"])


def downgrade() -> None:
    op.drop_index("ix_appointments_timetable_entry_id", table_name="appointments")
    op.drop_index("ix_appointments_subject_id", table_name="appointments")
    op.drop_index("ix_appointments_parent_id", table_name="appointments")
    op.drop_index("ix_appointments_created_at", table_name="appointments")
    op.drop_index("ix_appointments_student_id", table_name="appointments")
    op.drop_index("ix_appointments_family_id", table_name="appointments")
    op.drop_index("ix_appointments_scheduled_start_at", table_name="appointments")
    op.drop_index("ix_appointments_teacher_id", table_name="appointments")
    op.drop_index("ix_appointments_requested_start_at", table_name="appointments")
    op.drop_index("ix_appointments_status", table_name="appointments")
    op.drop_index("ix_appointments_tenant_id", table_name="appointments")
    op.drop_table("appointments")
