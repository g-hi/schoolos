from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.gateway.timetable_setup.scheduling_problem import PolicyConstraintRecord
from services.gateway.timetable_setup.solver.contracts import SolverDiagnostic


SUPPORTED_HARD_POLICY_TYPES = {
    "teacher_unavailable",
    "class_unavailable",
    "room_unavailable",
    "teacher_max_daily_sessions",
    "teacher_max_consecutive_sessions",
    "subject_required_weekly_sessions",
}


SUPPORTED_SOFT_POLICY_TYPES = {
    "teacher_preferred_period",
    "subject_daily_spread",
}


@dataclass(frozen=True, slots=True)
class ConstraintExtraction:
    teacher_unavailable: dict[str, set[str]]
    class_unavailable: dict[str, set[str]]
    room_unavailable: dict[str, set[str]]
    teacher_max_daily: dict[str, int]
    teacher_max_consecutive: dict[str, int]
    soft_preferred_periods: dict[str, set[str]]
    unsupported_hard: tuple[SolverDiagnostic, ...]
    unsupported_soft: tuple[SolverDiagnostic, ...]


def _slot(day: int, period: int) -> str:
    return f"d{day}:p{period}"


def extract_constraints(constraints: tuple[PolicyConstraintRecord, ...]) -> ConstraintExtraction:
    teacher_unavailable: dict[str, set[str]] = {}
    class_unavailable: dict[str, set[str]] = {}
    room_unavailable: dict[str, set[str]] = {}
    teacher_max_daily: dict[str, int] = {}
    teacher_max_consecutive: dict[str, int] = {}
    soft_preferred_periods: dict[str, set[str]] = {}

    unsupported_hard: list[SolverDiagnostic] = []
    unsupported_soft: list[SolverDiagnostic] = []

    for item in constraints:
        ctype = item.constraint_type
        enforcement = item.enforcement
        params = item.parameters or {}

        if enforcement == "hard" and ctype not in SUPPORTED_HARD_POLICY_TYPES:
            unsupported_hard.append(
                SolverDiagnostic(
                    code="unsupported_hard_policy_constraint",
                    message="Unsupported hard policy constraint type for solver encoding.",
                    severity="blocker",
                    entity_type="policy_constraint",
                    entity_id=item.constraint_id,
                    details={"constraint_type": ctype},
                )
            )
            continue

        if enforcement != "hard" and ctype not in SUPPORTED_HARD_POLICY_TYPES and ctype not in SUPPORTED_SOFT_POLICY_TYPES:
            unsupported_soft.append(
                SolverDiagnostic(
                    code="unsupported_soft_policy_constraint",
                    message="Unsupported soft policy constraint type was excluded from optimization.",
                    severity="warning",
                    entity_type="policy_constraint",
                    entity_id=item.constraint_id,
                    details={"constraint_type": ctype},
                )
            )
            continue

        if ctype == "teacher_unavailable" and item.scope_reference_id:
            weekdays = [value for value in params.get("weekdays", []) if isinstance(value, int)]
            periods = [value for value in params.get("period_numbers", []) if isinstance(value, int)]
            for day in weekdays:
                for period in periods:
                    teacher_unavailable.setdefault(item.scope_reference_id, set()).add(_slot(day, period))
            continue

        if ctype == "class_unavailable" and item.scope_reference_id:
            weekdays = [value for value in params.get("weekdays", []) if isinstance(value, int)]
            periods = [value for value in params.get("period_numbers", []) if isinstance(value, int)]
            for day in weekdays:
                for period in periods:
                    class_unavailable.setdefault(item.scope_reference_id, set()).add(_slot(day, period))
            continue

        if ctype == "room_unavailable" and item.scope_reference_id:
            weekdays = [value for value in params.get("weekdays", []) if isinstance(value, int)]
            periods = [value for value in params.get("period_numbers", []) if isinstance(value, int)]
            for day in weekdays:
                for period in periods:
                    room_unavailable.setdefault(item.scope_reference_id, set()).add(_slot(day, period))
            continue

        if ctype == "teacher_max_daily_sessions" and item.scope_reference_id:
            value = params.get("max_sessions")
            if isinstance(value, int) and value > 0:
                teacher_max_daily[item.scope_reference_id] = value
            continue

        if ctype == "teacher_max_consecutive_sessions" and item.scope_reference_id:
            value = params.get("max_consecutive")
            if isinstance(value, int) and value > 0:
                teacher_max_consecutive[item.scope_reference_id] = value
            continue

        if ctype == "teacher_preferred_period" and item.scope_reference_id:
            weekdays = [value for value in params.get("weekdays", []) if isinstance(value, int)]
            periods = [value for value in params.get("period_numbers", []) if isinstance(value, int)]
            for day in weekdays:
                for period in periods:
                    soft_preferred_periods.setdefault(item.scope_reference_id, set()).add(_slot(day, period))

    return ConstraintExtraction(
        teacher_unavailable=teacher_unavailable,
        class_unavailable=class_unavailable,
        room_unavailable=room_unavailable,
        teacher_max_daily=teacher_max_daily,
        teacher_max_consecutive=teacher_max_consecutive,
        soft_preferred_periods=soft_preferred_periods,
        unsupported_hard=tuple(unsupported_hard),
        unsupported_soft=tuple(unsupported_soft),
    )
