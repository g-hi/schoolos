from __future__ import annotations

from services.gateway.main import app


REQUIRED_PROBLEM_ROUTES = {
    "/leadership/timetable-generation/configurations/{configuration_id}/problem/validate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/problem/summary": {"get"},
    "/leadership/timetable-generation/configurations/{configuration_id}/problem/preview": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/candidates/preview": {"post"},
}


def test_phase_10c_problem_routes_are_present() -> None:
    paths = app.openapi()["paths"]
    for path, methods in REQUIRED_PROBLEM_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))


def test_phase_10c_problem_routes_do_not_expose_generate() -> None:
    paths = app.openapi()["paths"]
    assert "/leadership/timetable-generation/generate" not in paths
