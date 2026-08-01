"""phase_9d_import_history_foundation

Revision ID: b3c7d9e4f512
Revises: 1a9d5e7c3b21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c7d9e4f512"
down_revision: Union[str, None] = "1a9d5e7c3b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any((idx.get("name") or "") == index_name for idx in (inspector.get_indexes(table_name) or []))


def upgrade() -> None:
    if not _table_exists("import_batches"):
        op.create_table(
            "import_batches",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=True),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("mode", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("valid_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("skipped_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("conflict_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("entity_type IN ('subjects','classes','teachers','students','parents')", name="ck_import_batches_entity_type"),
            sa.CheckConstraint("mode IN ('preview','commit')", name="ck_import_batches_mode"),
            sa.CheckConstraint("status IN ('uploaded','validating','preview_ready','invalid','committing','completed','completed_with_errors','failed','cancelled')", name="ck_import_batches_status"),
        )

    if not _index_exists("import_batches", "ix_import_batches_tenant_id"):
        op.create_index("ix_import_batches_tenant_id", "import_batches", ["tenant_id"])
    if not _index_exists("import_batches", "ix_import_batches_entity_type"):
        op.create_index("ix_import_batches_entity_type", "import_batches", ["entity_type"])
    if not _index_exists("import_batches", "ix_import_batches_file_sha256"):
        op.create_index("ix_import_batches_file_sha256", "import_batches", ["file_sha256"])
    if not _index_exists("import_batches", "ix_import_batches_created_by_user_id"):
        op.create_index("ix_import_batches_created_by_user_id", "import_batches", ["created_by_user_id"])
    if not _index_exists("import_batches", "ix_import_batches_mode"):
        op.create_index("ix_import_batches_mode", "import_batches", ["mode"])
    if not _index_exists("import_batches", "ix_import_batches_status"):
        op.create_index("ix_import_batches_status", "import_batches", ["status"])
    if not _index_exists("import_batches", "ix_import_batches_created_at"):
        op.create_index("ix_import_batches_created_at", "import_batches", ["created_at"])

    if not _table_exists("import_row_results"):
        op.create_table(
            "import_row_results",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("entity_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("field_errors", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("normalized_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("row_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("row_number > 0", name="ck_import_row_results_row_number_positive"),
            sa.CheckConstraint("status IN ('valid','invalid','conflict','created','updated','skipped','failed')", name="ck_import_row_results_status"),
            sa.CheckConstraint("action IN ('create','update','skip','none')", name="ck_import_row_results_action"),
            sa.UniqueConstraint("import_batch_id", "row_number", name="uq_import_row_results_batch_row"),
        )

    if not _index_exists("import_row_results", "ix_import_row_results_tenant_id"):
        op.create_index("ix_import_row_results_tenant_id", "import_row_results", ["tenant_id"])
    if not _index_exists("import_row_results", "ix_import_row_results_import_batch_id"):
        op.create_index("ix_import_row_results_import_batch_id", "import_row_results", ["import_batch_id"])
    if not _index_exists("import_row_results", "ix_import_row_results_row_number"):
        op.create_index("ix_import_row_results_row_number", "import_row_results", ["row_number"])
    if not _index_exists("import_row_results", "ix_import_row_results_status"):
        op.create_index("ix_import_row_results_status", "import_row_results", ["status"])
    if not _index_exists("import_row_results", "ix_import_row_results_action"):
        op.create_index("ix_import_row_results_action", "import_row_results", ["action"])
    if not _index_exists("import_row_results", "ix_import_row_results_entity_reference_id"):
        op.create_index("ix_import_row_results_entity_reference_id", "import_row_results", ["entity_reference_id"])


def downgrade() -> None:
    if _table_exists("import_row_results"):
        if _index_exists("import_row_results", "ix_import_row_results_status"):
            op.drop_index("ix_import_row_results_status", table_name="import_row_results")
        if _index_exists("import_row_results", "ix_import_row_results_action"):
            op.drop_index("ix_import_row_results_action", table_name="import_row_results")
        if _index_exists("import_row_results", "ix_import_row_results_entity_reference_id"):
            op.drop_index("ix_import_row_results_entity_reference_id", table_name="import_row_results")
        if _index_exists("import_row_results", "ix_import_row_results_row_number"):
            op.drop_index("ix_import_row_results_row_number", table_name="import_row_results")
        if _index_exists("import_row_results", "ix_import_row_results_import_batch_id"):
            op.drop_index("ix_import_row_results_import_batch_id", table_name="import_row_results")
        if _index_exists("import_row_results", "ix_import_row_results_tenant_id"):
            op.drop_index("ix_import_row_results_tenant_id", table_name="import_row_results")
        op.drop_table("import_row_results")

    if _table_exists("import_batches"):
        if _index_exists("import_batches", "ix_import_batches_created_at"):
            op.drop_index("ix_import_batches_created_at", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_status"):
            op.drop_index("ix_import_batches_status", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_mode"):
            op.drop_index("ix_import_batches_mode", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_file_sha256"):
            op.drop_index("ix_import_batches_file_sha256", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_entity_type"):
            op.drop_index("ix_import_batches_entity_type", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_created_by_user_id"):
            op.drop_index("ix_import_batches_created_by_user_id", table_name="import_batches")
        if _index_exists("import_batches", "ix_import_batches_tenant_id"):
            op.drop_index("ix_import_batches_tenant_id", table_name="import_batches")
        op.drop_table("import_batches")
