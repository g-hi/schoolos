from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.ai.family_timeline import write_timeline_event
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.weekly_reports.authorization import (
    authorize_staff_for_student_action,
    ensure_can_review_or_publish,
)
from services.gateway.weekly_reports.evidence import (
    build_evidence_snapshot,
    resolve_reporting_period,
)
from services.gateway.weekly_reports.generation import (
    build_deterministic_draft,
    generate_optional_ai_draft,
)
from services.gateway.weekly_reports.schemas import (
    EditWeeklyReportRequest,
    GenerateDraftRequest,
    InitializeWeeklyReportRequest,
    StatusTransitionRequest,
)
from services.gateway.weekly_reports.transitions import can_transition
from services.gateway.weekly_reports.validation import validate_content_structure
from shared.db.models import StudentParent, Tenant, User
from shared.db.weekly_report_models import (
    WeeklyStudentReport,
    WeeklyStudentReportReviewEvent,
    WeeklyStudentReportVersion,
)


@dataclass(frozen=True)
class ServiceResult:
    report: WeeklyStudentReport
    created_version: WeeklyStudentReportVersion | None


class WeeklyReportService:
    def __init__(self, *, db: AsyncSession, tenant: Tenant, actor: User):
        self.db = db
        self.tenant = tenant
        self.actor = actor

    @staticmethod
    def _is_unique_report_integrity_error(exc: IntegrityError) -> bool:
        orig = getattr(exc, "orig", None)
        if orig is None:
            return False

        diag = getattr(orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name == "uq_weekly_report_per_student_week":
            return True

        sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        if sqlstate != "23505":
            return False

        message = str(orig).lower()
        return "uq_weekly_report_per_student_week" in message

    async def initialize_report(self, body: InitializeWeeklyReportRequest) -> ServiceResult:
        tenant_id = self.tenant.id
        actor_user_id = self.actor.id
        requested_student_id = uuid.UUID(body.student_id)
        assigned_reviewer_user_id = uuid.UUID(body.assigned_reviewer_user_id) if body.assigned_reviewer_user_id else None

        student_ctx = await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=tenant_id,
            actor=self.actor,
            student_id=requested_student_id,
            action="initialize",
        )
        student_id = student_ctx.student.id

        period = resolve_reporting_period(
            requested_week_start=body.week_start,
            tenant=self.tenant,
            timezone_override=body.timezone_override,
        )
        week_start = period.week_start

        existing_q = await self.db.execute(
            select(WeeklyStudentReport).where(
                WeeklyStudentReport.tenant_id == tenant_id,
                WeeklyStudentReport.student_id == student_id,
                WeeklyStudentReport.week_start == week_start,
            )
        )
        existing = existing_q.scalar_one_or_none()
        if existing:
            return ServiceResult(report=existing, created_version=None)

        report = WeeklyStudentReport(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            student_id=student_id,
            week_start=week_start,
            week_end=period.week_end,
            timezone_used=period.timezone_used,
            status="draft",
            row_version=1,
            created_by_user_id=actor_user_id,
            assigned_reviewer_user_id=assigned_reviewer_user_id,
        )
        self.db.add(report)

        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            if not self._is_unique_report_integrity_error(exc):
                raise

            existing_retry = await self.db.execute(
                select(WeeklyStudentReport).where(
                    WeeklyStudentReport.tenant_id == tenant_id,
                    WeeklyStudentReport.student_id == student_id,
                    WeeklyStudentReport.week_start == week_start,
                )
            )
            found = existing_retry.scalar_one_or_none()
            if found is None:
                raise
            return ServiceResult(report=found, created_version=None)

        evidence_snapshot = build_evidence_snapshot(
            student=student_ctx.student,
            klass=student_ctx.klass,
            period=period,
            actor=self.actor,
            staff_evidence=body.staff_evidence,
        )
        draft = build_deterministic_draft(
            student_display_name=student_ctx.student.name,
            class_name=f"{student_ctx.klass.grade}-{student_ctx.klass.section}",
            week_start=period.week_start.isoformat(),
            week_end=period.week_end.isoformat(),
            evidence_snapshot=evidence_snapshot,
        )

        version = WeeklyStudentReportVersion(
            id=uuid.uuid4(),
            report_id=report.id,
            version_number=1,
            source_type="manual",
            content_json=draft,
            evidence_snapshot_json=evidence_snapshot,
            validation_status="passed",
            validation_errors_json=[],
            created_by_user_id=actor_user_id,
        )
        self.db.add(version)
        await self.db.flush()

        report.current_version_number = 1

        event = WeeklyStudentReportReviewEvent(
            id=uuid.uuid4(),
            report_id=report.id,
            report_version_id=version.id,
            actor_user_id=actor_user_id,
            event_type="report_initialized",
            previous_status=None,
            new_status="draft",
            comment=None,
        )
        self.db.add(event)
        await self.db.flush()

        await log_action(
            db=self.db,
            tenant_id=tenant_id,
            action="report.initialized",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=actor_user_id,
            details={
                "student_id": str(student_id),
                "week_start": week_start.isoformat(),
            },
        )
        await self.db.commit()
        await self.db.refresh(report)
        return ServiceResult(report=report, created_version=version)

    async def get_report(self, *, report_id: uuid.UUID) -> WeeklyStudentReport:
        result = await self.db.execute(
            select(WeeklyStudentReport).where(
                WeeklyStudentReport.id == report_id,
                WeeklyStudentReport.tenant_id == self.tenant.id,
            )
        )
        report = result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

        await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="read",
        )
        return report

    async def _get_current_version(self, report: WeeklyStudentReport) -> WeeklyStudentReportVersion:
        if report.current_version_number is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Report has no working version.")

        version_result = await self.db.execute(
            select(WeeklyStudentReportVersion).where(
                WeeklyStudentReportVersion.report_id == report.id,
                WeeklyStudentReportVersion.version_number == report.current_version_number,
            )
        )
        version = version_result.scalar_one_or_none()
        if not version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Report working version is missing.")
        return version

    def _assert_row_version(self, *, report: WeeklyStudentReport, expected_row_version: int) -> None:
        if report.row_version != expected_row_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The report was updated by another user. Refresh and try again.",
            )

    async def edit_report(self, *, report_id: uuid.UUID, body: EditWeeklyReportRequest) -> ServiceResult:
        report = await self.get_report(report_id=report_id)
        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        period = resolve_reporting_period(
            requested_week_start=report.week_start,
            tenant=self.tenant,
            timezone_override=report.timezone_used,
        )
        student_ctx = await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="edit",
        )

        current_version = await self._get_current_version(report)

        content_json = dict(current_version.content_json or {})
        if body.title is not None:
            content_json["title"] = body.title
        if body.sections:
            content_json["sections"] = [
                {
                    "section_type": section.section_type,
                    "content": section.content,
                    "used_evidence_ids": ["staff_input_1"],
                }
                for section in body.sections
            ]

        evidence_snapshot = build_evidence_snapshot(
            student=student_ctx.student,
            klass=student_ctx.klass,
            period=period,
            actor=self.actor,
            staff_evidence=body.staff_evidence,
        )

        validation_errors = validate_content_structure(content_json, evidence_snapshot)
        validation_status = "passed" if not validation_errors else "failed"

        next_version_number = (report.current_version_number or 0) + 1
        new_version = WeeklyStudentReportVersion(
            id=uuid.uuid4(),
            report_id=report.id,
            version_number=next_version_number,
            source_type="staff_revision",
            content_json=content_json,
            evidence_snapshot_json=evidence_snapshot,
            validation_status=validation_status,
            validation_errors_json=validation_errors,
            created_by_user_id=self.actor.id,
        )
        self.db.add(new_version)

        previous_status = report.status
        report.current_version_number = next_version_number
        report.row_version = report.row_version + 1

        if previous_status in {"approved", "published"}:
            report.status = "pending_review"
            report.approved_version_number = None
            report.approved_by_user_id = None
            report.approved_at = None

        event = WeeklyStudentReportReviewEvent(
            id=uuid.uuid4(),
            report_id=report.id,
            report_version_id=new_version.id,
            actor_user_id=self.actor.id,
            event_type="report_edited",
            previous_status=previous_status,
            new_status=report.status,
            comment=None,
        )
        self.db.add(event)

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.edited",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={"version_number": next_version_number, "validation_status": validation_status},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return ServiceResult(report=report, created_version=new_version)

    async def generate_draft(
        self,
        *,
        report_id: uuid.UUID,
        body: GenerateDraftRequest,
        provider: LLMProvider | None,
    ) -> ServiceResult:
        report = await self.get_report(report_id=report_id)
        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        student_ctx = await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="generate",
        )

        current_version = await self._get_current_version(report)
        evidence_snapshot = dict(current_version.evidence_snapshot_json or {})

        decision = can_transition(previous_status=report.status, new_status="generating")
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=decision.reason)

        previous_status = report.status
        report.status = "generating"
        report.row_version = report.row_version + 1

        deterministic_draft = build_deterministic_draft(
            student_display_name=student_ctx.student.name,
            class_name=f"{student_ctx.klass.grade}-{student_ctx.klass.section}",
            week_start=report.week_start.isoformat(),
            week_end=report.week_end.isoformat(),
            evidence_snapshot=evidence_snapshot,
        )

        ai_output, ai_error = await generate_optional_ai_draft(
            provider=provider,
            deterministic_draft=deterministic_draft,
            evidence_snapshot=evidence_snapshot,
            use_ai=body.use_ai,
        )

        validation_errors = validate_content_structure(ai_output, evidence_snapshot)
        if validation_errors:
            # Discard invalid AI wording and preserve deterministic output.
            ai_output = deterministic_draft
            validation_errors = validate_content_structure(ai_output, evidence_snapshot)

        validation_status = "passed" if not validation_errors else "failed"

        next_status = "pending_review" if validation_status == "passed" else "validation_failed"
        if ai_error:
            next_status = "generation_failed"

        transition = can_transition(previous_status="generating", new_status=next_status)
        if not transition.allowed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=transition.reason)

        next_version_number = (report.current_version_number or 0) + 1
        new_version = WeeklyStudentReportVersion(
            id=uuid.uuid4(),
            report_id=report.id,
            version_number=next_version_number,
            source_type="ai_generated" if body.use_ai else "manual",
            content_json=ai_output,
            evidence_snapshot_json=evidence_snapshot,
            validation_status=validation_status,
            validation_errors_json=validation_errors,
            created_by_user_id=self.actor.id,
        )
        self.db.add(new_version)

        report.current_version_number = next_version_number
        report.status = next_status
        report.row_version = report.row_version + 1

        event = WeeklyStudentReportReviewEvent(
            id=uuid.uuid4(),
            report_id=report.id,
            report_version_id=new_version.id,
            actor_user_id=self.actor.id,
            event_type="draft_generated",
            previous_status=previous_status,
            new_status=next_status,
            comment=ai_error,
        )
        self.db.add(event)

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.generation_completed" if not ai_error else "report.generation_failed",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={"version_number": next_version_number, "error": ai_error},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return ServiceResult(report=report, created_version=new_version)

    async def _transition_status(
        self,
        *,
        report: WeeklyStudentReport,
        new_status: str,
        comment: str | None,
        report_version_id: uuid.UUID | None,
        event_type: str,
    ) -> None:
        previous_status = report.status
        decision = can_transition(previous_status=previous_status, new_status=new_status)
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=decision.reason)

        report.status = new_status
        report.row_version = report.row_version + 1

        event = WeeklyStudentReportReviewEvent(
            id=uuid.uuid4(),
            report_id=report.id,
            report_version_id=report_version_id,
            actor_user_id=self.actor.id,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            comment=comment,
        )
        self.db.add(event)

    async def submit_for_review(self, *, report_id: uuid.UUID, body: StatusTransitionRequest) -> WeeklyStudentReport:
        report = await self.get_report(report_id=report_id)
        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        await self._transition_status(
            report=report,
            new_status="pending_review",
            comment=body.comment,
            report_version_id=None,
            event_type="submitted_for_review",
        )

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.submitted_for_review",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def request_changes(self, *, report_id: uuid.UUID, body: StatusTransitionRequest) -> WeeklyStudentReport:
        ensure_can_review_or_publish(self.actor)
        report = await self.get_report(report_id=report_id)
        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        await self._transition_status(
            report=report,
            new_status="changes_requested",
            comment=body.comment,
            report_version_id=None,
            event_type="changes_requested",
        )

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.changes_requested",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def approve(self, *, report_id: uuid.UUID, body: StatusTransitionRequest) -> WeeklyStudentReport:
        ensure_can_review_or_publish(self.actor)

        locked_result = await self.db.execute(
            select(WeeklyStudentReport)
            .where(
                WeeklyStudentReport.id == report_id,
                WeeklyStudentReport.tenant_id == self.tenant.id,
            )
            .with_for_update()
        )
        report = locked_result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

        await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="approve",
        )

        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        if report.created_by_user_id == self.actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers cannot approve their own reports.")

        await self._transition_status(
            report=report,
            new_status="approved",
            comment=body.comment,
            report_version_id=None,
            event_type="approved",
        )
        report.approved_version_number = report.current_version_number
        report.approved_by_user_id = self.actor.id
        report.approved_at = datetime.now(timezone.utc)

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.approved",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={"approved_version_number": report.approved_version_number},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def publish(self, *, report_id: uuid.UUID, body: StatusTransitionRequest) -> WeeklyStudentReport:
        ensure_can_review_or_publish(self.actor)

        locked_result = await self.db.execute(
            select(WeeklyStudentReport)
            .where(
                WeeklyStudentReport.id == report_id,
                WeeklyStudentReport.tenant_id == self.tenant.id,
            )
            .with_for_update()
        )
        report = locked_result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

        await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="publish",
        )

        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        if report.approved_version_number is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Report must be approved before publication.")

        already_published_same = (
            report.status == "published" and report.published_version_number == report.approved_version_number
        )
        if not already_published_same:
            await self._transition_status(
                report=report,
                new_status="published",
                comment=body.comment,
                report_version_id=None,
                event_type="published",
            )
            report.published_version_number = report.approved_version_number
            report.published_by_user_id = self.actor.id
            report.published_at = datetime.now(timezone.utc)

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.published",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={"published_version_number": report.published_version_number},
        )

        student_ctx = await authorize_staff_for_student_action(
            db=self.db,
            tenant_id=self.tenant.id,
            actor=self.actor,
            student_id=report.student_id,
            action="publish",
        )

        published_version_id = await self._resolve_version_id(report=report, version_number=report.published_version_number)
        idempotency_key = f"weekly-report-published:{report.id}:{published_version_id}"

        family_rows = await self.db.execute(
            select(StudentParent.family_id).distinct()
            .where(
                StudentParent.student_id == report.student_id,
                StudentParent.family_id.isnot(None),
            )
        )
        family_ids = [row[0] for row in family_rows.all() if row[0] is not None]

        for family_id in family_ids:
            await write_timeline_event(
                db=self.db,
                tenant_id=self.tenant.id,
                family_id=family_id,
                student_id=report.student_id,
                event_type="weekly_report.published",
                event_category="academic",
                title=f"{student_ctx.student.name}'s weekly report for {report.week_start.isoformat()} to {report.week_end.isoformat()} is now available.",
                occurred_at=report.published_at or datetime.now(timezone.utc),
                source_module="weekly_reports",
                source_reference=None,
                event_key=idempotency_key,
                action_url=f"/parent/reports/{report.id}",
            )

        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def archive(self, *, report_id: uuid.UUID, body: StatusTransitionRequest) -> WeeklyStudentReport:
        ensure_can_review_or_publish(self.actor)
        report = await self.get_report(report_id=report_id)
        self._assert_row_version(report=report, expected_row_version=body.expected_row_version)

        await self._transition_status(
            report=report,
            new_status="archived",
            comment=body.comment,
            report_version_id=None,
            event_type="archived",
        )
        report.archived_at = datetime.now(timezone.utc)

        await log_action(
            db=self.db,
            tenant_id=self.tenant.id,
            action="report.archived",
            entity_type="WeeklyStudentReport",
            entity_id=report.id,
            actor_id=self.actor.id,
            details={},
        )
        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def _resolve_version_id(self, *, report: WeeklyStudentReport, version_number: int | None) -> uuid.UUID | None:
        if version_number is None:
            return None
        row = await self.db.execute(
            select(WeeklyStudentReportVersion.id).where(
                WeeklyStudentReportVersion.report_id == report.id,
                WeeklyStudentReportVersion.version_number == version_number,
            )
        )
        return row.scalar_one_or_none()
