from __future__ import annotations

from services.gateway.timetable_setup import policy_registry as registry


def test_registry_contains_required_initial_constraint_types() -> None:
    expected = {
        "teacher_unavailable",
        "teacher_preferred_period",
        "teacher_max_daily_sessions",
        "teacher_max_consecutive_sessions",
        "teacher_min_break",
        "teacher_subject_eligibility",
        "class_unavailable",
        "class_max_daily_sessions",
        "subject_required_weekly_sessions",
        "subject_required_weekly_minutes",
        "subject_max_daily_sessions",
        "subject_spread_across_days",
        "subject_preferred_period",
        "room_required_type",
        "room_capacity",
        "room_unavailable",
        "fixed_session",
        "avoid_period",
        "preferred_period",
        "lunch_protection",
        "campus_travel_buffer",
        "balanced_teacher_load",
        "minimize_teacher_gaps",
        "minimize_room_changes",
    }
    assert expected.issubset(set(registry.CONSTRAINT_TYPE_REGISTRY.keys()))


def test_registry_entries_declare_parameter_and_compatibility_metadata() -> None:
    entry = registry.CONSTRAINT_TYPE_REGISTRY["teacher_unavailable"]
    assert entry["required_parameters"] == {"weekdays": "list[int]", "period_numbers": "list[int]"}
    assert "hard" in entry["allowed_enforcement_levels"]
    assert "teacher" in entry["supported_scopes"]


def test_unknown_constraint_type_lookup_returns_none() -> None:
    assert registry.get_constraint_type_or_none("not_real") is None


def test_parameter_validation_rejects_wrong_types() -> None:
    entry = registry.CONSTRAINT_TYPE_REGISTRY["teacher_max_daily_sessions"]
    errors = registry.validate_constraint_parameters(entry, {"max_sessions": "three"})
    assert errors
