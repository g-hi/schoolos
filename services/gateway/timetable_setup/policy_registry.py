from __future__ import annotations

from typing import Any, TypedDict


CONSTRAINT_CATEGORIES = {
    "resource",
    "teacher",
    "class",
    "subject",
    "room",
    "time",
    "workload",
    "distribution",
    "curriculum",
    "campus",
    "policy",
    "preference",
}

ENFORCEMENT_LEVELS = {"hard", "soft", "preference", "advisory"}

LIFECYCLE_STATUSES = {"draft", "pending_review", "approved", "active", "suspended", "retired"}

SCOPE_TYPES = {
    "whole_school",
    "campus",
    "department",
    "grade",
    "class",
    "subject",
    "teacher",
    "room",
    "period",
    "policy_set",
}

SOURCE_TYPES = {"manual", "imported", "agent_proposal", "system_default", "approved_exception"}


class ConstraintTypeDefinition(TypedDict):
    key: str
    title: str
    category: str
    allowed_enforcement_levels: list[str]
    required_parameters: dict[str, str]
    optional_parameters: dict[str, str]
    supported_scopes: list[str]
    validation_rules: list[str]
    default_priority: int
    default_weight: float
    explanation: str
    solver_mapping: str
    approval_required: bool


def _make(
    *,
    key: str,
    title: str,
    category: str,
    allowed_enforcement_levels: list[str],
    required_parameters: dict[str, str],
    optional_parameters: dict[str, str],
    supported_scopes: list[str],
    validation_rules: list[str],
    default_priority: int,
    default_weight: float,
    explanation: str,
    approval_required: bool,
) -> ConstraintTypeDefinition:
    return {
        "key": key,
        "title": title,
        "category": category,
        "allowed_enforcement_levels": allowed_enforcement_levels,
        "required_parameters": required_parameters,
        "optional_parameters": optional_parameters,
        "supported_scopes": supported_scopes,
        "validation_rules": validation_rules,
        "default_priority": default_priority,
        "default_weight": default_weight,
        "explanation": explanation,
        "solver_mapping": "reserved_for_phase_10c",
        "approval_required": approval_required,
    }


CONSTRAINT_TYPE_REGISTRY: dict[str, ConstraintTypeDefinition] = {
    "require_subject_match": _make(
        key="require_subject_match",
        title="Require Subject Match",
        category="teacher",
        allowed_enforcement_levels=["hard"],
        required_parameters={},
        optional_parameters={},
        supported_scopes=["whole_school", "subject"],
        validation_rules=[],
        default_priority=5,
        default_weight=1.0,
        explanation="Only subject-qualified teachers may cover teaching assignments.",
        approval_required=True,
    ),
    "maximum_daily_teaching_periods": _make(
        key="maximum_daily_teaching_periods",
        title="Maximum Daily Teaching Periods",
        category="workload",
        allowed_enforcement_levels=["hard"],
        required_parameters={"max_periods": "int"},
        optional_parameters={},
        supported_scopes=["whole_school", "teacher"],
        validation_rules=["max_periods_must_be_positive"],
        default_priority=20,
        default_weight=1.0,
        explanation="Caps teaching periods for an operational coverage assignment.",
        approval_required=True,
    ),
    "maximum_daily_operational_minutes": _make(
        key="maximum_daily_operational_minutes",
        title="Maximum Daily Operational Minutes",
        category="workload",
        allowed_enforcement_levels=["hard"],
        required_parameters={"max_minutes": "int"},
        optional_parameters={},
        supported_scopes=["whole_school", "teacher"],
        validation_rules=["max_minutes_must_be_positive"],
        default_priority=21,
        default_weight=1.0,
        explanation="Caps total teaching minutes for an operational coverage assignment.",
        approval_required=True,
    ),
    "protected_periods": _make(
        key="protected_periods",
        title="Protected Periods",
        category="time",
        allowed_enforcement_levels=["hard"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={},
        supported_scopes=["whole_school", "teacher"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=22,
        default_weight=1.0,
        explanation="Prevents operational assignment during protected periods.",
        approval_required=True,
    ),
    "prefer_subject_match": _make(
        key="prefer_subject_match",
        title="Prefer Subject Match",
        category="preference",
        allowed_enforcement_levels=["preference", "advisory"],
        required_parameters={},
        optional_parameters={},
        supported_scopes=["whole_school", "subject"],
        validation_rules=[],
        default_priority=50,
        default_weight=1.0,
        explanation="Prefers subject-qualified teachers among eligible candidates.",
        approval_required=True,
    ),
    "prefer_lower_baseline_workload": _make(
        key="prefer_lower_baseline_workload",
        title="Prefer Lower Baseline Workload",
        category="preference",
        allowed_enforcement_levels=["preference", "advisory"],
        required_parameters={},
        optional_parameters={},
        supported_scopes=["whole_school", "teacher"],
        validation_rules=[],
        default_priority=51,
        default_weight=1.0,
        explanation="Prefers lower baseline operational workload among eligible candidates.",
        approval_required=True,
    ),
    "prefer_lower_recent_substitution_burden": _make(
        key="prefer_lower_recent_substitution_burden",
        title="Prefer Lower Recent Substitution Burden",
        category="preference",
        allowed_enforcement_levels=["preference", "advisory"],
        required_parameters={},
        optional_parameters={},
        supported_scopes=["whole_school", "teacher"],
        validation_rules=[],
        default_priority=52,
        default_weight=1.0,
        explanation="Prefers lower recent substitution burden among eligible candidates.",
        approval_required=True,
    ),
    "ordered_substitution_fallback_tiers": _make(
        key="ordered_substitution_fallback_tiers",
        title="Ordered Substitution Fallback Tiers",
        category="policy",
        allowed_enforcement_levels=["hard", "advisory"],
        required_parameters={"tiers": "list[object]"},
        optional_parameters={},
        supported_scopes=["whole_school", "campus"],
        validation_rules=["fallback_tiers_must_be_valid"],
        default_priority=60,
        default_weight=1.0,
        explanation="Defines the leadership-approved substitution fallback order.",
        approval_required=True,
    ),
    "teacher_unavailable": _make(
        key="teacher_unavailable",
        title="Teacher Unavailable",
        category="teacher",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"weekdays": "list[int]", "period_numbers": "list[int]"},
        optional_parameters={"reason": "str"},
        supported_scopes=["teacher"],
        validation_rules=["period_numbers_must_be_positive", "weekdays_must_be_0_to_6"],
        default_priority=10,
        default_weight=1.0,
        explanation="Teacher cannot be scheduled in the blocked periods.",
        approval_required=False,
    ),
    "teacher_preferred_period": _make(
        key="teacher_preferred_period",
        title="Teacher Preferred Period",
        category="teacher",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={"weekdays": "list[int]"},
        supported_scopes=["teacher"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=90,
        default_weight=0.6,
        explanation="A teacher prefers specific periods when feasible.",
        approval_required=False,
    ),
    "teacher_max_daily_sessions": _make(
        key="teacher_max_daily_sessions",
        title="Teacher Max Daily Sessions",
        category="workload",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"max_sessions": "int"},
        optional_parameters={},
        supported_scopes=["teacher", "department", "whole_school"],
        validation_rules=["max_sessions_must_be_positive"],
        default_priority=20,
        default_weight=1.0,
        explanation="Caps daily teaching load for teachers.",
        approval_required=False,
    ),
    "teacher_max_consecutive_sessions": _make(
        key="teacher_max_consecutive_sessions",
        title="Teacher Max Consecutive Sessions",
        category="workload",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"max_consecutive": "int"},
        optional_parameters={},
        supported_scopes=["teacher", "department", "whole_school"],
        validation_rules=["max_consecutive_must_be_positive"],
        default_priority=25,
        default_weight=1.0,
        explanation="Caps consecutive back-to-back sessions for teacher wellbeing.",
        approval_required=False,
    ),
    "teacher_min_break": _make(
        key="teacher_min_break",
        title="Teacher Minimum Break",
        category="workload",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"min_break_periods": "int"},
        optional_parameters={},
        supported_scopes=["teacher", "whole_school"],
        validation_rules=["min_break_periods_must_be_non_negative"],
        default_priority=30,
        default_weight=0.9,
        explanation="Reserves minimum break windows between teacher sessions.",
        approval_required=False,
    ),
    "teacher_subject_eligibility": _make(
        key="teacher_subject_eligibility",
        title="Teacher Subject Eligibility",
        category="teacher",
        allowed_enforcement_levels=["hard"],
        required_parameters={"subject_id": "uuid"},
        optional_parameters={},
        supported_scopes=["teacher", "subject"],
        validation_rules=["subject_reference_must_exist"],
        default_priority=5,
        default_weight=1.0,
        explanation="Teacher must be qualified or explicitly assigned for the subject.",
        approval_required=False,
    ),
    "class_unavailable": _make(
        key="class_unavailable",
        title="Class Unavailable",
        category="class",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"weekdays": "list[int]", "period_numbers": "list[int]"},
        optional_parameters={"reason": "str"},
        supported_scopes=["class"],
        validation_rules=["period_numbers_must_be_positive", "weekdays_must_be_0_to_6"],
        default_priority=15,
        default_weight=1.0,
        explanation="Class cannot be scheduled during unavailable windows.",
        approval_required=False,
    ),
    "class_max_daily_sessions": _make(
        key="class_max_daily_sessions",
        title="Class Max Daily Sessions",
        category="class",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"max_sessions": "int"},
        optional_parameters={},
        supported_scopes=["class", "grade", "whole_school"],
        validation_rules=["max_sessions_must_be_positive"],
        default_priority=40,
        default_weight=0.9,
        explanation="Caps daily session count per class.",
        approval_required=False,
    ),
    "subject_required_weekly_sessions": _make(
        key="subject_required_weekly_sessions",
        title="Subject Required Weekly Sessions",
        category="curriculum",
        allowed_enforcement_levels=["hard"],
        required_parameters={"required_sessions": "int"},
        optional_parameters={},
        supported_scopes=["subject", "class"],
        validation_rules=["required_sessions_must_be_positive"],
        default_priority=8,
        default_weight=1.0,
        explanation="Defines required weekly sessions for curriculum delivery.",
        approval_required=False,
    ),
    "subject_required_weekly_minutes": _make(
        key="subject_required_weekly_minutes",
        title="Subject Required Weekly Minutes",
        category="curriculum",
        allowed_enforcement_levels=["hard"],
        required_parameters={"required_minutes": "int"},
        optional_parameters={},
        supported_scopes=["subject", "class"],
        validation_rules=["required_minutes_must_be_positive"],
        default_priority=8,
        default_weight=1.0,
        explanation="Defines required weekly teaching minutes per scope.",
        approval_required=False,
    ),
    "subject_max_daily_sessions": _make(
        key="subject_max_daily_sessions",
        title="Subject Max Daily Sessions",
        category="distribution",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"max_sessions": "int"},
        optional_parameters={},
        supported_scopes=["subject", "class", "grade"],
        validation_rules=["max_sessions_must_be_positive"],
        default_priority=45,
        default_weight=0.8,
        explanation="Caps daily concentration of the same subject.",
        approval_required=False,
    ),
    "subject_spread_across_days": _make(
        key="subject_spread_across_days",
        title="Subject Spread Across Days",
        category="distribution",
        allowed_enforcement_levels=["soft", "preference"],
        required_parameters={"minimum_days": "int"},
        optional_parameters={},
        supported_scopes=["subject", "class", "grade"],
        validation_rules=["minimum_days_must_be_positive"],
        default_priority=70,
        default_weight=0.7,
        explanation="Prefers spreading sessions across multiple days.",
        approval_required=False,
    ),
    "subject_preferred_period": _make(
        key="subject_preferred_period",
        title="Subject Preferred Period",
        category="preference",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={"weekdays": "list[int]"},
        supported_scopes=["subject", "class", "grade"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=85,
        default_weight=0.6,
        explanation="Preferred periods for subject instruction.",
        approval_required=False,
    ),
    "room_required_type": _make(
        key="room_required_type",
        title="Room Required Type",
        category="room",
        allowed_enforcement_levels=["hard"],
        required_parameters={"required_room_type": "str"},
        optional_parameters={},
        supported_scopes=["subject", "class", "teacher"],
        validation_rules=["required_room_type_non_empty"],
        default_priority=12,
        default_weight=1.0,
        explanation="Specialist instruction must use compatible room types.",
        approval_required=False,
    ),
    "room_capacity": _make(
        key="room_capacity",
        title="Room Capacity",
        category="room",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"minimum_capacity": "int"},
        optional_parameters={},
        supported_scopes=["room", "class", "whole_school"],
        validation_rules=["minimum_capacity_must_be_non_negative"],
        default_priority=10,
        default_weight=1.0,
        explanation="Room capacity must satisfy class size when available.",
        approval_required=False,
    ),
    "room_unavailable": _make(
        key="room_unavailable",
        title="Room Unavailable",
        category="resource",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"weekdays": "list[int]", "period_numbers": "list[int]"},
        optional_parameters={"reason": "str"},
        supported_scopes=["room"],
        validation_rules=["period_numbers_must_be_positive", "weekdays_must_be_0_to_6"],
        default_priority=15,
        default_weight=1.0,
        explanation="Room cannot host sessions in specified slots.",
        approval_required=False,
    ),
    "fixed_session": _make(
        key="fixed_session",
        title="Fixed Session",
        category="time",
        allowed_enforcement_levels=["hard"],
        required_parameters={"weekday": "int", "period_number": "int"},
        optional_parameters={"room_id": "uuid", "teacher_id": "uuid", "subject_id": "uuid"},
        supported_scopes=["class", "subject", "teacher", "room"],
        validation_rules=["weekday_must_be_0_to_6", "period_number_must_be_positive"],
        default_priority=5,
        default_weight=1.0,
        explanation="Locks a session to a specific time slot.",
        approval_required=True,
    ),
    "avoid_period": _make(
        key="avoid_period",
        title="Avoid Period",
        category="time",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={"weekdays": "list[int]"},
        supported_scopes=["whole_school", "class", "subject", "teacher"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=80,
        default_weight=0.5,
        explanation="Discourages usage of selected periods.",
        approval_required=False,
    ),
    "preferred_period": _make(
        key="preferred_period",
        title="Preferred Period",
        category="preference",
        allowed_enforcement_levels=["preference", "advisory", "soft"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={"weekdays": "list[int]"},
        supported_scopes=["whole_school", "class", "subject", "teacher"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=90,
        default_weight=0.5,
        explanation="Preferred periods for scheduling quality.",
        approval_required=False,
    ),
    "lunch_protection": _make(
        key="lunch_protection",
        title="Lunch Protection",
        category="time",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"period_numbers": "list[int]"},
        optional_parameters={"weekdays": "list[int]"},
        supported_scopes=["whole_school", "grade", "class", "teacher"],
        validation_rules=["period_numbers_must_be_positive"],
        default_priority=18,
        default_weight=1.0,
        explanation="Protects lunch/break windows from teaching sessions.",
        approval_required=False,
    ),
    "campus_travel_buffer": _make(
        key="campus_travel_buffer",
        title="Campus Travel Buffer",
        category="campus",
        allowed_enforcement_levels=["hard", "soft"],
        required_parameters={"minimum_buffer_periods": "int"},
        optional_parameters={},
        supported_scopes=["teacher", "whole_school", "campus"],
        validation_rules=["minimum_buffer_periods_must_be_non_negative"],
        default_priority=22,
        default_weight=0.9,
        explanation="Enforces travel buffer between campuses.",
        approval_required=False,
    ),
    "balanced_teacher_load": _make(
        key="balanced_teacher_load",
        title="Balanced Teacher Load",
        category="distribution",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"target_variance": "float"},
        optional_parameters={},
        supported_scopes=["department", "whole_school"],
        validation_rules=["target_variance_must_be_non_negative"],
        default_priority=75,
        default_weight=0.6,
        explanation="Promotes balanced teaching load distribution.",
        approval_required=False,
    ),
    "minimize_teacher_gaps": _make(
        key="minimize_teacher_gaps",
        title="Minimize Teacher Gaps",
        category="distribution",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"max_gap_periods": "int"},
        optional_parameters={},
        supported_scopes=["teacher", "department", "whole_school"],
        validation_rules=["max_gap_periods_must_be_non_negative"],
        default_priority=78,
        default_weight=0.6,
        explanation="Reduces idle gaps in teacher schedules.",
        approval_required=False,
    ),
    "minimize_room_changes": _make(
        key="minimize_room_changes",
        title="Minimize Room Changes",
        category="distribution",
        allowed_enforcement_levels=["soft", "preference", "advisory"],
        required_parameters={"max_room_changes_per_day": "int"},
        optional_parameters={},
        supported_scopes=["class", "teacher", "whole_school"],
        validation_rules=["max_room_changes_per_day_must_be_non_negative"],
        default_priority=76,
        default_weight=0.6,
        explanation="Reduces room changes for stability and transitions.",
        approval_required=False,
    ),
}


def get_constraint_type_or_none(constraint_type: str) -> ConstraintTypeDefinition | None:
    return CONSTRAINT_TYPE_REGISTRY.get(constraint_type)


def list_constraint_types() -> list[ConstraintTypeDefinition]:
    return [CONSTRAINT_TYPE_REGISTRY[key] for key in sorted(CONSTRAINT_TYPE_REGISTRY.keys())]


def validate_constraint_parameters(definition: ConstraintTypeDefinition, parameters: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for key in definition["required_parameters"].keys():
        if key not in parameters:
            errors.append(f"Missing required parameter: {key}.")

    allowed = set(definition["required_parameters"].keys()) | set(definition["optional_parameters"].keys())
    for key in parameters.keys():
        if key not in allowed:
            errors.append(f"Unsupported parameter: {key}.")

    def _list_of_int(key: str, *, positive: bool = True) -> None:
        value = parameters.get(key)
        if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
            errors.append(f"{key} must be a list of integers.")
            return
        if positive and any(item <= 0 for item in value):
            errors.append(f"{key} values must be positive integers.")

    if "period_numbers" in parameters:
        _list_of_int("period_numbers")
    if "weekdays" in parameters:
        value = parameters.get("weekdays")
        if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
            errors.append("weekdays must be a list of integers.")
        elif any(item < 0 or item > 6 for item in value):
            errors.append("weekdays values must be between 0 and 6.")

    for key in (
        "max_sessions",
        "max_consecutive",
        "required_sessions",
        "required_minutes",
        "period_number",
        "weekday",
        "max_periods",
        "max_minutes",
    ):
        if key in parameters and (not isinstance(parameters[key], int) or int(parameters[key]) <= 0):
            errors.append(f"{key} must be a positive integer.")

    for key in (
        "min_break_periods",
        "minimum_capacity",
        "minimum_buffer_periods",
        "max_gap_periods",
        "max_room_changes_per_day",
        "minimum_days",
    ):
        if key in parameters and (not isinstance(parameters[key], int) or int(parameters[key]) < 0):
            errors.append(f"{key} must be a non-negative integer.")

    if "target_variance" in parameters and (not isinstance(parameters["target_variance"], (float, int)) or float(parameters["target_variance"]) < 0):
        errors.append("target_variance must be a non-negative number.")

    if "required_room_type" in parameters and (not isinstance(parameters["required_room_type"], str) or not parameters["required_room_type"].strip()):
        errors.append("required_room_type must be a non-empty string.")

    if definition["key"] == "ordered_substitution_fallback_tiers":
        if not isinstance(parameters.get("tiers"), list) or not parameters["tiers"]:
            errors.append("tiers must be a non-empty list.")

    return errors
