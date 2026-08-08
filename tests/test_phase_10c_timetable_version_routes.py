from __future__ import annotations

from services.gateway.main import app


REQUIRED_VERSION_ROUTES = {
    "/leadership/timetable-generation/timetables": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}/versions": {"get"},
    "/leadership/timetable-generation/timetable-versions/{version_id}": {"get"},
    "/leadership/timetable-generation/configurations/{configuration_id}/versions/from-candidate": {"post"},
    "/leadership/timetable-generation/configurations/{configuration_id}/repair/impact-preview": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/submit": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/approve": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/publish": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/cancel": {"post"},
    "/leadership/timetable-generation/timetable-versions/{version_id}/diff/{other_version_id}": {"get"},
    "/leadership/timetable-generation/timetables/{timetable_id}/effective-version": {"get"},
}


def test_phase_10c_batch5_routes_are_present() -> None:
    paths = app.openapi()["paths"]
    for path, methods in REQUIRED_VERSION_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))
