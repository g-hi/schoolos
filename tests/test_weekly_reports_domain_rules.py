from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from services.gateway.weekly_reports.evidence import build_evidence_snapshot, resolve_reporting_period
from services.gateway.weekly_reports.generation import generate_optional_ai_draft
from services.gateway.weekly_reports.schemas import (
    InitializeWeeklyReportRequest,
    StaffEvidenceInput,
    StatusTransitionRequest,
)
from services.gateway.weekly_reports.service import WeeklyReportService
from services.gateway.weekly_reports.validation import validate_content_structure


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", settings={"timezone": "UTC"})


def _actor(*, tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, name="Actor")


def _student_context(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    student = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, name="Ahmed Hassan")
    klass = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, grade="Grade 5", section="A", academic_year="2026-2027", class_teacher_id=None)
    return SimpleNamespace(student=student, klass=klass, teacher_profile=None)


def _report_for_publish(tenant_id: uuid.UUID, actor_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        student_id=uuid.uuid4(),
        row_version=5,
        status="approved",
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 19),
        approved_version_number=3,
        published_version_number=None,
        published_by_user_id=None,
        published_at=None,
        current_version_number=3,
        created_by_user_id=uuid.uuid4(),
        approved_by_user_id=actor_id,
        approved_at=datetime.now(timezone.utc),
    )


def _integrity_error(*, constraint_name: str, sqlstate: str) -> IntegrityError:
    diag = SimpleNamespace(constraint_name=constraint_name)

    class _OrigError:
        def __init__(self):
            self.diag = diag
            self.sqlstate = sqlstate

        def __str__(self) -> str:
            return f"constraint={constraint_name} sqlstate={sqlstate}"

    return IntegrityError("insert", {}, _OrigError())


def test_manual_report_generation_works_without_ai_provider():
    deterministic = {"title": "Safe Draft", "sections": []}

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


def test_malformed_ai_output_is_replaced_by_deterministic_draft():
    class BadProvider:
        async def generate(self, prompt: str):
            return {"content": "not-json"}

    deterministic = {"title": "Safe Draft", "sections": [{"section_type": "teacher_comment", "content": "Fallback"}]}

    output, error = asyncio.run(
        generate_optional_ai_draft(
            provider=BadProvider(),
            deterministic_draft=deterministic,
            evidence_snapshot={"evidence_items": []},
            use_ai=True,
        )
    )

    assert output == deterministic
    assert error == "invalid_provider_output"


def test_invalid_evidence_ids_are_rejected():
    evidence_snapshot = {
        "reporting_context": {"student_display_name": "Ahmed Hassan"},
        "evidence_items": [{"evidence_id": "student_profile_1"}],
    }
    content = {
        "title": "Weekly Report",
        "sections": [
            {
                "section_type": "teacher_comment",
                "content": "Progress update",
                "used_evidence_ids": ["unknown_evidence_99"],
            },
            {
                "section_type": "data_availability_note",
                "content": "Data modules unavailable this week.",
                "used_evidence_ids": ["student_profile_1"],
            },
        ],
    }

    errors = validate_content_structure(content, evidence_snapshot)
    codes = {e["code"] for e in errors}
    assert "unknown_evidence_id" in codes


def test_foreign_student_names_are_rejected():
    evidence_snapshot = {
        "reporting_context": {"student_display_name": "Ahmed Hassan"},
        "evidence_items": [{"evidence_id": "student_profile_1"}],
    }
    content = {
        "title": "Weekly Report",
        "sections": [
            {
                "section_type": "teacher_comment",
                "content": "Mary Jones completed every assignment this week.",
                "used_evidence_ids": ["student_profile_1"],
            },
            {
                "section_type": "data_availability_note",
                "content": "Unavailable data is a module-availability notice only.",
                "used_evidence_ids": ["student_profile_1"],
            },
        ],
    }

    errors = validate_content_structure(content, evidence_snapshot)
    codes = {e["code"] for e in errors}
    assert "foreign_student_name" in codes


def test_html_and_script_content_are_rejected():
    with pytest.raises(ValueError):
        StaffEvidenceInput(weekly_teacher_summary="<script>alert(1)</script>")

    evidence_snapshot = {
        "reporting_context": {"student_display_name": "Ahmed Hassan"},
        "evidence_items": [{"evidence_id": "student_profile_1"}],
    }
    content = {
        "title": "Weekly Report",
        "sections": [
            {
                "section_type": "teacher_comment",
                "content": "<b>Unsafe</b>",
                "used_evidence_ids": ["student_profile_1"],
            },
            {
                "section_type": "data_availability_note",
                "content": "No hidden content.",
                "used_evidence_ids": ["student_profile_1"],
            },
        ],
    }
    errors = validate_content_structure(content, evidence_snapshot)
    codes = {e["code"] for e in errors}
    assert "unsafe_html" in codes


def test_pickup_and_unrelated_timeline_data_are_excluded_from_evidence():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="teacher")
    student_ctx = _student_context(tenant_id=tenant.id)

    period = resolve_reporting_period(
        requested_week_start=date(2026, 7, 13),
        tenant=tenant,
        timezone_override=None,
    )
    snapshot = build_evidence_snapshot(
        student=student_ctx.student,
        klass=student_ctx.klass,
        period=period,
        actor=actor,
        staff_evidence=None,
    )

    source_types = {item["source_type"] for item in snapshot["evidence_items"]}
    assert "pickup" not in source_types
    assert "family_timeline" not in source_types


def test_publication_creates_one_family_timeline_event_and_repeated_publish_is_idempotent_keyed():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")

    report = _report_for_publish(tenant_id=tenant.id, actor_id=actor.id)
    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = report

    version_id = uuid.uuid4()
    version_result = MagicMock()
    version_result.scalar_one_or_none.return_value = version_id

    family_id = uuid.uuid4()
    family_rows_result = MagicMock()
    family_rows_result.all.return_value = [(family_id,)]

    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=[locked_result, version_result, family_rows_result, locked_result, version_result, family_rows_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    timeline_calls: list[dict] = []
    audit_calls: list[dict] = []

    async def _fake_timeline(**kwargs):
        timeline_calls.append(kwargs)
        return None

    async def _fake_log_action(**kwargs):
        audit_calls.append(kwargs)
        return None

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    body = StatusTransitionRequest(expected_row_version=5, comment="Publish")

    with patch(
        "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
        new=AsyncMock(return_value=SimpleNamespace(student=SimpleNamespace(name="Ahmed Hassan"), klass=SimpleNamespace(grade="Grade 5", section="A"))),
    ), patch("services.gateway.weekly_reports.service.write_timeline_event", new=_fake_timeline), patch(
        "services.gateway.weekly_reports.service.log_action", new=_fake_log_action
    ):
        asyncio.run(service.publish(report_id=report.id, body=body))

    report.status = "published"
    report.published_version_number = report.approved_version_number
    report.row_version = report.row_version

    with patch(
        "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
        new=AsyncMock(return_value=SimpleNamespace(student=SimpleNamespace(name="Ahmed Hassan"), klass=SimpleNamespace(grade="Grade 5", section="A"))),
    ), patch("services.gateway.weekly_reports.service.write_timeline_event", new=_fake_timeline), patch(
        "services.gateway.weekly_reports.service.log_action", new=_fake_log_action
    ):
        asyncio.run(service.publish(report_id=report.id, body=StatusTransitionRequest(expected_row_version=report.row_version, comment="Republish")))

    assert len(timeline_calls) == 2
    assert timeline_calls[0]["event_key"] == timeline_calls[1]["event_key"]

    assert len(audit_calls) >= 2
    for call in audit_calls:
        details = call.get("details", {})
        banned = {"content", "content_json", "evidence_snapshot", "prompt", "token_usage", "api_key", "secret"}
        assert not any(key in details for key in banned)


def test_lifecycle_actions_emit_audit_events():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="teacher")
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        row_version=1,
        status="draft",
        current_version_number=1,
    )

    audit_calls: list[str] = []

    async def _fake_log_action(**kwargs):
        audit_calls.append(kwargs["action"])
        return None

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)
    service.get_report = AsyncMock(return_value=report)

    with patch("services.gateway.weekly_reports.service.log_action", new=_fake_log_action), patch(
        "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
        new=AsyncMock(return_value=_student_context(tenant_id=tenant.id)),
    ):
        asyncio.run(service.submit_for_review(report_id=report.id, body=StatusTransitionRequest(expected_row_version=1, comment="Ready")))

    report.status = "pending_review"
    report.row_version = report.row_version

    with patch("services.gateway.weekly_reports.service.log_action", new=_fake_log_action), patch(
        "services.gateway.weekly_reports.service.authorize_staff_for_student_action",
        new=AsyncMock(return_value=_student_context(tenant_id=tenant.id)),
    ):
        leader = _actor(tenant_id=tenant.id, role="principal")
        service_leader = WeeklyReportService(db=db, tenant=tenant, actor=leader)
        service_leader.get_report = AsyncMock(return_value=report)
        asyncio.run(service_leader.request_changes(report_id=report.id, body=StatusTransitionRequest(expected_row_version=report.row_version, comment="Adjust wording")))

    assert "report.submitted_for_review" in audit_calls
    assert "report.changes_requested" in audit_calls


def test_initialization_is_idempotent_for_same_tenant_student_week():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="teacher")
    ctx = _student_context(tenant_id=tenant.id)

    existing_report = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, student_id=ctx.student.id, week_start=date(2026, 7, 13))

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_report

    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=existing_result)

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)

    with patch("services.gateway.weekly_reports.service.authorize_staff_for_student_action", new=AsyncMock(return_value=ctx)):
        result = asyncio.run(
            service.initialize_report(
                InitializeWeeklyReportRequest(
                    student_id=str(ctx.student.id),
                    week_start=date(2026, 7, 13),
                )
            )
        )

    assert result.report.id == existing_report.id
    assert result.created_version is None


def test_initialize_report_rolls_back_before_recovery_query_on_unique_violation():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="teacher")
    ctx = _student_context(tenant_id=tenant.id)

    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None

    existing_report = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, student_id=ctx.student.id, week_start=date(2026, 7, 13))
    retry_result = MagicMock()
    retry_result.scalar_one_or_none.return_value = existing_report

    trace: list[str] = []
    execute_calls = {"count": 0}

    async def _execute(*_args, **_kwargs):
        execute_calls["count"] += 1
        trace.append(f"execute_{execute_calls['count']}")
        return first_result if execute_calls["count"] == 1 else retry_result

    async def _flush():
        trace.append("flush")
        raise _integrity_error(constraint_name="uq_weekly_report_per_student_week", sqlstate="23505")

    async def _rollback():
        trace.append("rollback")

    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock(side_effect=_flush)
    db.rollback = AsyncMock(side_effect=_rollback)

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)

    with patch("services.gateway.weekly_reports.service.authorize_staff_for_student_action", new=AsyncMock(return_value=ctx)):
        result = asyncio.run(
            service.initialize_report(
                InitializeWeeklyReportRequest(
                    student_id=str(ctx.student.id),
                    week_start=date(2026, 7, 13),
                )
            )
        )

    assert result.report.id == existing_report.id
    assert result.created_version is None
    assert trace == ["execute_1", "flush", "rollback", "execute_2"]


def test_initialize_report_reraises_unexpected_integrity_error():
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="teacher")
    ctx = _student_context(tenant_id=tenant.id)

    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=first_result)
    db.flush = AsyncMock(side_effect=_integrity_error(constraint_name="fk_random_other_constraint", sqlstate="23503"))
    db.rollback = AsyncMock()

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)

    with patch("services.gateway.weekly_reports.service.authorize_staff_for_student_action", new=AsyncMock(return_value=ctx)), pytest.raises(IntegrityError):
        asyncio.run(
            service.initialize_report(
                InitializeWeeklyReportRequest(
                    student_id=str(ctx.student.id),
                    week_start=date(2026, 7, 13),
                )
            )
        )

    db.rollback.assert_awaited_once()
    assert db.execute.await_count == 1


def test_initialize_report_unique_recovery_does_not_reaccess_tenant_or_actor_ids():
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    class _TenantGuard:
        def __init__(self):
            self._id_calls = 0
            self.slug = "greenwood"
            self.settings = {"timezone": "UTC"}

        @property
        def id(self) -> uuid.UUID:
            self._id_calls += 1
            if self._id_calls > 1:
                raise AssertionError("tenant.id was accessed after being cached")
            return tenant_id

    class _ActorGuard:
        def __init__(self):
            self._id_calls = 0
            self.tenant_id = tenant_id
            self.role = "teacher"
            self.name = "Actor"

        @property
        def id(self) -> uuid.UUID:
            self._id_calls += 1
            if self._id_calls > 1:
                raise AssertionError("actor.id was accessed after being cached")
            return actor_id

    tenant = _TenantGuard()
    actor = _ActorGuard()
    ctx = _student_context(tenant_id=tenant_id)

    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None

    existing_report = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, student_id=ctx.student.id, week_start=date(2026, 7, 13))
    retry_result = MagicMock()
    retry_result.scalar_one_or_none.return_value = existing_report

    execute_calls = {"count": 0}

    async def _execute(*_args, **_kwargs):
        execute_calls["count"] += 1
        return first_result if execute_calls["count"] == 1 else retry_result

    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock(side_effect=_integrity_error(constraint_name="uq_weekly_report_per_student_week", sqlstate="23505"))
    db.rollback = AsyncMock()

    service = WeeklyReportService(db=db, tenant=tenant, actor=actor)

    with patch("services.gateway.weekly_reports.service.authorize_staff_for_student_action", new=AsyncMock(return_value=ctx)):
        result = asyncio.run(
            service.initialize_report(
                InitializeWeeklyReportRequest(
                    student_id=str(ctx.student.id),
                    week_start=date(2026, 7, 13),
                )
            )
        )

    assert result.report.id == existing_report.id
    assert result.created_version is None
