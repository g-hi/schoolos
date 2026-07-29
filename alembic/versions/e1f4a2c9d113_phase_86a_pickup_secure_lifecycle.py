"""phase_86a_pickup_secure_lifecycle

Revision ID: e1f4a2c9d113
Revises: c85b_announcements
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f4a2c9d113"
down_revision: Union[str, None] = "c85b_announcements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pickup_requests", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("called_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pickup_requests", sa.Column("verification_method", sa.String(length=100), nullable=True))
    op.add_column("pickup_requests", sa.Column("verification_note", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_pickup_requests_cancelled_by_users",
        "pickup_requests",
        "users",
        ["cancelled_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pickup_requests_verified_by_users",
        "pickup_requests",
        "users",
        ["verified_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pickup_requests_verified_by_users", "pickup_requests", type_="foreignkey")
    op.drop_constraint("fk_pickup_requests_cancelled_by_users", "pickup_requests", type_="foreignkey")

    op.drop_column("pickup_requests", "verification_note")
    op.drop_column("pickup_requests", "verification_method")
    op.drop_column("pickup_requests", "verified_at")
    op.drop_column("pickup_requests", "verified_by")
    op.drop_column("pickup_requests", "cancelled_by")
    op.drop_column("pickup_requests", "cancelled_at")
    op.drop_column("pickup_requests", "completed_at")
    op.drop_column("pickup_requests", "prepared_at")
    op.drop_column("pickup_requests", "called_at")
    op.drop_column("pickup_requests", "acknowledged_at")
