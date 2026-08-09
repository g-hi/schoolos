from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_parallel_foreign_language_children_share_one_slot_and_no_student_model() -> None:
    problem = make_problem(include_parallel=True)
    result = solve_scheduling_problem(problem)

    assert result.feasible is True

    parallel_rows = [row for row in result.assignments if row.parallel_block_id == "pb_lang"]
    assert parallel_rows
    assert len({row.period_key for row in parallel_rows}) == 1
    assert all(row.class_id == "class_8a" for row in parallel_rows)


def test_parallel_block_frequency_mismatch_is_rejected() -> None:
    problem = make_problem(include_parallel=True)
    # Inflate one child requirement weekly sessions to trigger mismatch.
    mutated_requirements = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_lang_8a":
            mutated_requirements.append(replace(req, weekly_sessions=2))
        else:
            mutated_requirements.append(req)

    broken = replace(problem, teaching_requirements=tuple(mutated_requirements))
    result = solve_scheduling_problem(broken)

    assert result.status == "invalid_problem"
    assert any(item.code == "parallel_block_frequency_mismatch" for item in result.diagnostics)
