"""phase_9a_master_data_foundation

Revision ID: 9a4d3b2c1f00
Revises: e1f4a2c9d113
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a4d3b2c1f00"
down_revision: Union[str, None] = "e1f4a2c9d113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campuses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_campus_code_per_tenant"),
    )

    op.create_table(
        "academic_years",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_academic_year_name_per_tenant"),
    )

    op.create_table(
        "terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sequence > 0", name="ck_terms_sequence_positive"),
        sa.UniqueConstraint("tenant_id", "academic_year_id", "code", name="uq_term_code_per_year_per_tenant"),
    )

    op.create_table(
        "grade_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sequence > 0", name="ck_grade_levels_sequence_positive"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_grade_level_code_per_tenant"),
    )

    for name, table, columns in (
        ("ix_campuses_tenant_id", "campuses", ["tenant_id"]),
        ("ix_campuses_is_active", "campuses", ["is_active"]),
        ("ix_academic_years_tenant_id", "academic_years", ["tenant_id"]),
        ("ix_academic_years_is_active", "academic_years", ["is_active"]),
        ("ix_academic_years_is_current", "academic_years", ["is_current"]),
        ("ix_terms_tenant_id", "terms", ["tenant_id"]),
        ("ix_terms_academic_year_id", "terms", ["academic_year_id"]),
        ("ix_terms_sequence", "terms", ["sequence"]),
        ("ix_terms_is_active", "terms", ["is_active"]),
        ("ix_grade_levels_tenant_id", "grade_levels", ["tenant_id"]),
        ("ix_grade_levels_sequence", "grade_levels", ["sequence"]),
        ("ix_grade_levels_is_active", "grade_levels", ["is_active"]),
    ):
        op.create_index(name, table, columns)

    op.create_index(
        "uq_academic_year_current_per_tenant",
        "academic_years",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_academic_year_current_per_tenant", table_name="academic_years")

    for name, table in (
        ("ix_grade_levels_is_active", "grade_levels"),
        ("ix_grade_levels_sequence", "grade_levels"),
        ("ix_grade_levels_tenant_id", "grade_levels"),
        ("ix_terms_is_active", "terms"),
        ("ix_terms_sequence", "terms"),
        ("ix_terms_academic_year_id", "terms"),
        ("ix_terms_tenant_id", "terms"),
        ("ix_academic_years_is_current", "academic_years"),
        ("ix_academic_years_is_active", "academic_years"),
        ("ix_academic_years_tenant_id", "academic_years"),
        ("ix_campuses_is_active", "campuses"),
        ("ix_campuses_tenant_id", "campuses"),
    ):
        op.drop_index(name, table_name=table)

    op.drop_table("grade_levels")
    op.drop_table("terms")
    op.drop_table("academic_years")
    op.drop_table("campuses")
