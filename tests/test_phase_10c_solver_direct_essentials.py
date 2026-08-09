from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver.cp_sat_solver import _status_to_contract
from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_hard_teacher_preference_enforced_directly() -> None:
    problem = make_problem()
    prefs = list(problem.teacher_preferences)
    prefs.append(
        replace(
            prefs[1],
            preference_id="hard_t1_avoid_d0p1",
            teacher_id="t1",
            preference_type="avoid_selected_periods",
            strength="hard",
            weekday_values=(0,),
            period_numbers=(1,),
        )
    )
    result = solve_scheduling_problem(replace(problem, teacher_preferences=tuple(prefs)))
    assert result.feasible
    assert all(not (row.teacher_id == "t1" and "d0:p1" in row.occupied_period_keys) for row in result.assignments)


def test_hard_constraint_not_tradable_for_objective_score() -> None:
    problem = make_problem(include_parallel=False)
    reqs = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_math_8a":
            reqs.append(replace(req, teacher_id="t1", eligible_teacher_ids=("t1",), weekly_sessions=1, fixed_session_rule_indexes=(0,)))
        elif req.requirement_id == "req_math_8b":
            reqs.append(replace(req, teacher_id="t1", eligible_teacher_ids=("t1",), fixed_session_rule_indexes=(0,)))
        else:
            reqs.append(req)

    fixed = [
        replace(problem.fixed_sessions[0], fixed_session_id="fx_hard_a", requirement_id="req_math_8a", class_id="class_8a", teacher_id="t1", room_id="r101", period_key="d0:p1"),
        replace(problem.fixed_sessions[0], fixed_session_id="fx_hard_b", requirement_id="req_math_8b", class_id="class_8b", teacher_id="t1", room_id="r102", period_key="d0:p1"),
    ]

    result = solve_scheduling_problem(replace(problem, teaching_requirements=tuple(reqs), fixed_sessions=tuple(fixed)))
    assert result.status in {"infeasible", "invalid_problem"}


def test_logical_identity_ignores_clock_only_changes() -> None:
    problem = make_problem()
    result_one = solve_scheduling_problem(problem)

    shifted = []
    for p in problem.logical_periods:
        shifted.append(replace(p, starts_at="09:00", ends_at="09:40"))
    result_two = solve_scheduling_problem(replace(problem, logical_periods=tuple(shifted)))

    one = sorted((a.occurrence_id, a.parallel_child_id, a.period_key) for a in result_one.assignments)
    two = sorted((a.occurrence_id, a.parallel_child_id, a.period_key) for a in result_two.assignments)
    assert one == two


def test_solve_options_time_limit_path_executes() -> None:
    problem = make_problem(include_parallel=True)
    result = solve_scheduling_problem(problem, SolveOptions(max_time_seconds=0.2, deterministic_mode=True))
    assert result.metrics.runtime_ms >= 0
    assert result.status in {"optimal", "feasible", "timeout_with_solution", "timeout_without_solution", "infeasible", "invalid_problem", "unknown"}


def test_status_mapping_feasible_vs_optimal_contract_level() -> None:
    optimal_status = _status_to_contract(4, has_solution=True, timed_out=False)
    feasible_status = _status_to_contract(2, has_solution=True, timed_out=False)
    assert optimal_status == ("optimal", True, True)
    assert feasible_status == ("feasible", True, False)


def test_objective_priority_dominance_direct_signal_present() -> None:
    problem = make_problem()
    prefs = list(problem.teacher_preferences)
    prefs.append(
        replace(
            prefs[0],
            preference_id="extra_low_pref",
            teacher_id="t1",
            preference_type="prefer_selected_periods",
            strength="low",
            weekday_values=(0, 1, 2, 3, 4),
            period_numbers=(4,),
        )
    )
    result = solve_scheduling_problem(replace(problem, teacher_preferences=tuple(prefs)))
    assert result.feasible
    priorities = {item.priority for item in result.objective_components}
    assert "high" in priorities
    assert "low" in priorities


def test_behavioral_high_priority_dominates_aggregate_low_tradeoff() -> None:
    problem = make_problem(include_parallel=False)

    # Keep only one occurrence and constrain class time-domain to exactly two competing slots.
    req = replace(
        problem.teaching_requirements[0],
        requirement_id="req_tradeoff",
        class_id="class_8a",
        teacher_id="t1",
        eligible_teacher_ids=("t1",),
        weekly_sessions=1,
        fixed_session_rule_indexes=tuple(),
    )
    class_8a = replace(
        problem.classes[0],
        schedulable_period_keys=("d0:p1", "d0:p4"),
        requirement_ids=("req_tradeoff",),
        fixed_session_ids=tuple(),
    )

    # Option A: d0:p4 satisfies HIGH, violates three LOW objectives.
    # Option B: d0:p1 violates HIGH, satisfies the LOW objectives.
    # Solver must choose Option A if hierarchy HIGH > aggregate LOW is respected.
    high_pref = replace(
        problem.teacher_preferences[0],
        preference_id="pref_high_avoid_p1",
        teacher_id="t1",
        preference_type="avoid_selected_periods",
        strength="strong",
        weekday_values=(0,),
        period_numbers=(1,),
    )
    low_pref_1 = replace(
        problem.teacher_preferences[0],
        preference_id="pref_low_avoid_p4_1",
        teacher_id="t1",
        preference_type="avoid_selected_periods",
        strength="low",
        weekday_values=(0,),
        period_numbers=(4,),
    )
    low_pref_2 = replace(low_pref_1, preference_id="pref_low_avoid_p4_2")
    low_pref_3 = replace(low_pref_1, preference_id="pref_low_avoid_p4_3")

    payload = replace(
        problem,
        classes=(class_8a,),
        teaching_requirements=(req,),
        fixed_sessions=tuple(),
        teacher_preferences=(high_pref, low_pref_1, low_pref_2, low_pref_3),
    )

    result = solve_scheduling_problem(payload)
    assert result.feasible

    row = next(item for item in result.assignments if item.requirement_id == "req_tradeoff")
    assert row.period_key == "d0:p4"
