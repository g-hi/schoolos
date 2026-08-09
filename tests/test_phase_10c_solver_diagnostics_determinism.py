from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_repeated_deterministic_solves_match_assignment_identity() -> None:
    problem = make_problem(include_parallel=True)
    options = SolveOptions(max_time_seconds=3.0, deterministic_mode=True, random_seed=42, num_search_workers=1)

    one = solve_scheduling_problem(problem, options)
    two = solve_scheduling_problem(problem, options)

    assert one.feasible and two.feasible
    a1 = [(row.occurrence_id, row.parallel_child_id, row.period_key, row.teacher_id, row.room_id) for row in one.assignments]
    a2 = [(row.occurrence_id, row.parallel_child_id, row.period_key, row.teacher_id, row.room_id) for row in two.assignments]
    assert a1 == a2


def test_unsupported_hard_policy_blocks_solve_with_reason_code() -> None:
    problem = make_problem()
    unsupported = replace(
        problem.policy_constraints[0],
        constraint_id="pc_unknown",
        constraint_type="campus_travel_buffer",
        enforcement="hard",
        parameters={"min_travel_gap": 1},
    )
    payload = replace(problem, policy_constraints=(unsupported,))

    result = solve_scheduling_problem(payload)
    assert result.status == "invalid_problem"
    assert any(item.code == "unsupported_hard_policy_constraint" for item in result.diagnostics)


def test_solver_does_not_mutate_problem() -> None:
    problem = make_problem(include_parallel=True)
    before = problem.to_dict()
    _ = solve_scheduling_problem(problem)
    after = problem.to_dict()
    assert before == after


def test_hard_generation_override_teacher_free_period_is_enforced() -> None:
    problem = make_problem()
    hard_override = replace(
        problem.generation_overrides[0],
        override_id="ov_hard_teacher",
        strength="hard",
        override_type="teacher_free_period",
        scope_reference_id="t1",
        payload={"weekday": 0, "period_number": 2},
    )
    payload = replace(problem, generation_overrides=(hard_override,))

    result = solve_scheduling_problem(payload)
    assert result.feasible
    assert all(not (row.teacher_id == "t1" and row.period_key == "d0:p2") for row in result.assignments)


def test_unknown_hard_generation_override_blocks_solving() -> None:
    problem = make_problem()
    bad_override = replace(
        problem.generation_overrides[0],
        override_id="ov_hard_unknown",
        strength="hard",
        override_type="campus_compaction",
        payload={"weekday": 0, "period_number": 2},
    )
    payload = replace(problem, generation_overrides=(bad_override,))

    result = solve_scheduling_problem(payload)
    assert result.status == "invalid_problem"
    assert any(item.code == "unsupported_hard_generation_override" for item in result.diagnostics)


def test_infeasible_status_reports_structured_diagnostic() -> None:
    problem = make_problem()
    req_conflict = replace(
        problem.teaching_requirements[2],
        requirement_id="req_conflict_8a",
        class_id="class_8a",
        subject_id="s_math",
        teacher_id="t2",
        eligible_teacher_ids=("t2",),
        weekly_sessions=1,
        fixed_session_rule_indexes=(0,),
    )
    fixed_conflict = replace(
        problem.fixed_sessions[0],
        fixed_session_id="fx_conflict",
        requirement_id="req_conflict_8a",
        class_id="class_8a",
        teacher_id="t2",
        room_id="r102",
        period_key="d0:p1",
    )
    blocked = replace(
        problem,
        teaching_requirements=tuple(problem.teaching_requirements) + (req_conflict,),
        fixed_sessions=tuple(problem.fixed_sessions) + (fixed_conflict,),
    )

    result = solve_scheduling_problem(blocked)
    assert result.status == "infeasible"
    assert any(item.code == "infeasible_model" for item in result.diagnostics)
