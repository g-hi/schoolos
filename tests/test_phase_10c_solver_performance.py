from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_moderate_synthetic_problem_solves_within_reasonable_budget() -> None:
    base = make_problem(include_parallel=True)

    extra_requirements = list(base.teaching_requirements)
    for index in range(3, 8):
        extra_requirements.append(
            replace(
                base.teaching_requirements[0],
                requirement_id=f"req_extra_{index}",
                class_id="class_8b",
                weekly_sessions=1,
                teacher_id=None,
                eligible_teacher_ids=("t1", "t2"),
                fixed_session_rule_indexes=tuple(),
            )
        )

    moderate = replace(base, teaching_requirements=tuple(extra_requirements))

    started = perf_counter()
    result = solve_scheduling_problem(moderate, SolveOptions(max_time_seconds=5.0, deterministic_mode=True))
    elapsed = perf_counter() - started

    assert result.status in {"optimal", "feasible", "timeout_with_solution"}
    assert result.metrics.placement_unit_count >= len(extra_requirements)
    assert elapsed < 10.0
