"""phase_9b1_academic_structure_foundation

Revision ID: 4f2e1d9b7c30
Revises: 9a4d3b2c1f00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4f2e1d9b7c30"
down_revision: Union[str, None] = "9a4d3b2c1f00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_CLASS_UNIQUE_COLUMNS = ("tenant_id", "grade", "section", "academic_year")


def _normalized_column_names(columns: list[str] | tuple[str, ...] | None) -> tuple[str, ...] | None:
    if not columns:
        return None
    return tuple(sorted(columns))


def _matching_legacy_unique_constraints(inspector: sa.Inspector) -> list[str]:
    matches: list[str] = []
    for constraint in inspector.get_unique_constraints("classes") or []:
        name = constraint.get("name")
        column_names = _normalized_column_names(constraint.get("column_names"))
        if not name or column_names is None:
            continue
        if column_names == tuple(sorted(LEGACY_CLASS_UNIQUE_COLUMNS)):
            matches.append(name)
    return matches


def _matching_legacy_unique_indexes(
    inspector: sa.Inspector,
    *,
    excluded_names: set[str] | None = None,
) -> list[str]:
    matches: list[str] = []
    legacy_columns = tuple(sorted(LEGACY_CLASS_UNIQUE_COLUMNS))
    excluded = set(excluded_names or _matching_legacy_unique_constraints(inspector))
    for index in inspector.get_indexes("classes") or []:
        name = index.get("name")
        column_names = _normalized_column_names(index.get("column_names"))
        if not name or column_names is None:
            continue
        if name in excluded:
            continue
        if not index.get("unique", False):
            continue
        if index.get("duplicates_constraint"):
            continue
        if column_names == legacy_columns:
            matches.append(name)
    return matches


def _drop_legacy_class_uniqueness(bind) -> None:
    inspector = sa.inspect(bind)
    constraint_names = _matching_legacy_unique_constraints(inspector)
    for constraint_name in constraint_names:
        op.drop_constraint(constraint_name, "classes", type_="unique")

    inspector = sa.inspect(bind)
    for index_name in _matching_legacy_unique_indexes(inspector, excluded_names=set(constraint_names)):
        op.drop_index(index_name, table_name="classes")


def _assert_no_duplicate_legacy_classes(bind) -> None:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM classes "
            "WHERE campus_id IS NULL AND academic_year_id IS NULL AND grade_level_id IS NULL "
            "GROUP BY tenant_id, grade, section, academic_year "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    )
    if result.first() is not None:
        raise RuntimeError("Duplicate legacy class identities must be resolved before running this migration.")


def _matching_legacy_uniqueness_exists(inspector: sa.Inspector) -> bool:
    return bool(_matching_legacy_unique_constraints(inspector) or _matching_legacy_unique_indexes(inspector))


def _restore_legacy_class_uniqueness_if_missing(bind) -> None:
    inspector = sa.inspect(bind)
    if _matching_legacy_uniqueness_exists(inspector):
        raise RuntimeError("Equivalent legacy class uniqueness already exists; downgrade would duplicate it.")
    op.create_unique_constraint(
        "uq_class_per_tenant",
        "classes",
        ["tenant_id", "grade", "section", "academic_year"],
    )


def upgrade() -> None:
    op.add_column("classes", sa.Column("campus_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("classes", sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("classes", sa.Column("grade_level_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("classes", sa.Column("code", sa.String(length=50), nullable=True))
    op.add_column("classes", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("classes", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

    op.create_foreign_key(
        "fk_classes_campus_id_campuses",
        "classes",
        "campuses",
        ["campus_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_classes_academic_year_id_academic_years",
        "classes",
        "academic_years",
        ["academic_year_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_classes_grade_level_id_grade_levels",
        "classes",
        "grade_levels",
        ["grade_level_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_classes_canonical_scope_all_or_none",
        "classes",
        "((campus_id IS NULL AND academic_year_id IS NULL AND grade_level_id IS NULL) OR "
        "(campus_id IS NOT NULL AND academic_year_id IS NOT NULL AND grade_level_id IS NOT NULL))",
    )

    bind = op.get_bind()
    _drop_legacy_class_uniqueness(bind)
    _assert_no_duplicate_legacy_classes(bind)

    op.create_index(
        "uq_classes_legacy_identity",
        "classes",
        ["tenant_id", "grade", "section", "academic_year"],
        unique=True,
        postgresql_where=sa.text(
            "campus_id IS NULL AND academic_year_id IS NULL AND grade_level_id IS NULL"
        ),
    )
    op.create_index(
        "uq_classes_canonical_section",
        "classes",
        ["tenant_id", "campus_id", "academic_year_id", "grade_level_id", "section"],
        unique=True,
        postgresql_where=sa.text(
            "campus_id IS NOT NULL AND academic_year_id IS NOT NULL "
            "AND grade_level_id IS NOT NULL AND is_active IS TRUE"
        ),
    )
    op.create_index(
        "uq_classes_code_per_academic_year",
        "classes",
        ["tenant_id", "academic_year_id", "code"],
        unique=True,
        postgresql_where=sa.text(
            "academic_year_id IS NOT NULL AND code IS NOT NULL AND is_active IS TRUE"
        ),
    )

    op.create_table(
        "subject_offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campus_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grade_level_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "campus_id", "academic_year_id", "grade_level_id", "subject_id", name="uq_subject_offering_scope"),
    )

    op.create_index("ix_subject_offerings_tenant_id", "subject_offerings", ["tenant_id"])
    op.create_index("ix_subject_offerings_campus_id", "subject_offerings", ["campus_id"])
    op.create_index("ix_subject_offerings_academic_year_id", "subject_offerings", ["academic_year_id"])
    op.create_index("ix_subject_offerings_grade_level_id", "subject_offerings", ["grade_level_id"])
    op.create_index("ix_subject_offerings_subject_id", "subject_offerings", ["subject_id"])
    op.create_index("ix_subject_offerings_is_active", "subject_offerings", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_subject_offerings_is_active", table_name="subject_offerings")
    op.drop_index("ix_subject_offerings_subject_id", table_name="subject_offerings")
    op.drop_index("ix_subject_offerings_grade_level_id", table_name="subject_offerings")
    op.drop_index("ix_subject_offerings_academic_year_id", table_name="subject_offerings")
    op.drop_index("ix_subject_offerings_campus_id", table_name="subject_offerings")
    op.drop_index("ix_subject_offerings_tenant_id", table_name="subject_offerings")
    op.drop_table("subject_offerings")

    op.drop_index("uq_classes_code_per_academic_year", table_name="classes")
    op.drop_index("uq_classes_canonical_section", table_name="classes")
    op.drop_index("uq_classes_legacy_identity", table_name="classes")

    _restore_legacy_class_uniqueness_if_missing(op.get_bind())

    op.drop_constraint("ck_classes_canonical_scope_all_or_none", "classes", type_="check")
    op.drop_constraint("fk_classes_grade_level_id_grade_levels", "classes", type_="foreignkey")
    op.drop_constraint("fk_classes_academic_year_id_academic_years", "classes", type_="foreignkey")
    op.drop_constraint("fk_classes_campus_id_campuses", "classes", type_="foreignkey")

    op.drop_column("classes", "updated_at")
    op.drop_column("classes", "is_active")
    op.drop_column("classes", "code")
    op.drop_column("classes", "grade_level_id")
    op.drop_column("classes", "academic_year_id")
    op.drop_column("classes", "campus_id")
