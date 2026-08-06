from __future__ import annotations

from services.gateway.timetable_setup import centre


def test_recommendations_prioritize_blockers_before_warnings() -> None:
    issues = [
        {
            "issue_key": "warn",
            "severity": "warning",
            "status": "warning",
            "title": "Warning",
            "explanation": "warning",
            "recommended_action": "fix warning",
            "setup_route": "/warning",
            "authorized_roles": ["principal", "school_admin"],
            "requires_human_authorization": False,
        },
        {
            "issue_key": "block",
            "severity": "blocker",
            "status": "blocking",
            "title": "Blocker",
            "explanation": "blocker",
            "recommended_action": "fix blocker",
            "setup_route": "/blocker",
            "authorized_roles": ["principal", "school_admin"],
            "requires_human_authorization": False,
        },
    ]
    recommendations = centre.build_recommendations(issues, [])
    assert recommendations
    assert recommendations[0]["title"] == "Blocker"
    assert recommendations[0]["priority_score"] > recommendations[1]["priority_score"]
