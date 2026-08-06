from __future__ import annotations

from services.gateway.main import app


REQUIRED_POLICY_ROUTES = {
    "/leadership/timetable-policies/policy-sets": {"get", "post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}": {"get", "patch"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/submit": {"post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/approve": {"post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/activate": {"post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/suspend": {"post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/retire": {"post"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/versions": {"get"},
    "/leadership/timetable-policies/policy-sets/{policy_set_id}/constraints": {"get", "post"},
    "/leadership/timetable-policies/constraints/{constraint_id}": {"get", "patch"},
    "/leadership/timetable-policies/constraints/{constraint_id}/submit": {"post"},
    "/leadership/timetable-policies/constraints/{constraint_id}/approve": {"post"},
    "/leadership/timetable-policies/constraints/{constraint_id}/activate": {"post"},
    "/leadership/timetable-policies/constraints/{constraint_id}/suspend": {"post"},
    "/leadership/timetable-policies/constraints/{constraint_id}/retire": {"post"},
    "/leadership/timetable-policies/constraints/{constraint_id}/versions": {"get"},
    "/leadership/timetable-policies/exceptions": {"get", "post"},
    "/leadership/timetable-policies/exceptions/{exception_id}": {"get"},
    "/leadership/timetable-policies/exceptions/{exception_id}/submit": {"post"},
    "/leadership/timetable-policies/exceptions/{exception_id}/approve": {"post"},
    "/leadership/timetable-policies/exceptions/{exception_id}/reject": {"post"},
    "/leadership/timetable-policies/exceptions/{exception_id}/revoke": {"post"},
    "/leadership/timetable-policies/diagnostics": {"get"},
    "/leadership/timetable-policies/diagnostics/conflicts": {"get"},
    "/leadership/timetable-policies/diagnostics/feasibility": {"get"},
    "/leadership/timetable-policies/diagnostics/impact": {"get"},
    "/leadership/timetable-policies/diagnostics/resolution-guidance": {"get"},
    "/leadership/timetable-policies/readiness": {"get"},
    "/leadership/timetable-policies/readiness/effective-policy": {"get"},
    "/leadership/timetable-policies/readiness/effective-constraints": {"get"},
    "/leadership/timetable-policies/readiness/authorization": {"get"},
    "/leadership/timetable-policies/constraint-types": {"get"},
    "/leadership/timetable-policies/constraint-types/{constraint_type}": {"get"},
}


def test_phase_10b_policy_routes_present_with_expected_methods() -> None:
    paths = app.openapi()["paths"]

    for path, methods in REQUIRED_POLICY_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))


def test_no_delete_routes_under_policy_scope() -> None:
    paths = app.openapi()["paths"]
    for path, methods in paths.items():
        if path.startswith("/leadership/timetable-policies"):
            assert "delete" not in methods
