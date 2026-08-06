"""phase_10a_calendar_lifecycle_and_pdf_intake

Revision ID: f91c2d7a6b55
Revises: d2f6e7a9b4c1
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f91c2d7a6b55"
down_revision: Union[str, None] = "d2f6e7a9b4c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("operational_calendar_events") as batch_op:
        batch_op.add_column(sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="draft"))
        batch_op.add_column(sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("previous_version_event_id", sa.UUID(), nullable=True))
        batch_op.add_column(sa.Column("change_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("impact_scope_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
        batch_op.add_column(sa.Column("notification_plan_status", sa.String(length=30), nullable=False, server_default="not_planned"))
        batch_op.add_column(sa.Column("notification_plan_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
        batch_op.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("published_by_user_id", sa.UUID(), nullable=True))
        batch_op.create_index("ix_operational_calendar_events_lifecycle_status", ["lifecycle_status"], unique=False)
        batch_op.create_index("ix_operational_calendar_events_version_number", ["version_number"], unique=False)
        batch_op.create_index("ix_operational_calendar_events_previous_version_event_id", ["previous_version_event_id"], unique=False)
        batch_op.create_index("ix_operational_calendar_events_notification_plan_status", ["notification_plan_status"], unique=False)
        batch_op.create_foreign_key(
            "fk_operational_calendar_events_previous_version_event_id",
            "operational_calendar_events",
            ["previous_version_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_operational_calendar_events_published_by_user_id",
            "users",
            ["published_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        """
        UPDATE operational_calendar_events
        SET lifecycle_status = CASE
            WHEN review_status = 'approved' THEN 'approved'
            WHEN review_status = 'pending_review' THEN 'pending_review'
            WHEN review_status = 'rejected' THEN 'rejected'
            ELSE 'draft'
        END
        """
    )

    op.create_check_constraint(
        "ck_operational_calendar_lifecycle_status",
        "operational_calendar_events",
        "lifecycle_status IN ('draft','pending_review','approved','published','rescheduled','cancelled','superseded','archived','rejected')",
    )
    op.create_check_constraint(
        "ck_operational_calendar_version_number_positive",
        "operational_calendar_events",
        "version_number > 0",
    )
    op.create_check_constraint(
        "ck_operational_calendar_notification_plan_status",
        "operational_calendar_events",
        "notification_plan_status IN ('not_planned','planned','queued','sent','cancelled')",
    )

    op.create_table(
        "calendar_source_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("import_batch_id", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="pdf_upload"),
        sa.Column("extraction_status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source_type IN ('pdf_upload','manual_text')", name="ck_calendar_source_documents_source_type"),
        sa.CheckConstraint(
            "extraction_status IN ('uploaded','processing','ocr_required','review_ready','processed','failed','cancelled','committed')",
            name="ck_calendar_source_documents_extraction_status",
        ),
        sa.CheckConstraint("page_count >= 0", name="ck_calendar_source_documents_page_count_non_negative"),
        sa.CheckConstraint("extracted_char_count >= 0", name="ck_calendar_source_documents_char_count_non_negative"),
    )
    op.create_index("ix_calendar_source_documents_tenant_id", "calendar_source_documents", ["tenant_id"], unique=False)
    op.create_index("ix_calendar_source_documents_import_batch_id", "calendar_source_documents", ["import_batch_id"], unique=False)
    op.create_index("ix_calendar_source_documents_file_sha256", "calendar_source_documents", ["file_sha256"], unique=False)
    op.create_index("ix_calendar_source_documents_extraction_status", "calendar_source_documents", ["extraction_status"], unique=False)

    op.create_table(
        "calendar_source_pages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("text_excerpt", sa.String(length=500), nullable=True),
        sa.Column("extracted_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_document_id"], ["calendar_source_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("page_number > 0", name="ck_calendar_source_pages_page_number_positive"),
        sa.CheckConstraint("extracted_char_count >= 0", name="ck_calendar_source_pages_char_count_non_negative"),
        sa.UniqueConstraint("source_document_id", "page_number", name="uq_calendar_source_pages_document_page"),
    )
    op.create_index("ix_calendar_source_pages_tenant_id", "calendar_source_pages", ["tenant_id"], unique=False)
    op.create_index("ix_calendar_source_pages_source_document_id", "calendar_source_pages", ["source_document_id"], unique=False)

    op.create_table(
        "calendar_event_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("source_page_id", sa.UUID(), nullable=True),
        sa.Column("proposed_event_name", sa.String(length=255), nullable=False),
        sa.Column("proposed_description", sa.Text(), nullable=True),
        sa.Column("proposed_start_date", sa.Date(), nullable=True),
        sa.Column("proposed_end_date", sa.Date(), nullable=True),
        sa.Column("proposed_event_type", sa.String(length=50), nullable=False),
        sa.Column("proposed_teaching_day_effect", sa.String(length=40), nullable=False, server_default="no_change"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("candidate_status", sa.String(length=30), nullable=False, server_default="proposed"),
        sa.Column("date_parse_status", sa.String(length=30), nullable=False, server_default="missing"),
        sa.Column("uncertainty_note", sa.String(length=255), nullable=True),
        sa.Column("classification_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("validation_issues_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("source_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_event_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["applied_event_id"], ["operational_calendar_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["calendar_source_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_page_id"], ["calendar_source_pages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "proposed_end_date IS NULL OR proposed_start_date IS NULL OR proposed_end_date >= proposed_start_date",
            name="ck_calendar_event_candidates_date_range",
        ),
        sa.CheckConstraint(
            "proposed_event_type IN ('teaching_day_override','public_holiday','school_holiday','examination_period','professional_development','parent_conference','school_event','half_day','special_schedule','term_boundary','information_only')",
            name="ck_calendar_event_candidates_event_type",
        ),
        sa.CheckConstraint(
            "proposed_teaching_day_effect IN ('no_change','non_teaching_day','teaching_day','special_schedule')",
            name="ck_calendar_event_candidates_teaching_day_effect",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)",
            name="ck_calendar_event_candidates_confidence_score",
        ),
        sa.CheckConstraint(
            "candidate_status IN ('proposed','edited','approved','rejected','committed')",
            name="ck_calendar_event_candidates_status",
        ),
        sa.CheckConstraint(
            "date_parse_status IN ('parsed','ambiguous','hijri_unresolved','invalid_range','missing')",
            name="ck_calendar_event_candidates_date_parse_status",
        ),
    )
    op.create_index("ix_calendar_event_candidates_tenant_id", "calendar_event_candidates", ["tenant_id"], unique=False)
    op.create_index("ix_calendar_event_candidates_source_document_id", "calendar_event_candidates", ["source_document_id"], unique=False)
    op.create_index("ix_calendar_event_candidates_source_page_id", "calendar_event_candidates", ["source_page_id"], unique=False)
    op.create_index("ix_calendar_event_candidates_candidate_status", "calendar_event_candidates", ["candidate_status"], unique=False)
    op.create_index("ix_calendar_event_candidates_applied_event_id", "calendar_event_candidates", ["applied_event_id"], unique=False)

    op.create_table(
        "calendar_notification_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_version_number", sa.Integer(), nullable=False),
        sa.Column("trigger_reason", sa.String(length=40), nullable=False),
        sa.Column("audience_scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("affected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("proposed_message", sa.Text(), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("urgency", sa.String(length=30), nullable=False, server_default="normal"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outbox_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("delivery_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("audit_reference_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("related_notification_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["operational_calendar_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_notification_id"], ["notifications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("event_version_number > 0", name="ck_calendar_notification_plans_version_positive"),
        sa.CheckConstraint(
            "trigger_reason IN ('event_published','reminder','event_updated','event_rescheduled','event_cancelled','urgent_change','weekly_calendar_summary')",
            name="ck_calendar_notification_plans_trigger_reason",
        ),
        sa.CheckConstraint("affected_count >= 0", name="ck_calendar_notification_plans_affected_count_non_negative"),
        sa.CheckConstraint("urgency IN ('low','normal','high','critical')", name="ck_calendar_notification_plans_urgency"),
        sa.CheckConstraint(
            "approval_status IN ('draft','pending_approval','approved','scheduled','ready','dispatched','partially_failed','failed','cancelled')",
            name="ck_calendar_notification_plans_approval_status",
        ),
        sa.CheckConstraint(
            "outbox_status IN ('draft','pending_approval','approved','scheduled','ready','dispatched','partially_failed','failed','cancelled')",
            name="ck_calendar_notification_plans_outbox_status",
        ),
    )
    op.create_index("ix_calendar_notification_plans_tenant_id", "calendar_notification_plans", ["tenant_id"], unique=False)
    op.create_index("ix_calendar_notification_plans_event_id", "calendar_notification_plans", ["event_id"], unique=False)
    op.create_index("ix_calendar_notification_plans_trigger_reason", "calendar_notification_plans", ["trigger_reason"], unique=False)
    op.create_index("ix_calendar_notification_plans_approval_status", "calendar_notification_plans", ["approval_status"], unique=False)
    op.create_index("ix_calendar_notification_plans_outbox_status", "calendar_notification_plans", ["outbox_status"], unique=False)

    op.create_table(
        "calendar_event_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("previous_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("new_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("changed_fields", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("approval_actor_user_id", sa.UUID(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("affected_stakeholder_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("notification_plan_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["operational_calendar_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notification_plan_id"], ["calendar_notification_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version_number > 0", name="ck_calendar_event_versions_version_positive"),
        sa.CheckConstraint(
            "change_type IN ('created','edited','submitted','approved','published','rescheduled','scope_changed','location_changed','cancelled','restored','archived')",
            name="ck_calendar_event_versions_change_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual','excel_import','csv_import','pdf_extraction','agent_recommendation','system_generated')",
            name="ck_calendar_event_versions_source_type",
        ),
        sa.UniqueConstraint("event_id", "version_number", "change_type", name="uq_calendar_event_versions_event_version_change"),
    )
    op.create_index("ix_calendar_event_versions_tenant_id", "calendar_event_versions", ["tenant_id"], unique=False)
    op.create_index("ix_calendar_event_versions_event_id", "calendar_event_versions", ["event_id"], unique=False)
    op.create_index("ix_calendar_event_versions_change_type", "calendar_event_versions", ["change_type"], unique=False)
    op.create_index("ix_calendar_event_versions_notification_plan_id", "calendar_event_versions", ["notification_plan_id"], unique=False)

    op.drop_constraint("ck_import_batches_entity_type", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_format", "import_batches", type_="check")
    op.create_check_constraint(
        "ck_import_batches_entity_type",
        "import_batches",
        "entity_type IN ('subjects','classes','teachers','students','parents','timetable_workbook','calendar_pdf')",
    )
    op.create_check_constraint(
        "ck_import_batches_format",
        "import_batches",
        "import_format IS NULL OR import_format IN ('csv','xlsx','pdf')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_import_batches_entity_type", "import_batches", type_="check")
    op.drop_constraint("ck_import_batches_format", "import_batches", type_="check")
    op.create_check_constraint(
        "ck_import_batches_entity_type",
        "import_batches",
        "entity_type IN ('subjects','classes','teachers','students','parents','timetable_workbook')",
    )
    op.create_check_constraint(
        "ck_import_batches_format",
        "import_batches",
        "import_format IS NULL OR import_format IN ('csv','xlsx')",
    )

    op.drop_index("ix_calendar_event_versions_notification_plan_id", table_name="calendar_event_versions")
    op.drop_index("ix_calendar_event_versions_change_type", table_name="calendar_event_versions")
    op.drop_index("ix_calendar_event_versions_event_id", table_name="calendar_event_versions")
    op.drop_index("ix_calendar_event_versions_tenant_id", table_name="calendar_event_versions")
    op.drop_table("calendar_event_versions")

    op.drop_index("ix_calendar_notification_plans_outbox_status", table_name="calendar_notification_plans")
    op.drop_index("ix_calendar_notification_plans_approval_status", table_name="calendar_notification_plans")
    op.drop_index("ix_calendar_notification_plans_trigger_reason", table_name="calendar_notification_plans")
    op.drop_index("ix_calendar_notification_plans_event_id", table_name="calendar_notification_plans")
    op.drop_index("ix_calendar_notification_plans_tenant_id", table_name="calendar_notification_plans")
    op.drop_table("calendar_notification_plans")

    op.drop_index("ix_calendar_event_candidates_applied_event_id", table_name="calendar_event_candidates")
    op.drop_index("ix_calendar_event_candidates_candidate_status", table_name="calendar_event_candidates")
    op.drop_index("ix_calendar_event_candidates_source_page_id", table_name="calendar_event_candidates")
    op.drop_index("ix_calendar_event_candidates_source_document_id", table_name="calendar_event_candidates")
    op.drop_index("ix_calendar_event_candidates_tenant_id", table_name="calendar_event_candidates")
    op.drop_table("calendar_event_candidates")

    op.drop_index("ix_calendar_source_pages_source_document_id", table_name="calendar_source_pages")
    op.drop_index("ix_calendar_source_pages_tenant_id", table_name="calendar_source_pages")
    op.drop_table("calendar_source_pages")

    op.drop_index("ix_calendar_source_documents_extraction_status", table_name="calendar_source_documents")
    op.drop_index("ix_calendar_source_documents_file_sha256", table_name="calendar_source_documents")
    op.drop_index("ix_calendar_source_documents_import_batch_id", table_name="calendar_source_documents")
    op.drop_index("ix_calendar_source_documents_tenant_id", table_name="calendar_source_documents")
    op.drop_table("calendar_source_documents")

    op.drop_constraint("ck_operational_calendar_lifecycle_status", "operational_calendar_events", type_="check")
    op.drop_constraint("ck_operational_calendar_version_number_positive", "operational_calendar_events", type_="check")
    op.drop_constraint("ck_operational_calendar_notification_plan_status", "operational_calendar_events", type_="check")

    with op.batch_alter_table("operational_calendar_events") as batch_op:
        batch_op.drop_constraint("fk_operational_calendar_events_published_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_operational_calendar_events_previous_version_event_id", type_="foreignkey")
        batch_op.drop_index("ix_operational_calendar_events_notification_plan_status")
        batch_op.drop_index("ix_operational_calendar_events_previous_version_event_id")
        batch_op.drop_index("ix_operational_calendar_events_version_number")
        batch_op.drop_index("ix_operational_calendar_events_lifecycle_status")
        batch_op.drop_column("published_by_user_id")
        batch_op.drop_column("published_at")
        batch_op.drop_column("notification_plan_json")
        batch_op.drop_column("notification_plan_status")
        batch_op.drop_column("impact_scope_json")
        batch_op.drop_column("change_reason")
        batch_op.drop_column("previous_version_event_id")
        batch_op.drop_column("version_number")
        batch_op.drop_column("lifecycle_status")
