from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def _double_problem():
    problem = make_problem(include_parallel=True)
    reqs = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_math_8a":
            reqs.append(replace(req, weekly_sessions=2, periods_per_session=2))
        elif req.requirement_id == "req_lang_8a":
            reqs.append(replace(req, periods_per_session=2))
        else:
            reqs.append(req)
    return replace(problem, teaching_requirements=tuple(reqs))


def test_basic_double_lesson_occupies_two_consecutive_periods() -> None:
    problem = _double_problem()
    result = solve_scheduling_problem(problem)

    assert result.feasible
    row = next(item for item in result.assignments if item.occurrence_id == "req_math_8a#occ1" and item.parallel_child_id is None)
    assert row.periods_per_session == 2
    assert len(row.occupied_period_keys) == 2
    first = int(row.occupied_period_keys[0].split(":")[1][1:])
    second = int(row.occupied_period_keys[1].split(":")[1][1:])
    assert second == first + 1


def test_double_lesson_blocks_class_overlap_at_second_period() -> None:
    problem = _double_problem()
    # Force another class_8a lesson into day0:p2 to collide with fixed double at day0:p1+day0:p2.
    fixed = list(problem.fixed_sessions)
    fixed.append(
        replace(
            problem.fixed_sessions[0],
            fixed_session_id="fx_overlap_class",
            requirement_id="req_lang_8a",
            class_id="class_8a",
            teacher_id="t3",
            room_id="r102",
            period_key="d0:p2",
        )
    )
    payload = replace(problem, fixed_sessions=tuple(fixed))

    result = solve_scheduling_problem(payload)
    assert result.status in {"infeasible", "invalid_problem"}


def test_double_lesson_blocks_teacher_overlap_at_second_period() -> None:
    problem = _double_problem()
    reqs = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_lang_8a":
            reqs.append(replace(req, teacher_id="t1", eligible_teacher_ids=("t1",), periods_per_session=1))
        else:
            reqs.append(req)
    fixed = list(problem.fixed_sessions)
    fixed.append(
        replace(
            problem.fixed_sessions[0],
            fixed_session_id="fx_overlap_teacher",
            requirement_id="req_lang_8a",
            class_id="class_8a",
            teacher_id="t1",
            room_id="r102",
            period_key="d0:p2",
        )
    )
    payload = replace(problem, teaching_requirements=tuple(reqs), fixed_sessions=tuple(fixed))

    result = solve_scheduling_problem(payload)
    assert result.status in {"infeasible", "invalid_problem"}


def test_double_lesson_blocks_room_overlap_at_second_period() -> None:
    problem = _double_problem()
    reqs = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_lang_8a":
            reqs.append(replace(req, periods_per_session=1))
        else:
            reqs.append(req)
    fixed = list(problem.fixed_sessions)
    fixed.append(
        replace(
            problem.fixed_sessions[0],
            fixed_session_id="fx_overlap_room",
            requirement_id="req_lang_8a",
            class_id="class_8a",
            teacher_id="t3",
            room_id="r101",
            period_key="d0:p2",
        )
    )
    payload = replace(problem, teaching_requirements=tuple(reqs), fixed_sessions=tuple(fixed))

    result = solve_scheduling_problem(payload)
    assert result.status in {"infeasible", "invalid_problem"}


def test_double_lesson_rejected_when_teacher_unavailable_on_second_slot() -> None:
    problem = _double_problem()
    reqs = []
    for req in problem.teaching_requirements:
        if req.requirement_id == "req_math_8a":
            reqs.append(replace(req, teacher_id="t2", eligible_teacher_ids=("t2",), fixed_session_rule_indexes=tuple()))
        else:
            reqs.append(req)
    prefs = list(problem.teacher_preferences)
    prefs.append(
        replace(
            prefs[1],
            preference_id="hard_unavail_t2",
            teacher_id="t2",
            preference_type="avoid_selected_periods",
            strength="hard",
            weekday_values=(0,),
            period_numbers=(2,),
        )
    )
    fixed = tuple(item for item in problem.fixed_sessions if item.requirement_id != "req_math_8a")
    payload = replace(problem, teaching_requirements=tuple(reqs), teacher_preferences=tuple(prefs), fixed_sessions=fixed)

    result = solve_scheduling_problem(payload)
    assert all(not (row.occurrence_id.startswith("req_math_8a") and row.period_key == "d0:p1") for row in result.assignments)


def test_end_of_day_start_invalid_for_double_lesson() -> None:
    problem = make_problem()
    req = replace(problem.teaching_requirements[2], requirement_id="req_end_day", class_id="class_8b", teacher_id="t1", eligible_teacher_ids=("t1",), weekly_sessions=1, periods_per_session=2)
    fixed = replace(problem.fixed_sessions[0], fixed_session_id="fx_end_day", requirement_id="req_end_day", class_id="class_8b", teacher_id="t1", room_id="r102", period_key="d0:p4")
    payload = replace(problem, teaching_requirements=tuple(problem.teaching_requirements) + (req,), fixed_sessions=tuple(problem.fixed_sessions) + (fixed,))

    result = solve_scheduling_problem(payload)
    assert result.status == "invalid_problem"
    assert any(item.code == "multi_period_fixed_session_conflict" for item in result.diagnostics)


def test_non_teaching_break_interrupts_multi_period_sequence() -> None:
    problem = make_problem()
    periods = []
    for item in problem.logical_periods:
        if item.key == "d0:p2":
            periods.append(replace(item, is_teaching_period=False))
        else:
            periods.append(item)
    req = replace(problem.teaching_requirements[2], requirement_id="req_break", class_id="class_8b", teacher_id="t1", eligible_teacher_ids=("t1",), weekly_sessions=1, periods_per_session=2)
    fixed = replace(problem.fixed_sessions[0], fixed_session_id="fx_break", requirement_id="req_break", class_id="class_8b", teacher_id="t1", room_id="r102", period_key="d0:p1")
    payload = replace(problem, logical_periods=tuple(periods), teaching_requirements=tuple(problem.teaching_requirements) + (req,), fixed_sessions=tuple(problem.fixed_sessions) + (fixed,))

    result = solve_scheduling_problem(payload)
    assert result.status == "invalid_problem"
    assert any(item.code == "multi_period_fixed_session_conflict" for item in result.diagnostics)


def test_fixed_double_lesson_occupies_required_span() -> None:
    problem = _double_problem()
    result = solve_scheduling_problem(problem)
    assert result.feasible
    row = next(item for item in result.assignments if item.occurrence_id == "req_math_8a#occ1" and item.parallel_child_id is None)
    assert row.period_key == "d0:p1"
    assert row.occupied_period_keys == ("d0:p1", "d0:p2")


def test_weekly_sessions_and_periods_per_session_semantics() -> None:
    problem = _double_problem()
    result = solve_scheduling_problem(problem)
    assert result.feasible
    rows = [item for item in result.assignments if item.occurrence_id.startswith("req_math_8a#occ") and item.parallel_child_id is None]
    assert len(rows) == 2
    assert all(item.periods_per_session == 2 for item in rows)
    assert sum(len(item.occupied_period_keys) for item in rows) == 4


def test_parallel_double_period_block_children_synchronized_across_span() -> None:
    problem = _double_problem()
    result = solve_scheduling_problem(problem)
    assert result.feasible

    rows = [item for item in result.assignments if item.parallel_block_id == "pb_lang"]
    assert rows
    starts = {item.period_key for item in rows}
    spans = {item.occupied_period_keys for item in rows}
    assert len(starts) == 1
    assert len(spans) == 1
    assert len(next(iter(spans))) == 2


def test_periods_per_session_one_remains_backward_compatible() -> None:
    problem = make_problem()
    result = solve_scheduling_problem(problem)
    assert result.feasible
    plain_rows = [item for item in result.assignments if item.parallel_child_id is None]
    assert plain_rows
    assert all(item.periods_per_session == 1 for item in plain_rows)
    assert all(item.occupied_period_keys == (item.period_key,) for item in plain_rows)
