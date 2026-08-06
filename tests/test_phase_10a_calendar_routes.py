from __future__ import annotations

from services.gateway.main import app


REQUIRED_MANUAL_EVENT_ROUTES = {
    "/leadership/timetable-setup/calendar/events": {"post", "get"},
    "/leadership/timetable-setup/calendar/events/{event_id}": {"get", "patch"},
    "/leadership/timetable-setup/calendar/events/{event_id}/submit": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/approve": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/publish": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/reschedule": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/cancel": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/restore": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/archive": {"post"},
    "/leadership/timetable-setup/calendar/events/{event_id}/versions": {"get"},
    "/leadership/timetable-setup/calendar/events/{event_id}/impact": {"get"},
}

REQUIRED_PDF_ROUTES = {
    "/leadership/timetable-setup/calendar/pdf-intake/upload": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports": {"get"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}": {"get"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/pages": {"get"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/extract": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/candidates": {"get"},
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}": {"patch"},
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/approve": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/candidates/{candidate_id}/reject": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/validate": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/commit": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/cancel": {"post"},
    "/leadership/timetable-setup/calendar/pdf-intake/imports/{document_id}/diagnostics": {"get"},
}


REQUIRED_NOTIFICATION_ROUTES = {
    "/leadership/timetable-setup/calendar/notification-plans": {"get"},
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}": {"get"},
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}/approve": {"post"},
    "/leadership/timetable-setup/calendar/notification-plans/{plan_id}/cancel": {"post"},
}


def test_phase_10a_calendar_routes_present_with_expected_methods() -> None:
    paths = app.openapi()["paths"]

    for path, methods in REQUIRED_MANUAL_EVENT_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))

    for path, methods in REQUIRED_PDF_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))

    for path, methods in REQUIRED_NOTIFICATION_ROUTES.items():
        assert path in paths
        assert methods.issubset(set(paths[path].keys()))


def test_no_delete_routes_under_calendar_scope() -> None:
    paths = app.openapi()["paths"]
    for path, methods in paths.items():
        if path.startswith("/leadership/timetable-setup/calendar"):
            assert "delete" not in methods
