"""phase_10a_timetable_workbook_imports

Revision ID: d2f6e7a9b4c1
Revises: 9a10b1c2d3e4
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6e7a9b4c1"
down_revision: Union[str, None] = "9a10b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("import_batches") as batch_op:
        batch_op.add_column(sa.Column("import_format", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
        batch_op.create_index("ix_import_batches_import_format", ["import_format"], unique=False)

    op.drop_constraint("ck_import_batches_entity_type", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_mode", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_status", "import_batches", type_="check")

    op.create_check_constraint(
        "ck_import_batches_entity_type",
        "import_batches",
        "entity_type IN ('subjects','classes','teachers','students','parents','timetable_workbook')",
    )
    op.create_check_constraint(
        "ck_import_batches_mode",
        "import_batches",
        "mode IN ('preview','commit','workbook')",
    )
    op.create_check_constraint(
        "ck_import_batches_status",
        "import_batches",
        "status IN ('uploaded','validating','preview_ready','invalid','committing','completed','completed_with_errors','failed','cancelled','parsing','mapping_required','validation_failed','validated','committed')",
    )
    op.create_check_constraint(
        "ck_import_batches_format",
        "import_batches",
        "import_format IS NULL OR import_format IN ('csv','xlsx')",
    )

    with op.batch_alter_table("import_row_results") as batch_op:
        batch_op.add_column(sa.Column("severity", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("sheet_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("source_column", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("field_name", sa.String(length=120), nullable=True))
        batch_op.create_index("ix_import_row_results_severity", ["severity"], unique=False)
        batch_op.create_index("ix_import_row_results_sheet_name", ["sheet_name"], unique=False)

    op.create_check_constraint(
        "ck_import_row_results_severity",
        "import_row_results",
        "severity IS NULL OR severity IN ('blocker','warning','information')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_import_row_results_severity", "import_row_results", type_="check")

    with op.batch_alter_table("import_row_results") as batch_op:
        batch_op.drop_index("ix_import_row_results_sheet_name")
        batch_op.drop_index("ix_import_row_results_severity")
        batch_op.drop_column("field_name")
        batch_op.drop_column("source_column")
        batch_op.drop_column("sheet_name")
        batch_op.drop_column("severity")

    op.drop_constraint("ck_import_batches_format", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_entity_type", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_mode", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_status", "import_batches", type_="check")

    op.create_check_constraint(
        "ck_import_batches_entity_type",
        "import_batches",
        "entity_type IN ('subjects','classes','teachers','students','parents')",
    )
    op.create_check_constraint(
        "ck_import_batches_mode",
        "import_batches",
        "mode IN ('preview','commit')",
    )
    op.create_check_constraint(
        "ck_import_batches_status",
        "import_batches",
        "status IN ('uploaded','validating','preview_ready','invalid','committing','completed','completed_with_errors','failed','cancelled')",
    )

    with op.batch_alter_table("import_batches") as batch_op:
        batch_op.drop_index("ix_import_batches_import_format")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("import_format")
