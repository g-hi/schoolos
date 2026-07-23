"""phase_85b_announcements

Revision ID: c85b_announcements
Revises: b6d4fe19f7c2
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c85b_announcements"
down_revision: Union[str, None] = "b6d4fe19f7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publication_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publication_claimed_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft','scheduled','publishing','published','archived')", name="valid_announcement_status"),
    )
    op.create_table(
        "announcement_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_key", sa.String(300), nullable=False),
        sa.Column("grade", sa.String(50), nullable=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("target_type IN ('school','grade','class','family','student')", name="valid_announcement_target_type"),
        sa.CheckConstraint("(target_type = 'school' AND grade IS NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'grade' AND grade IS NOT NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'class' AND grade IS NULL AND class_id IS NOT NULL AND family_id IS NULL AND student_id IS NULL) OR (target_type = 'family' AND grade IS NULL AND class_id IS NULL AND family_id IS NOT NULL AND student_id IS NULL) OR (target_type = 'student' AND grade IS NULL AND class_id IS NULL AND family_id IS NULL AND student_id IS NOT NULL)", name="valid_announcement_target_shape"),
        sa.UniqueConstraint("announcement_id", "target_key", name="uq_announcement_target_key"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("announcements.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("delivery_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("delivery_status IN ('pending','delivered','partial','failed','skipped')", name="valid_notification_delivery_status"),
        sa.UniqueConstraint("announcement_id", "recipient_user_id", name="uq_announcement_notification_recipient"),
    )
    op.add_column("messages", sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_messages_notification_id", "messages", "notifications", ["notification_id"], ["id"], ondelete="SET NULL")
    for name, table, columns in (
        ("ix_announcements_tenant_id", "announcements", ["tenant_id"]),
        ("ix_announcements_status", "announcements", ["status"]),
        ("ix_announcements_scheduled_at", "announcements", ["scheduled_at"]),
        ("ix_announcements_published_at", "announcements", ["published_at"]),
        ("ix_announcements_publication_claimed_at", "announcements", ["publication_claimed_at"]),
        ("ix_announcement_targets_tenant_id", "announcement_targets", ["tenant_id"]),
        ("ix_announcement_targets_announcement_id", "announcement_targets", ["announcement_id"]),
        ("ix_announcement_targets_class_id", "announcement_targets", ["class_id"]),
        ("ix_announcement_targets_family_id", "announcement_targets", ["family_id"]),
        ("ix_announcement_targets_student_id", "announcement_targets", ["student_id"]),
        ("ix_notifications_tenant_id", "notifications", ["tenant_id"]),
        ("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"]),
        ("ix_notifications_announcement_id", "notifications", ["announcement_id"]),
        ("ix_notifications_delivery_status", "notifications", ["delivery_status"]),
        ("ix_messages_notification_id", "messages", ["notification_id"]),
    ):
        op.create_index(name, table, columns)


def downgrade() -> None:
    op.drop_index("ix_messages_notification_id", table_name="messages")
    op.drop_constraint("fk_messages_notification_id", "messages", type_="foreignkey")
    op.drop_column("messages", "notification_id")
    for name, table in (
        ("ix_notifications_delivery_status", "notifications"),
        ("ix_notifications_announcement_id", "notifications"),
        ("ix_notifications_recipient_user_id", "notifications"),
        ("ix_notifications_tenant_id", "notifications"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_table("notifications")
    for name in ("ix_announcement_targets_student_id", "ix_announcement_targets_family_id", "ix_announcement_targets_class_id", "ix_announcement_targets_announcement_id", "ix_announcement_targets_tenant_id"):
        op.drop_index(name, table_name="announcement_targets")
    op.drop_table("announcement_targets")
    for name in ("ix_announcements_publication_claimed_at", "ix_announcements_published_at", "ix_announcements_scheduled_at", "ix_announcements_status", "ix_announcements_tenant_id"):
        op.drop_index(name, table_name="announcements")
    op.drop_table("announcements")
