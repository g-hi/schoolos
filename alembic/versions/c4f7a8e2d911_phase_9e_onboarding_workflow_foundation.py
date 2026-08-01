"""phase_9e_onboarding_workflow_foundation

Revision ID: c4f7a8e2d911
Revises: b3c7d9e4f512
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f7a8e2d911"
down_revision: Union[str, None] = "b3c7d9e4f512"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any((idx.get("name") or "") == index_name for idx in (inspector.get_indexes(table_name) or []))


def upgrade() -> None:
    if not _table_exists("school_onboarding_runs"):
        op.create_table(
            "school_onboarding_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("current_step_key", sa.String(length=64), nullable=True),
            sa.Column("started_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("completed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("status IN ('in_progress','paused','ready','completed','cancelled')", name="ck_school_onboarding_runs_status"),
            sa.CheckConstraint("(status <> 'completed') OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL)", name="ck_school_onboarding_runs_completed_fields"),
            sa.CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="ck_school_onboarding_runs_completed_after_started"),
        )

    if not _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_tenant_id"):
        op.create_index("ix_school_onboarding_runs_tenant_id", "school_onboarding_runs", ["tenant_id"])
    if not _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_status"):
        op.create_index("ix_school_onboarding_runs_status", "school_onboarding_runs", ["status"])
    if not _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_started_by_user_id"):
        op.create_index("ix_school_onboarding_runs_started_by_user_id", "school_onboarding_runs", ["started_by_user_id"])
    if not _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_completed_by_user_id"):
        op.create_index("ix_school_onboarding_runs_completed_by_user_id", "school_onboarding_runs", ["completed_by_user_id"])
    if not _index_exists("school_onboarding_runs", "uq_school_onboarding_runs_active_per_tenant"):
        op.create_index(
            "uq_school_onboarding_runs_active_per_tenant",
            "school_onboarding_runs",
            ["tenant_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('in_progress','paused','ready')"),
        )

    if not _table_exists("school_onboarding_steps"):
        op.create_table(
            "school_onboarding_steps",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("onboarding_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("school_onboarding_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("step_key", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("completion_source", sa.String(length=20), nullable=True),
            sa.Column("acknowledged_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("blocked_reason", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("status IN ('not_started','in_progress','blocked','completed','skipped')", name="ck_school_onboarding_steps_status"),
            sa.CheckConstraint("completion_source IS NULL OR completion_source IN ('computed','manual','imported')", name="ck_school_onboarding_steps_completion_source"),
            sa.CheckConstraint("(completion_source <> 'manual' AND status <> 'skipped') OR (acknowledged_by_user_id IS NOT NULL AND acknowledged_at IS NOT NULL)", name="ck_school_onboarding_steps_manual_ack"),
            sa.UniqueConstraint("onboarding_run_id", "step_key", name="uq_school_onboarding_steps_run_step"),
        )

    if not _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_tenant_id"):
        op.create_index("ix_school_onboarding_steps_tenant_id", "school_onboarding_steps", ["tenant_id"])
    if not _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_onboarding_run_id"):
        op.create_index("ix_school_onboarding_steps_onboarding_run_id", "school_onboarding_steps", ["onboarding_run_id"])
    if not _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_step_key"):
        op.create_index("ix_school_onboarding_steps_step_key", "school_onboarding_steps", ["step_key"])
    if not _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_status"):
        op.create_index("ix_school_onboarding_steps_status", "school_onboarding_steps", ["status"])
    if not _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_acknowledged_by_user_id"):
        op.create_index("ix_school_onboarding_steps_acknowledged_by_user_id", "school_onboarding_steps", ["acknowledged_by_user_id"])


def downgrade() -> None:
    if _table_exists("school_onboarding_steps"):
        if _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_acknowledged_by_user_id"):
            op.drop_index("ix_school_onboarding_steps_acknowledged_by_user_id", table_name="school_onboarding_steps")
        if _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_status"):
            op.drop_index("ix_school_onboarding_steps_status", table_name="school_onboarding_steps")
        if _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_step_key"):
            op.drop_index("ix_school_onboarding_steps_step_key", table_name="school_onboarding_steps")
        if _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_onboarding_run_id"):
            op.drop_index("ix_school_onboarding_steps_onboarding_run_id", table_name="school_onboarding_steps")
        if _index_exists("school_onboarding_steps", "ix_school_onboarding_steps_tenant_id"):
            op.drop_index("ix_school_onboarding_steps_tenant_id", table_name="school_onboarding_steps")
        op.drop_table("school_onboarding_steps")

    if _table_exists("school_onboarding_runs"):
        if _index_exists("school_onboarding_runs", "uq_school_onboarding_runs_active_per_tenant"):
            op.drop_index("uq_school_onboarding_runs_active_per_tenant", table_name="school_onboarding_runs")
        if _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_completed_by_user_id"):
            op.drop_index("ix_school_onboarding_runs_completed_by_user_id", table_name="school_onboarding_runs")
        if _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_started_by_user_id"):
            op.drop_index("ix_school_onboarding_runs_started_by_user_id", table_name="school_onboarding_runs")
        if _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_status"):
            op.drop_index("ix_school_onboarding_runs_status", table_name="school_onboarding_runs")
        if _index_exists("school_onboarding_runs", "ix_school_onboarding_runs_tenant_id"):
            op.drop_index("ix_school_onboarding_runs_tenant_id", table_name="school_onboarding_runs")
        op.drop_table("school_onboarding_runs")
