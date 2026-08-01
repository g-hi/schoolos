"""phase_9c_people_directory_foundation

Revision ID: 1a9d5e7c3b21
Revises: 8c3f2b1e9d77
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1a9d5e7c3b21"
down_revision: Union[str, None] = "8c3f2b1e9d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    columns = inspector.get_columns(table_name)
    return any(col.get("name") == column_name for col in columns)


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any((idx.get("name") or "") == index_name for idx in (inspector.get_indexes(table_name) or []))


def upgrade() -> None:
    if not _table_exists("account_invitations"):
        op.create_table(
            "account_invitations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("invited_email", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=50), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("accepted_at IS NULL OR revoked_at IS NULL", name="ck_account_invitations_accepted_or_revoked"),
            sa.CheckConstraint("expires_at > created_at", name="ck_account_invitations_expires_after_created"),
            sa.CheckConstraint("role IN ('school_admin','principal','teacher','parent','staff')", name="ck_account_invitations_role"),
            sa.CheckConstraint("invited_email = lower(invited_email)", name="ck_account_invitations_email_normalized"),
            sa.UniqueConstraint("token_hash", name="uq_account_invitations_token_hash"),
        )

    if not _index_exists("account_invitations", "ix_account_invitations_tenant_id"):
        op.create_index("ix_account_invitations_tenant_id", "account_invitations", ["tenant_id"])
    if not _index_exists("account_invitations", "ix_account_invitations_user_id"):
        op.create_index("ix_account_invitations_user_id", "account_invitations", ["user_id"])
    if not _index_exists("account_invitations", "ix_account_invitations_role"):
        op.create_index("ix_account_invitations_role", "account_invitations", ["role"])
    if not _index_exists("account_invitations", "ix_account_invitations_expires_at"):
        op.create_index("ix_account_invitations_expires_at", "account_invitations", ["expires_at"])
    if not _index_exists("account_invitations", "ix_account_invitations_created_by_user_id"):
        op.create_index("ix_account_invitations_created_by_user_id", "account_invitations", ["created_by_user_id"])
    if not _index_exists("account_invitations", "ix_account_invitations_invited_email"):
        op.create_index("ix_account_invitations_invited_email", "account_invitations", ["invited_email"])
    if not _index_exists("account_invitations", "uq_account_invitations_pending_per_user"):
        op.create_index(
            "uq_account_invitations_pending_per_user",
            "account_invitations",
            ["tenant_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
        )

    if not _column_exists("student_parents", "is_active"):
        op.add_column(
            "student_parents",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
    if not _column_exists("student_parents", "created_at"):
        op.add_column(
            "student_parents",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if not _column_exists("student_parents", "updated_at"):
        op.add_column(
            "student_parents",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    if not _index_exists("student_parents", "ix_student_parents_is_active"):
        op.create_index("ix_student_parents_is_active", "student_parents", ["is_active"])


def downgrade() -> None:
    if _index_exists("student_parents", "ix_student_parents_is_active"):
        op.drop_index("ix_student_parents_is_active", table_name="student_parents")

    if _column_exists("student_parents", "updated_at"):
        op.drop_column("student_parents", "updated_at")
    if _column_exists("student_parents", "created_at"):
        op.drop_column("student_parents", "created_at")
    if _column_exists("student_parents", "is_active"):
        op.drop_column("student_parents", "is_active")

    if _table_exists("account_invitations"):
        if _index_exists("account_invitations", "uq_account_invitations_pending_per_user"):
            op.drop_index("uq_account_invitations_pending_per_user", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_invited_email"):
            op.drop_index("ix_account_invitations_invited_email", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_created_by_user_id"):
            op.drop_index("ix_account_invitations_created_by_user_id", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_expires_at"):
            op.drop_index("ix_account_invitations_expires_at", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_role"):
            op.drop_index("ix_account_invitations_role", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_user_id"):
            op.drop_index("ix_account_invitations_user_id", table_name="account_invitations")
        if _index_exists("account_invitations", "ix_account_invitations_tenant_id"):
            op.drop_index("ix_account_invitations_tenant_id", table_name="account_invitations")
        op.drop_table("account_invitations")
