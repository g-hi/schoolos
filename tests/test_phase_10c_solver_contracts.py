from __future__ import annotations

from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_solver_contract_status_and_shape() -> None:
    problem = make_problem()
    result = solve_scheduling_problem(problem, SolveOptions(max_time_seconds=2.0, deterministic_mode=True))

    assert result.problem_id == problem.problem_id
    assert result.problem_fingerprint == problem.source_fingerprint
    assert result.solver_name == "or-tools-cp-sat"
    assert result.solver_version
    assert result.status in {
        "optimal",
        "feasible",
        "infeasible",
        "invalid_problem",
        "timeout_with_solution",
        "timeout_without_solution",
        "unknown",
        "solver_error",
    }
    assert result.metrics.placement_unit_count > 0
    assert result.metrics.logical_slot_count > 0
