from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SOLVER_STATUS_VALUES = {
    "optimal",
    "feasible",
    "infeasible",
    "invalid_problem",
    "timeout_with_solution",
    "timeout_without_solution",
    "unknown",
    "solver_error",
}


@dataclass(frozen=True, slots=True)
class SolveOptions:
    max_time_seconds: float = 10.0
    deterministic_mode: bool = True
    random_seed: int = 42
    num_search_workers: int = 1
    log_search_progress: bool = False
    stop_after_first_feasible: bool = False


@dataclass(frozen=True, slots=True)
class SolverAssignment:
    occurrence_id: str
    requirement_id: str | None
    class_id: str
    subject_id: str | None
    day_key: str
    period_key: str
    teacher_id: str | None
    room_id: str | None
    parallel_block_id: str | None
    parallel_child_id: str | None
    fixed: bool
    lock_state: str | None
    periods_per_session: int = 1
    occupied_period_keys: tuple[str, ...] = tuple()


@dataclass(frozen=True, slots=True)
class SolverObjectiveComponent:
    key: str
    priority: str
    score: int
    max_score: int
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SolverDiagnostic:
    code: str
    message: str
    severity: str
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SolverMetrics:
    runtime_ms: int
    objective_score: int | None
    boolean_variables: int
    integer_variables: int
    constraint_count: int
    placement_unit_count: int
    logical_slot_count: int
    eligible_teacher_links: int
    room_links: int
    parallel_block_count: int
    teacher_gap_count: int


@dataclass(frozen=True, slots=True)
class SolverResult:
    problem_id: str
    problem_fingerprint: str
    solver_name: str
    solver_version: str
    status: str
    feasible: bool
    optimal: bool
    assignments: tuple[SolverAssignment, ...]
    objective_score: int | None
    objective_components: tuple[SolverObjectiveComponent, ...]
    hard_constraint_summary: dict[str, Any]
    diagnostics: tuple[SolverDiagnostic, ...]
    warnings: tuple[SolverDiagnostic, ...]
    metrics: SolverMetrics
    solver_statistics: dict[str, Any]
    input_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "problem_fingerprint": self.problem_fingerprint,
            "solver_name": self.solver_name,
            "solver_version": self.solver_version,
            "status": self.status,
            "feasible": self.feasible,
            "optimal": self.optimal,
            "assignments": [vars(item) for item in self.assignments],
            "objective_score": self.objective_score,
            "objective_components": [vars(item) for item in self.objective_components],
            "hard_constraint_summary": self.hard_constraint_summary,
            "diagnostics": [vars(item) for item in self.diagnostics],
            "warnings": [vars(item) for item in self.warnings],
            "metrics": vars(self.metrics),
            "solver_statistics": self.solver_statistics,
            "input_counts": self.input_counts,
        }
