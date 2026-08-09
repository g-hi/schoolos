from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from services.gateway.timetable_setup.solver import solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_teacher_class_room_collisions_are_prevented() -> None:
    problem = make_problem(include_parallel=True)
    result = solve_scheduling_problem(problem)

    assert result.feasible is True

    teacher_slot = defaultdict(int)
    class_slot = defaultdict(int)
    room_slot = defaultdict(int)

    for row in result.assignments:
        teacher_slot[(row.teacher_id, row.period_key)] += 1 if row.teacher_id else 0
        class_slot[(row.class_id, row.period_key)] += 1 if row.parallel_child_id is None else 0
        room_slot[(row.room_id, row.period_key)] += 1 if row.room_id else 0

    assert all(value <= 1 for value in teacher_slot.values())
    assert all(value <= 1 for value in class_slot.values())
    assert all(value <= 1 for value in room_slot.values())


def test_infeasible_when_teacher_unavailable_for_mandatory_requirement() -> None:
    problem = make_problem()
    policy = list(problem.policy_constraints)
    policy.append(
        replace(
            policy[0],
            constraint_id="pc_unavail",
            constraint_type="teacher_unavailable",
            scope_reference_id="t1",
            parameters={"weekdays": [0, 1, 2, 3, 4], "period_numbers": [1, 2, 3, 4]},
        )
    )
    constrained = replace(problem, policy_constraints=tuple(policy))

    result = solve_scheduling_problem(constrained)
    assert result.status in {"invalid_problem", "infeasible"}
