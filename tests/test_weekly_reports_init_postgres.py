from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from services.gateway.weekly_reports.schemas import InitializeWeeklyReportRequest
from services.gateway.weekly_reports.service import WeeklyReportService
from shared.config import settings
from shared.db.models import Class, Student, Tenant, User
from shared.db.weekly_report_models import (
    WeeklyStudentReport,
    WeeklyStudentReportReviewEvent,
    WeeklyStudentReportVersion,
)


async def _can_connect(db_url: str) -> None:
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def _seed_minimum_entities(session: AsyncSession) -> tuple[Tenant, User, Class, Student]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Weekly Reports Test Tenant",
        slug=f"weekly-reports-test-{uuid.uuid4().hex[:8]}",
        settings={"timezone": "UTC"},
        is_active=True,
    )
    actor = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Teacher User",
        email=f"teacher-{uuid.uuid4().hex[:6]}@example.test",
        role="teacher",
        password_hash="test-hash",
        is_active=True,
        preferred_channel="email",
    )
    klass = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade="Grade 5",
        section="A",
        academic_year="2026-2027",
        class_teacher_id=None,
    )
    student = Student(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        class_id=klass.id,
        name="Ahmed Hassan",
        student_code=f"TEST-{uuid.uuid4().hex[:6]}",
    )

    session.add(tenant)
    await session.flush()

    session.add(actor)
    await session.flush()

    session.add(klass)
    await session.flush()

    session.add(student)
    await session.flush()
    return tenant, actor, klass, student


async def _run_initialize_report_fk_test() -> None:
    engine = create_async_engine(settings.async_database_url)

    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")

        try:
            tenant, actor, klass, student = await _seed_minimum_entities(session)

            body = InitializeWeeklyReportRequest(student_id=str(student.id), week_start=date(2026, 7, 13))
            student_ctx = SimpleNamespace(
                student=SimpleNamespace(id=student.id, tenant_id=tenant.id, name=student.name),
                klass=SimpleNamespace(
                    id=klass.id,
                    tenant_id=tenant.id,
                    grade=klass.grade,
                    section=klass.section,
                    academic_year=klass.academic_year,
                ),
                teacher_profile=None,
            )

            service = WeeklyReportService(db=session, tenant=tenant, actor=actor)

            with patch(
                "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
                new=AsyncMock(return_value=student_ctx),
            ), patch("services.gateway.weekly_reports.service.log_action", new=AsyncMock(return_value=None)):
                first = await service.initialize_report(body)
                second = await service.initialize_report(body)

            reports = (
                (
                    await session.execute(
                        select(WeeklyStudentReport).where(
                            WeeklyStudentReport.tenant_id == tenant.id,
                            WeeklyStudentReport.student_id == student.id,
                            WeeklyStudentReport.week_start == body.week_start,
                        )
                    )
                )
                .scalars()
                .all()
            )
            versions = (
                (
                    await session.execute(
                        select(WeeklyStudentReportVersion).where(WeeklyStudentReportVersion.report_id == first.report.id)
                    )
                )
                .scalars()
                .all()
            )
            events = (
                (
                    await session.execute(
                        select(WeeklyStudentReportReviewEvent).where(WeeklyStudentReportReviewEvent.report_id == first.report.id)
                    )
                )
                .scalars()
                .all()
            )

            assert first.created_version is not None
            assert first.report.status == "draft"
            assert first.report.row_version == 1
            assert len(reports) == 1
            assert len(versions) == 1
            assert len(events) == 1
            assert events[0].event_type == "report_initialized"
            assert events[0].report_version_id == versions[0].id

            assert second.created_version is None
            assert second.report.id == first.report.id
        finally:
            await session.close()
            await outer_tx.rollback()

    await engine.dispose()


def test_initialize_report_persists_version_before_review_event_in_postgres():
    try:
        asyncio.run(_can_connect(settings.async_database_url))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for integration test: {exc}")

    asyncio.run(_run_initialize_report_fk_test())
