from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_solver_refuses_when_not_eligible() -> None:
    problem = make_problem(solver_eligible=False)
    result = solve_scheduling_problem(problem)

    assert result.status == "invalid_problem"
    assert result.feasible is False
    assert any(item.code == "solver_eligible_false" for item in result.diagnostics)


def test_solver_refuses_with_validation_blockers() -> None:
    problem = make_problem()
    blocked = replace(
        problem,
        solver_eligible=False,
        validation_summary=replace(
            problem.validation_summary,
            valid=False,
            blocker_count=1,
        ),
    )

    result = solve_scheduling_problem(blocked)
    assert result.status == "invalid_problem"
    assert any(item.code == "problem_validation_blockers" for item in result.diagnostics)


def test_simple_problem_solves_and_places_each_occurrence_once() -> None:
    problem = make_problem()
    result = solve_scheduling_problem(problem, SolveOptions(max_time_seconds=3.0))

    assert result.feasible is True
    unit_ids = {row.occurrence_id for row in result.assignments if row.parallel_child_id is None}
    assert "req_math_8a#occ1" in unit_ids
    assert "req_math_8a#occ2" in unit_ids
    assert "req_lang_8a#occ1" in unit_ids

    fixed = [row for row in result.assignments if row.occurrence_id == "req_math_8a#occ1" and row.parallel_child_id is None]
    assert fixed
    assert fixed[0].period_key == "d0:p1"


def test_production_repair_without_supported_baseline_is_blocked() -> None:
    problem = make_problem(with_baseline=False)
    repair = replace(problem, generation_mode="repair")

    result = solve_scheduling_problem(repair)
    assert result.status == "invalid_problem"
    assert any(item.code == "repair_baseline_missing" for item in result.diagnostics)
