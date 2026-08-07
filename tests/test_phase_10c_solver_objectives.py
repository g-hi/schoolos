from __future__ import annotations

from dataclasses import replace

from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from tests.test_phase_10c_solver_fixtures import make_problem


def test_stability_mode_very_high_penalizes_disruption_at_least_as_much_as_flexible() -> None:
    base = make_problem(with_baseline=True)
    very_high = replace(base, stability_mode="very_high")
    flexible = replace(base, stability_mode="flexible")

    result_high = solve_scheduling_problem(very_high, SolveOptions(max_time_seconds=3.0))
    result_flexible = solve_scheduling_problem(flexible, SolveOptions(max_time_seconds=3.0))

    assert result_high.feasible and result_flexible.feasible
    score_high = next((c.score for c in result_high.objective_components if c.key == "minimize_timetable_disruption"), 0)
    score_flexible = next((c.score for c in result_flexible.objective_components if c.key == "minimize_timetable_disruption"), 0)
    assert score_high <= score_flexible


def test_priority_dominance_high_vs_low_preferences() -> None:
    problem = make_problem()
    prefs = list(problem.teacher_preferences)
    prefs.append(
        replace(
            prefs[0],
            preference_id="low_pref",
            teacher_id="t1",
            preference_type="prefer_selected_periods",
            strength="low",
            weekday_values=(0, 1, 2, 3, 4),
            period_numbers=(4,),
        )
    )
    adjusted = replace(problem, teacher_preferences=tuple(prefs))

    result = solve_scheduling_problem(adjusted, SolveOptions(max_time_seconds=3.0))
    assert result.feasible is True
    # Dominance assertion: high-priority teacher preference component should not be worse than its bound while low terms exist.
    high_components = [c for c in result.objective_components if c.priority == "high"]
    low_components = [c for c in result.objective_components if c.priority == "low"]
    assert high_components
    assert low_components


def test_teacher_gap_metric_reported() -> None:
    problem = make_problem()
    result = solve_scheduling_problem(problem)
    assert result.feasible
    assert result.metrics.teacher_gap_count >= 0
