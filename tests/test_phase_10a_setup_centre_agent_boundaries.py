from __future__ import annotations

from services.gateway.timetable_setup import centre


def test_agent_policy_boundaries_include_critical_prohibitions() -> None:
    prohibited = set(centre.AGENT_PROHIBITED_ACTIONS)
    assert "commit_imports" in prohibited
    assert "publish_events" in prohibited
    assert "override_blockers" in prohibited


def test_generation_blocked_when_pending_approvals_exist() -> None:
    readiness = {
        "blocker_count": 0,
        "warning_count": 0,
        "information_count": 0,
        "checks": [],
    }
    metrics = {"pending_approvals_total": 1}
    generation = centre.build_generation_readiness(readiness, metrics, [])
    assert generation["generation_allowed"] is False
    assert generation["readiness_status"] == "awaiting_human_approval"
