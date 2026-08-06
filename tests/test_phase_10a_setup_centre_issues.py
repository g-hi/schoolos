from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers import timetable_setup_centre
from services.gateway.timetable_setup import centre
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="school_admin", is_active=True, name="Leader", email="leader@example.test")


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_issues_filtering_is_deterministic() -> None:
    db = AsyncMock()
    tenant = _tenant()
    actor = _actor(tenant.id)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "issues": [
            {"issue_key": "readiness:a", "severity": "blocker", "status": "blocking", "step_key": "approvals_and_readiness"},
            {"issue_key": "imports:b", "severity": "warning", "status": "warning", "step_key": "intake_imports"},
            {"issue_key": "approvals:c", "severity": "warning", "status": "pending_review", "step_key": "approvals_and_readiness"},
        ],
    }

    original = timetable_setup_centre.build_setup_centre_payload
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            blocker = client.get("/leadership/timetable-setup/centre/issues", params={"severity": "blocker"})
            pending = client.get("/leadership/timetable-setup/centre/issues", params={"status": "pending_review"})
            imports = client.get("/leadership/timetable-setup/centre/issues", params={"step_key": "intake_imports"})
        assert blocker.status_code == 200
        assert blocker.json()["total"] == 1
        assert pending.json()["items"][0]["issue_key"] == "approvals:c"
        assert imports.json()["items"][0]["issue_key"] == "imports:b"
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()


def test_approvals_and_activity_endpoints() -> None:
    db = AsyncMock()
    tenant = _tenant()
    actor = _actor(tenant.id)
    summary_payload = {
        "generated_at": datetime.now(timezone.utc),
        "metrics": {
            "calendar_pending": 1,
            "pending_candidates": 2,
            "pending_plans": 1,
        },
    }
    activity_payload = {
        "items": [{"id": str(uuid.uuid4()), "action": "timetable_setup.calendar.created"}],
        "total": 1,
        "page": 1,
        "page_size": 25,
    }

    original_summary = timetable_setup_centre.build_setup_centre_payload
    original_activity = timetable_setup_centre.get_recent_activity
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=summary_payload)
    timetable_setup_centre.get_recent_activity = AsyncMock(return_value=activity_payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            approvals = client.get("/leadership/timetable-setup/centre/approvals")
            activity = client.get("/leadership/timetable-setup/centre/activity")
        assert approvals.status_code == 200
        assert approvals.json()["pending_total"] == 4
        assert activity.status_code == 200
        assert activity.json()["total"] == 1
    finally:
        timetable_setup_centre.build_setup_centre_payload = original_summary
        timetable_setup_centre.get_recent_activity = original_activity
        app.dependency_overrides.clear()


def test_policy_guidance_and_generation_logic_are_human_safe() -> None:
    readiness = {
        "blocker_count": 0,
        "warning_count": 1,
        "information_count": 0,
        "checks": [
            {
                "check_key": "calendar_pending_review",
                "status": "attention",
                "severity": "warning",
                "title": "Pending review",
                "explanation": "Pending entries need leadership decision.",
                "affected_record_count": 2,
                "recommended_action": "Approve or reject pending entries.",
                "setup_route": "/leadership/timetable-setup/calendar",
            }
        ],
    }
    metrics = {
        "pending_approvals_total": 2,
        "imports_failed": 1,
    }
    issues = centre.build_issues(readiness, metrics)
    generation = centre.build_generation_readiness(readiness, metrics, issues)
    recommendations = centre.build_recommendations(issues, [])

    assert generation["generation_allowed"] is False
    assert generation["readiness_status"] == "awaiting_human_approval"
    assert any(item["status"] == "pending_review" for item in issues)
    assert any(item["requires_human_authorization"] for item in recommendations)
