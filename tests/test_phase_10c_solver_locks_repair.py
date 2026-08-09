from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_locked_baseline_assignment_preserved_when_supported() -> None:
    problem = make_problem(with_baseline=True)
    locks = tuple(replace(lock, lock_state="locked") if lock.target_reference_code == "req_math_8a#occ1" else lock for lock in problem.locks)
    locked = replace(problem, locks=locks)

    result = solve_scheduling_problem(locked)
    assert result.feasible
    row = next(item for item in result.assignments if item.occurrence_id == "req_math_8a#occ1" and item.parallel_child_id is None)
    assert row.period_key == "d0:p1"


def test_hard_lock_without_baseline_resolution_is_blocked() -> None:
    problem = make_problem(with_baseline=False)
    locks = tuple(replace(lock, lock_state="locked") if lock.target_reference_code == "req_math_8a#occ1" else lock for lock in problem.locks)
    broken = replace(problem, locks=locks)

    result = solve_scheduling_problem(broken)
    assert result.status == "invalid_problem"
    assert any(item.code in {"repair_baseline_missing", "lock_requires_baseline"} for item in result.diagnostics)


def test_department_lock_target_remains_unsupported() -> None:
    problem = make_problem()
    bad_lock = replace(problem.locks[0], lock_id="l_dep", target_type="department", target_reference_code="science", lock_state="locked")
    result = solve_scheduling_problem(replace(problem, locks=(bad_lock,)))

    assert result.status == "invalid_problem"
    assert any(item.code == "unsupported_lock_target" for item in result.diagnostics)
