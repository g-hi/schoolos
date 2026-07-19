from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.gateway.weekly_reports.generation import generate_optional_ai_draft
from services.gateway.weekly_reports.schemas import StatusTransitionRequest
from services.gateway.weekly_reports.service import WeeklyReportService


def _mk_user(*, role: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=role,
        name="Test User",
    )


def _mk_tenant(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=tenant_id,
        slug="greenwood",
        settings={},
    )


def test_generate_optional_ai_draft_returns_deterministic_when_ai_disabled():
    deterministic = {"title": "Deterministic", "sections": []}

    output, error = asyncio.run(
        generate_optional_ai_draft(
            provider=None,
            deterministic_draft=deterministic,
            evidence_snapshot={"evidence_items": []},
            use_ai=False,
        )
    )

    assert output == deterministic
    assert error is None


def test_generate_optional_ai_draft_provider_failure_falls_back():
    class FailingProvider:
        async def generate(self, prompt: str):
            raise RuntimeError("provider down")

    deterministic = {"title": "Deterministic", "sections": []}

    output, error = asyncio.run(
        generate_optional_ai_draft(
            provider=FailingProvider(),
            deterministic_draft=deterministic,
            evidence_snapshot={"evidence_items": []},
            use_ai=True,
        )
    )

    assert output == deterministic
    assert error == "provider_unavailable"


def test_submit_for_review_returns_409_on_stale_row_version():
    actor = _mk_user(role="teacher")
    tenant = _mk_tenant(actor.tenant_id)
    db = AsyncMock()
    db.add = MagicMock()

    report = SimpleNamespace(
        id=uuid.uuid4(),
        row_version=3,
        status="draft",
    )

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    service.get_report = AsyncMock(return_value=report)

    body = StatusTransitionRequest(expected_row_version=2, comment=None)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(service.submit_for_review(report_id=report.id, body=body))

    assert getattr(exc_info.value, "status_code", None) == 409


def test_teacher_cannot_publish_report():
    actor = _mk_user(role="teacher")
    tenant = _mk_tenant(actor.tenant_id)
    db = AsyncMock()
    db.add = MagicMock()

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    body = StatusTransitionRequest(expected_row_version=1, comment=None)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(service.publish(report_id=uuid.uuid4(), body=body))

    assert getattr(exc_info.value, "status_code", None) == 403


def test_leadership_cannot_approve_own_authored_report():
    actor = _mk_user(role="principal")
    tenant = _mk_tenant(actor.tenant_id)
    db = AsyncMock()
    db.add = MagicMock()

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        row_version=5,
        status="pending_review",
        created_by_user_id=actor.id,
        current_version_number=2,
        approved_version_number=None,
        approved_by_user_id=None,
        approved_at=None,
    )

    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = report
    db.execute = AsyncMock(return_value=locked_result)

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    body = StatusTransitionRequest(expected_row_version=5, comment="Looks good")

    with patch("services.gateway.weekly_reports.service.authorize_staff_for_student_action", new=AsyncMock(return_value=SimpleNamespace(student=SimpleNamespace(name="Student"), klass=SimpleNamespace(grade="G1", section="A")))), pytest.raises(Exception) as exc_info:
        asyncio.run(service.approve(report_id=report.id, body=body))

    assert getattr(exc_info.value, "status_code", None) == 403


def test_publish_uses_stable_timeline_idempotency_key_for_same_version():
    actor = _mk_user(role="principal")
    tenant = _mk_tenant(actor.tenant_id)
    db = AsyncMock()
    db.add = MagicMock()

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        row_version=7,
        status="published",
        approved_version_number=3,
        published_version_number=3,
        published_by_user_id=actor.id,
        published_at=datetime.now(timezone.utc),
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 19),
    )

    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = report

    version_result = MagicMock()
    version_id = uuid.uuid4()
    version_result.scalar_one_or_none.return_value = version_id

    family_rows_result = MagicMock()
    family_rows_result.all.return_value = [(uuid.uuid4(),), (uuid.uuid4(),)]

    db.execute = AsyncMock(side_effect=[locked_result, version_result, family_rows_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    body = StatusTransitionRequest(expected_row_version=7, comment="Republish")

    timeline_calls = []

    async def _fake_timeline(**kwargs):
        timeline_calls.append(kwargs)
        return None

    with patch(
        "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
        new=AsyncMock(return_value=SimpleNamespace(student=SimpleNamespace(name="Amina"), klass=SimpleNamespace(grade="G5", section="B"))),
    ), patch("services.gateway.weekly_reports.service.write_timeline_event", new=_fake_timeline):
        asyncio.run(service.publish(report_id=report.id, body=body))

    assert len(timeline_calls) == 2
    for call in timeline_calls:
        assert call["event_key"] == f"weekly-report-published:{report.id}:{version_id}"
