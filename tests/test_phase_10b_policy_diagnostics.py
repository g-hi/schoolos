from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers import timetable_policies, timetable_setup_centre
from services.gateway.timetable_setup import policy_diagnostics
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True, name="Leader", email="leader@example.test")


def _client(db: SimpleNamespace, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_diagnostics_analysis_reports_conflicts_and_feasibility_blocks() -> None:
    policy_set_id = str(uuid.uuid4())
    shared_academic_year_id = str(uuid.uuid4())
    shared_term_id = str(uuid.uuid4())
    shared_scope_reference_id = str(uuid.uuid4())
    constraint_id = str(uuid.uuid4())
    requirement_id = str(uuid.uuid4())
    diagnostics = policy_diagnostics.analyze_policy_state(
        readiness={"blocker_count": 0, "warning_count": 0, "information_count": 0},
        policy_sets=[
            {
                "id": policy_set_id,
                "academic_year_id": shared_academic_year_id,
                "term_id": shared_term_id,
                "campus_id": None,
                "name": "Policy",
                "lifecycle_status": "active",
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
            },
            {
                "id": str(uuid.uuid4()),
                "academic_year_id": shared_academic_year_id,
                "term_id": shared_term_id,
                "campus_id": None,
                "name": "Draft Policy",
                "lifecycle_status": "active",
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
            },
        ],
        constraints=[
            {
                "id": constraint_id,
                "policy_set_id": policy_set_id,
                "policy_set_name": "Policy",
                "academic_year_id": str(uuid.uuid4()),
                "term_id": str(uuid.uuid4()),
                "campus_id": None,
                "constraint_type": "subject_required_weekly_sessions",
                "category": "curriculum",
                "enforcement_level": "hard",
                "lifecycle_status": "active",
                "scope_type": "subject",
                "scope_reference_id": shared_scope_reference_id,
                "scope_reference_code": None,
                "parameters": {"required_sessions": 8},
                "weight": 1.0,
                "priority": 5,
                "is_active": True,
                "explanation": "Needs eight sessions",
                "requires_approval": False,
            },
            {
                "id": str(uuid.uuid4()),
                "policy_set_id": policy_set_id,
                "policy_set_name": "Policy",
                "academic_year_id": str(uuid.uuid4()),
                "term_id": str(uuid.uuid4()),
                "campus_id": None,
                "constraint_type": "subject_required_weekly_sessions",
                "category": "curriculum",
                "enforcement_level": "hard",
                "lifecycle_status": "active",
                "scope_type": "subject",
                "scope_reference_id": shared_scope_reference_id,
                "scope_reference_code": None,
                "parameters": {"required_sessions": 8},
                "weight": 1.0,
                "priority": 5,
                "is_active": True,
                "explanation": "Needs eight sessions",
                "requires_approval": False,
            },
        ],
        exceptions=[],
        requirements=[
            {
                "id": requirement_id,
                "campus_id": None,
                "academic_year_id": str(uuid.uuid4()),
                "term_id": str(uuid.uuid4()),
                "class_id": str(uuid.uuid4()),
                "subject_id": str(uuid.uuid4()),
                "teacher_id": None,
                "sessions_per_week": 3,
                "periods_per_session": 1,
                "min_daily_sessions": 0,
                "max_daily_sessions": 10,
                "specialist_room_type": None,
                "preferred_period_numbers": [1, 2],
                "forbidden_period_numbers": [1, 2],
                "has_fixed_sessions": True,
                "fixed_session_rules": [],
                "review_status": "approved",
                "is_active": True,
            }
        ],
        rooms=[],
        school_weeks=[],
        bell_periods=[],
    )

    assert diagnostics["generation"]["generation_allowed"] is False
    assert diagnostics["summary"]["conflict_count"] >= 1
    assert diagnostics["summary"]["feasibility_count"] >= 1
    assert diagnostics["summary"]["pending_approval_count"] == 0


def test_policy_diagnostics_routes_return_read_only_payloads() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(tenant.id)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "summary": {"conflict_count": 1, "feasibility_count": 1, "impact_count": 1, "blocker_count": 1, "warning_count": 0, "information_count": 0, "pending_approval_count": 0},
        "generation": {"generation_allowed": False, "policy_generation_allowed": False, "readiness_status": "blocked", "blocker_count": 1, "warning_count": 0, "information_count": 0, "pending_approval_count": 0},
        "conflicts": [{"diagnostic_key": "a"}],
        "feasibility": [{"diagnostic_key": "b"}],
        "impact": [{"diagnostic_key": "c"}],
        "resolution_guidance": [{"guidance_key": "d"}],
        "policy_counts": {"policy_sets": 1},
    }

    original = timetable_policies.build_policy_diagnostics_payload
    timetable_policies.build_policy_diagnostics_payload = AsyncMock(return_value=payload)
    timetable_policies.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-policies/diagnostics")
            conflicts = client.get("/leadership/timetable-policies/diagnostics/conflicts")
            feasibility = client.get("/leadership/timetable-policies/diagnostics/feasibility")
            impact = client.get("/leadership/timetable-policies/diagnostics/impact")
            guidance = client.get("/leadership/timetable-policies/diagnostics/resolution-guidance")
        assert response.status_code == 200
        assert conflicts.status_code == 200
        assert feasibility.status_code == 200
        assert impact.status_code == 200
        assert guidance.status_code == 200
        assert response.json()["generation"]["generation_allowed"] is False
        assert conflicts.json()["conflicts"][0]["diagnostic_key"] == "a"
        assert feasibility.json()["feasibility"][0]["diagnostic_key"] == "b"
        assert impact.json()["impact"][0]["diagnostic_key"] == "c"
        assert guidance.json()["resolution_guidance"][0]["guidance_key"] == "d"
    finally:
        timetable_policies.build_policy_diagnostics_payload = original
        app.dependency_overrides.clear()


def test_setup_centre_exposes_additive_policy_diagnostics() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(tenant.id)

    payload = {
        "generated_at": datetime.now(timezone.utc),
        "progress": {"completed_steps": 1, "total_steps": 1, "completed_weight": 100, "total_weight": 100, "progress_percentage": 100},
        "generation": {"generation_allowed": False, "readiness_status": "blocked", "blocker_count": 0, "warning_count": 0, "information_count": 0, "pending_approval_count": 0, "policy_blocker_count": 1, "policy_warning_count": 0, "policy_information_count": 0, "policy_pending_approval_count": 0, "policy_readiness_status": "blocked", "policy_generation_allowed": False, "required_actions": []},
        "policy_diagnostics": {"generated_at": datetime.now(timezone.utc), "summary": {"blocker_count": 1}, "generation": {"generation_allowed": False}},
        "policy": {"authorized_roles": ["principal", "school_admin"], "agent_allowed_actions": ["inspect_setup_state"], "agent_prohibited_actions": ["commit_imports"], "human_approval_required_for": ["import_commit"]},
    }

    original = timetable_setup_centre.build_setup_centre_payload
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-setup/centre/summary")
        assert response.status_code == 200
        assert response.json()["policy_diagnostics"]["summary"]["blocker_count"] == 1
        assert response.json()["generation"]["policy_generation_allowed"] is False
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()