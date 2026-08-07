from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers import timetable_policies, timetable_setup_centre
from services.gateway.timetable_setup import policy_diagnostics
from services.gateway.timetable_setup import policy_readiness
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
        "policy_readiness": {"generation_allowed": False, "readiness_status": "blocked", "policy_blocker_count": 1, "policy_warning_count": 0, "policy_pending_approval_count": 0, "overall_policy_score": 0},
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
        assert response.json()["policy_readiness"]["readiness_status"] == "blocked"
        assert response.json()["generation"]["policy_generation_allowed"] is False
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()


def test_setup_centre_revalidate_recomputes_without_mutation() -> None:
    db = AsyncMock()
    tenant = _tenant()
    actor = _actor(tenant.id)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "progress": {"completed_steps": 4, "total_steps": 4, "completed_weight": 100, "total_weight": 100, "progress_percentage": 100},
        "generation": {"generation_allowed": True, "readiness_status": "ready", "blocker_count": 0, "warning_count": 0, "information_count": 0, "pending_approval_count": 0, "policy_blocker_count": 0, "policy_warning_count": 0, "policy_information_count": 0, "policy_pending_approval_count": 0, "policy_readiness_status": "ready", "policy_generation_allowed": True, "required_actions": []},
    }

    original_summary = timetable_setup_centre.build_setup_centre_payload
    original_log_action = timetable_setup_centre.log_action
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.log_action = AsyncMock()
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.post("/leadership/timetable-setup/centre/revalidate")
        assert response.status_code == 200
        assert response.json()["revalidated"] is True
        assert response.json()["generation"]["generation_allowed"] is True
        assert timetable_setup_centre.log_action.await_count == 1
    finally:
        timetable_setup_centre.build_setup_centre_payload = original_summary
        timetable_setup_centre.log_action = original_log_action
        app.dependency_overrides.clear()


def test_setup_centre_backwards_compatibility_and_policy_issue_visibility() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(tenant.id)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "progress": {"completed_steps": 1, "total_steps": 1, "completed_weight": 100, "total_weight": 100, "progress_percentage": 100},
        "generation": {"generation_allowed": False, "readiness_status": "blocked", "blocker_count": 1, "warning_count": 0, "information_count": 0, "pending_approval_count": 1, "policy_blocker_count": 1, "policy_warning_count": 0, "policy_information_count": 0, "policy_pending_approval_count": 1, "policy_readiness_status": "blocked", "policy_generation_allowed": False, "required_actions": []},
        "issues": [{"issue_key": "readiness:policy", "severity": "blocker", "status": "blocking", "step_key": "approvals_and_readiness", "recommended_action": "Resolve policy blockers.", "setup_route": "/leadership/timetable-policies/readiness"}],
        "approval_queue": {"items": [{"type": "policy_set_pending_review", "urgency": "high", "setup_step": "approvals_and_readiness"}], "pending_total": 1, "direct_route": "/leadership/timetable-setup/centre/approvals"},
        "policy_diagnostics": {"generated_at": datetime.now(timezone.utc), "summary": {"blocker_count": 1}, "generation": {"generation_allowed": False}, "conflicts": [], "feasibility": [], "impact": [], "resolution_guidance": [], "policy_counts": {"policy_sets": 1}},
        "policy_readiness": {"generation_allowed": False, "readiness_status": "blocked", "policy_blocker_count": 1, "policy_warning_count": 0, "policy_pending_approval_count": 1, "overall_policy_score": 0},
        "recommendations": [{"recommendation_key": "recommend:readiness:policy", "priority_score": 100, "title": "Resolve policy blockers", "why": "Policy blockers remain", "recommended_action": "Resolve policy blockers.", "setup_route": "/leadership/timetable-policies/readiness", "authorized_roles": ["principal", "school_admin"], "requires_human_authorization": True, "agent_can_execute": False}],
        "policy": {"authorized_roles": ["principal", "school_admin"], "agent_allowed_actions": ["inspect_setup_state"], "agent_prohibited_actions": ["commit_imports"], "human_approval_required_for": ["import_commit"]},
    }

    original = timetable_setup_centre.build_setup_centre_payload
    timetable_setup_centre.build_setup_centre_payload = AsyncMock(return_value=payload)
    timetable_setup_centre.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-setup/centre/summary")
            issues = client.get("/leadership/timetable-setup/centre/issues")
            approvals = client.get("/leadership/timetable-setup/centre/approvals")
            recommendations = client.get("/leadership/timetable-setup/centre/recommendations")
        assert response.status_code == 200
        assert response.json()["generation"]["policy_generation_allowed"] is False
        assert response.json()["policy_diagnostics"]["summary"]["blocker_count"] == 1
        assert response.json()["policy_readiness"]["readiness_status"] == "blocked"
        assert issues.json()["items"][0]["issue_key"] == "readiness:policy"
        assert approvals.json()["items"][0]["type"] == "policy_set_pending_review"
        assert recommendations.json()["recommendations"][0]["setup_route"] == "/leadership/timetable-policies/readiness"
    finally:
        timetable_setup_centre.build_setup_centre_payload = original
        app.dependency_overrides.clear()


def test_policy_readiness_routes_return_read_only_payloads() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(tenant.id)
    payload = {
        "generated_at": datetime.now(timezone.utc),
        "calculation_id": str(uuid.uuid4()),
        "readiness_status": "ready",
        "generation_allowed": True,
        "policy_set_id": str(uuid.uuid4()),
        "policy_set_status": "active",
        "policy_set_version": 3,
        "policy_explanation": {"selected_policy_set": {"id": "p1"}},
        "source_and_provenance_summary": {"policy_set_count": 1},
        "policy_blocker_count": 0,
        "policy_warning_count": 0,
        "policy_pending_approval_count": 0,
        "policy_readiness_status": "ready",
        "overall_policy_score": 100,
        "policy_score": {"overall_score": 100, "dimensions": [], "applicable_weight": 0, "completed_weight": 0, "excluded_not_applicable_weight": 0, "calculation_explanation": ""},
        "calculation_breakdown": {"coverage": {"coverage_percentage": 100}, "effective_constraints": {"effective_constraint_count": 1}},
        "effective_constraint_count": 1,
        "coverage": {"coverage_percentage": 100},
        "effective_constraints": [{"constraint_id": "c1"}],
        "exception_readiness": {"ready": True},
        "required_actions": [],
        "readiness_blockers": [],
        "readiness_warnings": [],
    }

    original = timetable_policies.build_policy_readiness_payload
    timetable_policies.build_policy_readiness_payload = AsyncMock(return_value=payload)
    original_set_tenant_context = timetable_policies.set_tenant_context
    timetable_policies.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            readiness_response = client.get("/leadership/timetable-policies/readiness")
            policy_response = client.get("/leadership/timetable-policies/readiness/effective-policy")
            constraints_response = client.get("/leadership/timetable-policies/readiness/effective-constraints")
            authorization_response = client.get("/leadership/timetable-policies/readiness/authorization")
        assert readiness_response.status_code == 200
        assert policy_response.status_code == 200
        assert constraints_response.status_code == 200
        assert authorization_response.status_code == 200
        assert readiness_response.json()["generation_allowed"] is True
        assert policy_response.json()["policy_set_status"] == "active"
        assert constraints_response.json()["effective_constraint_count"] == 1
        assert authorization_response.json()["readiness_status"] == "ready"
    finally:
        timetable_policies.build_policy_readiness_payload = original
        timetable_policies.set_tenant_context = original_set_tenant_context
        app.dependency_overrides.clear()