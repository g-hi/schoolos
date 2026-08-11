"""phase_10d_2_attendance_persistence

Revision ID: b7c3d9e1f4a2
Revises: f3a2d8c1e9b4

Creates:
  - attendance_registers  (one per class-facing session slot per school day)
  - attendance_records    (one per expected student per register)

All PostgreSQL identifiers ≤63 characters.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7c3d9e1f4a2"
down_revision: Union[str, None] = "f3a2d8c1e9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attendance_registers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("operational_school_day_id", sa.UUID(), nullable=False),
        # class_facing_session_key: mirrors DailySession.class_facing_session_key.
        # Parallel DailySession children share one key → one register per slot.
        sa.Column("class_facing_session_key", sa.String(length=64), nullable=False),
        # class_id: denormalized string UUID, matches DailySession.class_id type.
        sa.Column("class_id", sa.String(length=120), nullable=False),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column(
            "register_status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "roster_resolution_status",
            sa.String(length=30),
            nullable=False,
            server_default="resolved",
        ),
        # SHA-256 hex over sorted effective (student_id, enrollment_id) pairs.
        # Same effective roster on same date → same fingerprint.
        sa.Column("roster_source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "expected_student_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operational_school_day_id"],
            ["operational_school_days.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "register_status IN ('open','closed')",
            name="ck_attendance_registers_status",
        ),
        sa.CheckConstraint(
            "roster_resolution_status IN ('resolved','stale','parallel_unresolved')",
            name="ck_att_registers_roster_status",
        ),
        # Primary uniqueness: one register per (tenant, OSD, class-facing key).
        sa.UniqueConstraint(
            "tenant_id",
            "operational_school_day_id",
            "class_facing_session_key",
            name="uq_att_registers_osd_session_key",
        ),
    )
    op.create_index(
        "ix_att_registers_tenant_id",
        "attendance_registers", ["tenant_id"], unique=False,
    )
    op.create_index(
        "ix_att_registers_osd_id",
        "attendance_registers", ["operational_school_day_id"], unique=False,
    )
    op.create_index(
        "ix_att_registers_school_date",
        "attendance_registers", ["school_date"], unique=False,
    )
    op.create_index(
        "ix_att_registers_tenant_date",
        "attendance_registers", ["tenant_id", "school_date"], unique=False,
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("attendance_register_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        # source_enrollment_id: the StudentEnrollment that placed the student
        # in the effective roster. SET NULL to survive enrollment corrections.
        sa.Column("source_enrollment_id", sa.UUID(), nullable=True),
        sa.Column(
            "attendance_status",
            sa.String(length=20),
            nullable=False,
            server_default="unmarked",
        ),
        # marked_at / marked_by: NULL until a teacher marks the record (future).
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("marked_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attendance_register_id"],
            ["attendance_registers.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_enrollment_id"],
            ["student_enrollments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["marked_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "attendance_status IN ('unmarked','present','absent','late','excused')",
            name="ck_attendance_records_status",
        ),
        # One record per student per register.
        sa.UniqueConstraint(
            "attendance_register_id",
            "student_id",
            name="uq_attendance_records_register_student",
        ),
    )
    op.create_index(
        "ix_att_records_tenant_id",
        "attendance_records", ["tenant_id"], unique=False,
    )
    op.create_index(
        "ix_att_records_register_id",
        "attendance_records", ["attendance_register_id"], unique=False,
    )
    op.create_index(
        "ix_att_records_student_id",
        "attendance_records", ["student_id"], unique=False,
    )
    op.create_index(
        "ix_att_records_status",
        "attendance_records", ["attendance_status"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_att_records_status", table_name="attendance_records")
    op.drop_index("ix_att_records_student_id", table_name="attendance_records")
    op.drop_index("ix_att_records_register_id", table_name="attendance_records")
    op.drop_index("ix_att_records_tenant_id", table_name="attendance_records")
    op.drop_table("attendance_records")

    op.drop_index("ix_att_registers_tenant_date", table_name="attendance_registers")
    op.drop_index("ix_att_registers_school_date", table_name="attendance_registers")
    op.drop_index("ix_att_registers_osd_id", table_name="attendance_registers")
    op.drop_index("ix_att_registers_tenant_id", table_name="attendance_registers")
    op.drop_table("attendance_registers")
