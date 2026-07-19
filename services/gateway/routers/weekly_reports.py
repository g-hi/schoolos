from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.copilot.providers.factory import get_provider
from services.gateway.weekly_reports.authorization import authorize_staff_for_student_action
from services.gateway.weekly_reports.schemas import (
    EditWeeklyReportRequest,
    GenerateDraftRequest,
    InitializeWeeklyReportRequest,
    ReviewEventResponse,
    WeeklyReportActionResult,
    WeeklyReportDetailResponse,
    WeeklyReportListItem,
    WeeklyReportStudentOption,
    WeeklyReportVersionResponse,
    StatusTransitionRequest,
)
from services.gateway.weekly_reports.service import WeeklyReportService
from shared.auth.dependencies import (
    resolve_authenticated_leadership,
    resolve_authenticated_staff,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Class, Student, Tenant, User
from shared.db.weekly_report_models import (
    WeeklyStudentReport,
    WeeklyStudentReportReviewEvent,
    WeeklyStudentReportVersion,
)
from services.gateway.weekly_reports.authorization import list_staff_authorized_students

router = APIRouter(prefix="/weekly-reports", tags=["Weekly Reports"])


def _service(*, db: AsyncSession, tenant: Tenant, actor: User) -> WeeklyReportService:
    return WeeklyReportService(db=db, tenant=tenant, actor=actor)


async def _load_student_label(*, db: AsyncSession, tenant_id: uuid.UUID, student_id: uuid.UUID) -> tuple[str, str]:
    result = await db.execute(
        select(Student, Class)
        .join(Class, Class.id == Student.class_id)
        .where(
            Student.id == student_id,
            Student.tenant_id == tenant_id,
        )
    )
    row = result.first()
    if not row:
        return "Student", "Unknown"
    student, klass = row
    return student.name, f"{klass.grade}-{klass.section}"


@router.get("", response_model=list[WeeklyReportListItem], summary="List weekly reports")
async def list_weekly_reports(
    student_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    query = select(WeeklyStudentReport).where(WeeklyStudentReport.tenant_id == tenant.id)
    if student_id:
        query = query.where(WeeklyStudentReport.student_id == student_id)
    if status_filter:
        query = query.where(WeeklyStudentReport.status == status_filter)
    query = query.order_by(WeeklyStudentReport.week_start.desc(), WeeklyStudentReport.updated_at.desc()).limit(200)

    rows = (await db.execute(query)).scalars().all()
    items: list[WeeklyReportListItem] = []

    for report in rows:
        try:
            await authorize_staff_for_student_action(
                db=db,
                tenant_id=tenant.id,
                actor=actor,
                student_id=report.student_id,
                action="list",
            )
        except HTTPException:
            continue

        student_name, class_name = await _load_student_label(db=db, tenant_id=tenant.id, student_id=report.student_id)
        items.append(
            WeeklyReportListItem(
                report_id=str(report.id),
                student_id=str(report.student_id),
                student_display_name=student_name,
                class_name=class_name,
                week_start=report.week_start,
                week_end=report.week_end,
                status=report.status,
                current_version_number=report.current_version_number,
                approved_version_number=report.approved_version_number,
                published_version_number=report.published_version_number,
                row_version=report.row_version,
                updated_at=report.updated_at,
            )
        )

    return items


@router.get("/students", response_model=list[WeeklyReportStudentOption], summary="List authorized students")
async def list_authorized_weekly_report_students(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    rows = await list_staff_authorized_students(db=db, tenant_id=tenant.id, actor=actor)
    return [
        WeeklyReportStudentOption(
            student_id=str(student.id),
            student_display_name=student.name,
            class_name=f"{klass.grade}-{klass.section}",
        )
        for student, klass in rows
    ]


@router.post("/init", response_model=WeeklyReportActionResult, summary="Initialize one weekly report")
async def initialize_weekly_report(
    body: InitializeWeeklyReportRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    result = await _service(db=db, tenant=tenant, actor=actor).initialize_report(body)
    return WeeklyReportActionResult(
        report_id=str(result.report.id),
        status=result.report.status,
        row_version=result.report.row_version,
        current_version_number=result.report.current_version_number,
    )


@router.get("/{report_id}", response_model=WeeklyReportDetailResponse, summary="Get weekly report detail")
async def get_weekly_report(
    report_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    service = _service(db=db, tenant=tenant, actor=actor)
    report = await service.get_report(report_id=report_id)

    current_version_result = await db.execute(
        select(WeeklyStudentReportVersion).where(
            WeeklyStudentReportVersion.report_id == report.id,
            WeeklyStudentReportVersion.version_number == report.current_version_number,
        )
    )
    current_version = current_version_result.scalar_one_or_none()
    if not current_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Current version not found.")

    all_versions = (
        await db.execute(
            select(WeeklyStudentReportVersion)
            .where(WeeklyStudentReportVersion.report_id == report.id)
            .order_by(WeeklyStudentReportVersion.version_number.desc())
        )
    ).scalars().all()

    student_name, class_name = await _load_student_label(db=db, tenant_id=tenant.id, student_id=report.student_id)

    return WeeklyReportDetailResponse(
        report_id=str(report.id),
        student_id=str(report.student_id),
        student_display_name=student_name,
        class_name=class_name,
        week_start=report.week_start,
        week_end=report.week_end,
        timezone_used=report.timezone_used,
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
        approved_version_number=report.approved_version_number,
        published_version_number=report.published_version_number,
        current_content=dict(current_version.content_json or {}),
        current_evidence_snapshot=dict(current_version.evidence_snapshot_json or {}),
        current_validation_status=current_version.validation_status,
        current_validation_errors=list(current_version.validation_errors_json or []),
        versions=[
            WeeklyReportVersionResponse(
                version_id=str(version.id),
                version_number=version.version_number,
                source_type=version.source_type,
                validation_status=version.validation_status,
                created_by_user_id=str(version.created_by_user_id) if version.created_by_user_id else None,
                created_at=version.created_at,
            )
            for version in all_versions
        ],
    )


@router.patch("/{report_id}/draft", response_model=WeeklyReportActionResult, summary="Edit weekly report draft")
async def edit_weekly_report_draft(
    report_id: uuid.UUID,
    body: EditWeeklyReportRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    result = await _service(db=db, tenant=tenant, actor=actor).edit_report(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(result.report.id),
        status=result.report.status,
        row_version=result.report.row_version,
        current_version_number=result.report.current_version_number,
    )


@router.post("/{report_id}/generate", response_model=WeeklyReportActionResult, summary="Generate weekly report draft")
async def generate_weekly_report_draft(
    report_id: uuid.UUID,
    body: GenerateDraftRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    provider = get_provider() if body.use_ai else None
    result = await _service(db=db, tenant=tenant, actor=actor).generate_draft(
        report_id=report_id,
        body=body,
        provider=provider,
    )
    return WeeklyReportActionResult(
        report_id=str(result.report.id),
        status=result.report.status,
        row_version=result.report.row_version,
        current_version_number=result.report.current_version_number,
    )


@router.post("/{report_id}/submit-review", response_model=WeeklyReportActionResult, summary="Submit report for review")
async def submit_weekly_report_for_review(
    report_id: uuid.UUID,
    body: StatusTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).submit_for_review(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(report.id),
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
    )


@router.post("/{report_id}/request-changes", response_model=WeeklyReportActionResult, summary="Request changes")
async def request_weekly_report_changes(
    report_id: uuid.UUID,
    body: StatusTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).request_changes(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(report.id),
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
    )


@router.post("/{report_id}/approve", response_model=WeeklyReportActionResult, summary="Approve report")
async def approve_weekly_report(
    report_id: uuid.UUID,
    body: StatusTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).approve(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(report.id),
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
    )


@router.post("/{report_id}/publish", response_model=WeeklyReportActionResult, summary="Publish report")
async def publish_weekly_report(
    report_id: uuid.UUID,
    body: StatusTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).publish(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(report.id),
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
    )


@router.post("/{report_id}/archive", response_model=WeeklyReportActionResult, summary="Archive report")
async def archive_weekly_report(
    report_id: uuid.UUID,
    body: StatusTransitionRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).archive(report_id=report_id, body=body)
    return WeeklyReportActionResult(
        report_id=str(report.id),
        status=report.status,
        row_version=report.row_version,
        current_version_number=report.current_version_number,
    )


@router.get("/{report_id}/versions", response_model=list[WeeklyReportVersionResponse], summary="View version history")
async def list_weekly_report_versions(
    report_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).get_report(report_id=report_id)

    rows = (
        await db.execute(
            select(WeeklyStudentReportVersion)
            .where(WeeklyStudentReportVersion.report_id == report.id)
            .order_by(WeeklyStudentReportVersion.version_number.desc())
        )
    ).scalars().all()

    return [
        WeeklyReportVersionResponse(
            version_id=str(row.id),
            version_number=row.version_number,
            source_type=row.source_type,
            validation_status=row.validation_status,
            created_by_user_id=str(row.created_by_user_id) if row.created_by_user_id else None,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{report_id}/review-events", response_model=list[ReviewEventResponse], summary="View review history")
async def list_weekly_report_review_events(
    report_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_staff),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    report = await _service(db=db, tenant=tenant, actor=actor).get_report(report_id=report_id)

    rows = (
        await db.execute(
            select(WeeklyStudentReportReviewEvent)
            .where(WeeklyStudentReportReviewEvent.report_id == report.id)
            .order_by(WeeklyStudentReportReviewEvent.created_at.desc())
        )
    ).scalars().all()

    return [
        ReviewEventResponse(
            event_id=str(row.id),
            report_id=str(row.report_id),
            report_version_id=str(row.report_version_id) if row.report_version_id else None,
            actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
            event_type=row.event_type,
            previous_status=row.previous_status,
            new_status=row.new_status,
            comment=row.comment,
            created_at=row.created_at,
        )
        for row in rows
    ]
