"""parent_experience_phase_8_1

Revision ID: b5f3e8c9a12d
Revises: a69044576efe
Create Date: 2026-07-15 00:00:00.000000

Adds the Parent Experience Platform Phase 8.1 schema:

New tables:
  families                  — family grouping unit
  parent_preferences        — per-parent display and notification settings
  family_timeline_events    — chronological event projection (write-on-event)

Extended table:
  student_parents           — adds family_id, is_primary, and three
                              can_* permission columns

Migration notes
---------------
- family_id on student_parents is nullable to preserve legacy rows.
  The application layer enforces family_id for new Parent Experience records.
  A separate controlled backfill is required before this column can be
  made NOT NULL (not part of Phase 8.1).
- The FK fk_student_parents_family_id is created explicitly with
  op.create_foreign_key() and not duplicated inside op.add_column().
- Downgrade removes constraints and columns in reverse dependency order.

Production deployment
---------------------
Run this migration via:
    alembic upgrade head
before starting the application against an existing database.
The Dockerfile CMD and Render deployment both execute this automatically.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "b5f3e8c9a12d"
down_revision: Union[str, None] = "a69044576efe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create families table ──────────────────────────────────────────────
    op.create_table(
        "families",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_families_tenant_id", "families", ["tenant_id"])

    # ── 2. Create parent_preferences table ───────────────────────────────────
    op.create_table(
        "parent_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "preferred_language",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column(
            "timezone",
            sa.String(60),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column(
            "theme",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'light'"),
        ),
        sa.Column(
            "weekly_report_digest",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "email_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "in_app_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_parent_preferences_user"),
        sa.CheckConstraint(
            "theme IN ('light','dark','system')", name="valid_theme"
        ),
    )
    op.create_index("ix_parent_preferences_tenant_id", "parent_preferences", ["tenant_id"])
    op.create_index("ix_parent_preferences_user_id", "parent_preferences", ["user_id"])

    # ── 3. Create family_timeline_events table ────────────────────────────────
    op.create_table(
        "family_timeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(500), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_module", sa.String(80), nullable=False),
        sa.Column("source_reference", sa.String(128), nullable=True),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'informational'"),
        ),
        sa.Column("action_url", sa.String(500), nullable=True),
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'family'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_timeline_idempotency"
        ),
        sa.CheckConstraint(
            "priority IN ('critical','important','informational')",
            name="valid_timeline_priority",
        ),
        sa.CheckConstraint(
            "visibility IN ('family','student_only')",
            name="valid_timeline_visibility",
        ),
    )
    op.create_index(
        "ix_family_timeline_tenant_id", "family_timeline_events", ["tenant_id"]
    )
    op.create_index(
        "ix_family_timeline_family_id", "family_timeline_events", ["family_id"]
    )
    op.create_index(
        "ix_family_timeline_student_id", "family_timeline_events", ["student_id"]
    )
    op.create_index(
        "ix_family_timeline_occurred_at", "family_timeline_events", ["occurred_at"]
    )

    # ── 4. Extend student_parents ─────────────────────────────────────────────
    # Add bare UUID column first (no inline FK — named FK created separately below).
    op.add_column(
        "student_parents",
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                "Nullable: legacy rows without family_id are preserved. "
                "New Parent Experience records must set this via the application layer."
            ),
        ),
    )
    op.add_column(
        "student_parents",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "student_parents",
        sa.Column(
            "can_pickup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "student_parents",
        sa.Column(
            "can_view_academics",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "student_parents",
        sa.Column(
            "can_view_behaviour",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Single named FK — not duplicated inside add_column above.
    op.create_foreign_key(
        "fk_student_parents_family_id",
        "student_parents",
        "families",
        ["family_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_student_parents_family_id", "student_parents", ["family_id"]
    )


def downgrade() -> None:
    # Reverse order: remove the FK and index first, then the columns,
    # then the new tables in reverse dependency order.

    op.drop_index("ix_student_parents_family_id", table_name="student_parents")
    op.drop_constraint(
        "fk_student_parents_family_id", "student_parents", type_="foreignkey"
    )
    op.drop_column("student_parents", "can_view_behaviour")
    op.drop_column("student_parents", "can_view_academics")
    op.drop_column("student_parents", "can_pickup")
    op.drop_column("student_parents", "is_primary")
    op.drop_column("student_parents", "family_id")

    op.drop_index("ix_family_timeline_occurred_at", table_name="family_timeline_events")
    op.drop_index("ix_family_timeline_student_id", table_name="family_timeline_events")
    op.drop_index("ix_family_timeline_family_id", table_name="family_timeline_events")
    op.drop_index("ix_family_timeline_tenant_id", table_name="family_timeline_events")
    op.drop_table("family_timeline_events")

    op.drop_index("ix_parent_preferences_user_id", table_name="parent_preferences")
    op.drop_index("ix_parent_preferences_tenant_id", table_name="parent_preferences")
    op.drop_table("parent_preferences")

    op.drop_index("ix_families_tenant_id", table_name="families")
    op.drop_table("families")
