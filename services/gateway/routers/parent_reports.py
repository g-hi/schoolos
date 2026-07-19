from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.weekly_reports.schemas import (
    ParentPublishedReportDetail,
    ParentPublishedReportListItem,
)
from shared.auth.dependencies import (
    resolve_authenticated_parent,
    validate_parent_student_access,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Class, Student, StudentParent, Tenant, User
from shared.db.weekly_report_models import WeeklyStudentReport, WeeklyStudentReportVersion

router = APIRouter(prefix="/parent/reports", tags=["Parent Reports"])


@router.get("", response_model=list[ParentPublishedReportListItem], summary="List published weekly reports")
async def list_parent_published_reports(
    student_id: uuid.UUID | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    if student_id is not None:
        await validate_parent_student_access(student_id=student_id, parent=parent, tenant=tenant, db=db)

    query = (
        select(WeeklyStudentReport, Student, Class)
        .join(Student, Student.id == WeeklyStudentReport.student_id)
        .join(Class, Class.id == Student.class_id)
        .join(
            StudentParent,
            (StudentParent.student_id == WeeklyStudentReport.student_id)
            & (StudentParent.parent_id == parent.id),
        )
        .where(
            WeeklyStudentReport.tenant_id == tenant.id,
            WeeklyStudentReport.status == "published",
            WeeklyStudentReport.published_version_number.isnot(None),
            WeeklyStudentReport.published_at.isnot(None),
            Student.tenant_id == tenant.id,
        )
        .order_by(WeeklyStudentReport.week_start.desc(), WeeklyStudentReport.published_at.desc())
        .limit(200)
    )
    if student_id is not None:
        query = query.where(WeeklyStudentReport.student_id == student_id)

    rows = (await db.execute(query)).all()
    items: list[ParentPublishedReportListItem] = []

    for report, student, klass in rows:
        version_result = await db.execute(
            select(WeeklyStudentReportVersion).where(
                WeeklyStudentReportVersion.report_id == report.id,
                WeeklyStudentReportVersion.version_number == report.published_version_number,
            )
        )
        version = version_result.scalar_one_or_none()
        if not version:
            continue
        content = dict(version.content_json or {})
        items.append(
            ParentPublishedReportListItem(
                report_id=str(report.id),
                student_id=str(report.student_id),
                student_display_name=student.name,
                class_name=f"{klass.grade}-{klass.section}",
                week_start=report.week_start,
                week_end=report.week_end,
                title=str(content.get("title") or "Weekly Report"),
                published_at=report.published_at,
            )
        )

    return items


@router.get("/{report_id}", response_model=ParentPublishedReportDetail, summary="Get one published weekly report")
async def get_parent_published_report(
    report_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    parent: User = Depends(resolve_authenticated_parent),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        select(WeeklyStudentReport, Student, Class)
        .join(Student, Student.id == WeeklyStudentReport.student_id)
        .join(Class, Class.id == Student.class_id)
        .join(
            StudentParent,
            (StudentParent.student_id == WeeklyStudentReport.student_id)
            & (StudentParent.parent_id == parent.id),
        )
        .where(
            WeeklyStudentReport.id == report_id,
            WeeklyStudentReport.tenant_id == tenant.id,
            WeeklyStudentReport.status == "published",
            WeeklyStudentReport.published_version_number.isnot(None),
            WeeklyStudentReport.published_at.isnot(None),
            Student.tenant_id == tenant.id,
        )
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    report, student, klass = row

    version_result = await db.execute(
        select(WeeklyStudentReportVersion).where(
            WeeklyStudentReportVersion.report_id == report.id,
            WeeklyStudentReportVersion.version_number == report.published_version_number,
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    content = dict(version.content_json or {})

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="parent.report_viewed",
        entity_type="WeeklyStudentReport",
        entity_id=report.id,
        actor_id=parent.id,
        details={
            "student_id": str(report.student_id),
            "week_start": report.week_start.isoformat(),
        },
    )
    await db.commit()

    return ParentPublishedReportDetail(
        report_id=str(report.id),
        student_id=str(report.student_id),
        student_display_name=student.name,
        class_name=f"{klass.grade}-{klass.section}",
        week_start=report.week_start,
        week_end=report.week_end,
        title=str(content.get("title") or "Weekly Report"),
        sections=list(content.get("sections") or []),
        published_at=report.published_at,
    )
