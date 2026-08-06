from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers import timetable_setup_centre
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True, name="Leader", email="leader@example.test")


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_summary_returns_generation_progress_and_policy() -> None:
    db = AsyncMock()
    tenant = _tenant()
    actor = _actor(tenant.id)

    payload = {
        "generated_at": datetime.now(timezone.utc),
        "progress": {"completed_steps": 8, "total_steps": 11, "completed_weight": 74, "total_weight": 100, "progress_percentage": 74},
        "generation": {
            "generation_allowed": False,
            "readiness_status": "awaiting_human_approval",
            "blocker_count": 0,
            "warning_count": 1,
            "information_count": 0,
            "pending_approval_count": 2,
            "required_actions": [],
        },
        "source_breakdown": {"manual": 2, "excel_import": 1, "pdf_extraction": 1, "agent_recommendation": 0, "system_generated": 0},
        "review_breakdown": {"approved": 2, "pending_review": 1, "rejected": 0},
        "metrics": {
            "calendar_approved": 2,
            "school_week_approved": 1,
            "bell_schedule_approved": 1,
            "teaching_periods_active": 7,
            "rooms_approved": 4,
            "classes_active": 10,
            "subjects_total": 8,
            "teachers_active": 12,
            "requirements_approved": 14,
            "imports_total": 3,
        },
        "policy": {
            "authorized_roles": ["principal", "school_admin"],
            "agent_allowed_actions": ["inspect_setup_state"],
            "agent_prohibited_actions": ["commit_imports"],
            "human_approval_required_for": ["import_commit"],
        },
    }

    original = timetable_setup_centre.build_setup_centre_payload
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-setup/centre/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["progress"]["progress_percentage"] == 74
        assert body["generation"]["generation_allowed"] is False
        assert body["generation"]["readiness_status"] == "awaiting_human_approval"
        assert "agent_prohibited_actions" in body["policy"]
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()


def test_recommendations_exposes_policy_and_generation_status() -> None:
    db = AsyncMock()
    tenant = _tenant()
    actor = _actor(tenant.id)

    payload = {
        "generated_at": datetime.now(timezone.utc),
        "generation": {
            "generation_allowed": True,
            "readiness_status": "ready_with_warnings",
            "blocker_count": 0,
            "warning_count": 1,
            "information_count": 0,
            "pending_approval_count": 0,
            "required_actions": [],
        },
        "recommendations": [
            {
                "recommendation_key": "recommend:imports:failed_batches",
                "priority_score": 70,
                "title": "Import batches failed validation or processing",
                "recommended_action": "Inspect diagnostics.",
                "requires_human_authorization": False,
            }
        ],
        "policy": {
            "authorized_roles": ["principal", "school_admin"],
            "agent_allowed_actions": ["inspect_setup_state"],
            "agent_prohibited_actions": ["publish_events"],
            "human_approval_required_for": ["event_publication"],
        },
    }

    original = timetable_setup_centre.build_setup_centre_payload
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-setup/centre/recommendations")
        assert response.status_code == 200
        body = response.json()
        assert body["generation"]["generation_allowed"] is True
        assert body["recommendations"][0]["priority_score"] == 70
        assert "publish_events" in body["policy"]["agent_prohibited_actions"]
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()
