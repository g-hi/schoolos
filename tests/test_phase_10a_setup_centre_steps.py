from __future__ import annotations

from services.gateway.timetable_setup import centre


def test_build_steps_returns_fixed_catalogue_of_eleven() -> None:
    metrics = {
        "calendar_approved": 1,
        "calendar_pending": 0,
        "school_week_approved": 1,
        "school_week_pending": 0,
        "bell_schedule_approved": 1,
        "bell_schedule_pending": 0,
        "teaching_periods_active": 6,
        "rooms_approved": 2,
        "rooms_pending": 0,
        "classes_active": 3,
        "subjects_total": 4,
        "teachers_active": 5,
        "requirements_approved": 8,
        "requirements_pending": 0,
        "imports_total": 1,
        "imports_pending_review": 0,
        "pending_approvals_total": 0,
    }
    readiness = {"blocker_count": 0}

    steps = centre.build_steps(metrics, readiness)
    assert len(steps) == 11
    assert steps[0]["step_key"] == "operational_calendar"
    assert steps[-1]["step_key"] == "approvals_and_readiness"
    assert all(item["status"] in {"completed", "in_review", "in_progress", "blocked", "not_started"} for item in steps)
