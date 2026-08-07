from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from services.gateway.timetable_setup.candidates import CandidateGenerationOptions, generate_timetable_candidates
from services.gateway.timetable_setup.candidates.contracts import TimetableCandidate
from services.gateway.timetable_setup.candidates.service import _comparison, _pairwise, _repair_impact_summary
from services.gateway.timetable_setup.solver.contracts import (
    SolverAssignment,
    SolverDiagnostic,
    SolverMetrics,
    SolverObjectiveComponent,
    SolverResult,
)
from tests.test_phase_10c_solver_fixtures import make_problem


def test_candidate_generation_is_deterministic_for_same_problem_and_options() -> None:
    problem = make_problem(include_parallel=True)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_comparison=True, include_explanation_facts=True)

    one = generate_timetable_candidates(problem, options=options)
    two = generate_timetable_candidates(problem, options=options)

    assert one.generated_count == two.generated_count
    assert one.candidates[0].assignment_fingerprint == two.candidates[0].assignment_fingerprint
    assert one.candidates[0].candidate_id == two.candidates[0].candidate_id


def test_candidate_generation_deduplicates_equivalent_candidates() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=2, candidate_profiles=("configured", "balanced"), include_comparison=True, include_explanation_facts=False)

    result = generate_timetable_candidates(problem, options=options)

    assert result.requested_count == 2
    assert result.generated_count >= 1
    assert len(result.attempts) == 2
    if result.generated_count == 1:
        assert any(item.get("code") == "candidate_count_not_reached" for item in result.warnings)


def test_candidate_contains_class_facing_assignments_without_parallel_children() -> None:
    problem = make_problem(include_parallel=True)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_comparison=False, include_explanation_facts=False)

    result = generate_timetable_candidates(problem, options=options)
    assert result.generated_count == 1
    candidate = result.candidates[0]

    assert candidate.class_facing_assignments
    assert all(item.get("parallel_child_id") is None for item in candidate.class_facing_assignments)


def test_candidate_includes_explainability_facts_and_quality_components() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_comparison=True, include_explanation_facts=True)

    result = generate_timetable_candidates(problem, options=options)
    candidate = result.candidates[0]

    assert candidate.quality_components
    assert candidate.explanation_facts
    assert all(item.reason_code for item in candidate.explanation_facts)


def test_candidate_repair_impact_summary_reports_mode_even_without_baseline() -> None:
    problem = replace(make_problem(with_baseline=False), generation_mode="repair")
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_comparison=False, include_explanation_facts=False)

    result = generate_timetable_candidates(problem, options=options)
    assert result.generated_count == 0
    assert any(item.get("code") in {"no_candidate_generated", "repair_baseline_missing"} for item in result.diagnostics)


def test_candidate_comparison_recommends_a_candidate_when_available() -> None:
    problem = make_problem(include_parallel=True)
    options = CandidateGenerationOptions(candidate_count=2, candidate_profiles=("configured", "preference_focused"), include_comparison=True, include_explanation_facts=False)

    result = generate_timetable_candidates(problem, options=options)

    assert result.generated_count >= 1
    assert result.comparison is not None
    assert result.comparison.recommended_candidate_id is not None


def _fake_solver_result(*, status: str, feasible: bool, period_key: str = "d0:p1") -> SolverResult:
    return SolverResult(
        problem_id="p1",
        problem_fingerprint="f1",
        solver_name="or-tools-cp-sat",
        solver_version="9.15.6755",
        status=status,
        feasible=feasible,
        optimal=False,
        assignments=(
            SolverAssignment(
                occurrence_id="req_1#occ1",
                requirement_id="req_1",
                class_id="class_8a",
                subject_id="s_math",
                day_key="d0",
                period_key=period_key,
                teacher_id="t1",
                room_id="r101",
                parallel_block_id=None,
                parallel_child_id=None,
                fixed=False,
                lock_state=None,
                periods_per_session=1,
                occupied_period_keys=(period_key,),
            ),
        ),
        objective_score=3,
        objective_components=(
            SolverObjectiveComponent(key="teacher_preferences", priority="high", score=1, max_score=4, details={}),
            SolverObjectiveComponent(key="minimize_teacher_gaps", priority="normal", score=0, max_score=1, details={}),
        ),
        hard_constraint_summary={"all_hard_constraints_satisfied": feasible},
        diagnostics=(
            SolverDiagnostic(code="infeasible_model", message="x", severity="blocker"),
        )
        if not feasible
        else tuple(),
        warnings=tuple(),
        metrics=SolverMetrics(
            runtime_ms=12,
            objective_score=3,
            boolean_variables=10,
            integer_variables=0,
            constraint_count=20,
            placement_unit_count=1,
            logical_slot_count=20,
            eligible_teacher_links=1,
            room_links=1,
            parallel_block_count=0,
            teacher_gap_count=0,
        ),
        solver_statistics={"solve_status": status},
        input_counts={"requirements": 1},
    )


def _fake_candidate(*, cid: str, profile: str, quality: float, gaps: int, assignments: tuple[dict, ...]) -> TimetableCandidate:
    return TimetableCandidate(
        candidate_id=cid,
        problem_id="p1",
        problem_fingerprint="f1",
        generation_configuration_id="cfg1",
        generation_mode="standard",
        candidate_profile=profile,
        assignment_fingerprint=f"fp_{cid}",
        solver_status="feasible",
        feasible=True,
        optimal=False,
        assignments=assignments,
        class_facing_assignments=tuple(item for item in assignments if item.get("parallel_child_id") is None),
        metrics={"teacher_gap_count": gaps, "objective_score": 2, "runtime_ms": 0},
        quality_score=quality,
        quality_band="good",
        quality_components=tuple(),
        preference_summary={},
        fairness_summary={},
        workload_summary={},
        gap_summary={},
        subject_distribution_summary={},
        room_summary={},
        repair_impact_summary={},
        hard_constraint_summary={"all_hard_constraints_satisfied": True},
        diagnostics=tuple(),
        explanation_facts=tuple(),
        warnings=tuple(),
        solver_runtime_ms=0,
        solver_statistics={},
        provenance={"source": "test"},
    )


def test_infeasible_solver_result_does_not_become_candidate_and_preserves_diagnostics() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), deterministic=True)

    with patch("services.gateway.timetable_setup.candidates.service.solve_scheduling_problem", return_value=_fake_solver_result(status="infeasible", feasible=False)):
        result = generate_timetable_candidates(problem, options=options)

    assert result.generated_count == 0
    assert result.candidates == tuple()
    assert result.attempts[0].status == "no_feasible_solution"
    codes = {item.get("code") for item in result.diagnostics}
    assert "infeasible_model" in codes


def test_duplicate_solution_attempt_is_labeled() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=2, candidate_profiles=("configured", "balanced"), deterministic=True)
    fake = _fake_solver_result(status="feasible", feasible=True)

    with patch("services.gateway.timetable_setup.candidates.service.solve_scheduling_problem", side_effect=[fake, fake]):
        result = generate_timetable_candidates(problem, options=options)

    assert result.generated_count == 1
    assert any(item.status == "duplicate_solution" for item in result.attempts)


def test_parallel_block_move_is_one_class_facing_difference() -> None:
    left = _fake_candidate(
        cid="c1",
        profile="configured",
        quality=0.9,
        gaps=3,
        assignments=(
            {"occurrence_id": "o1", "parallel_child_id": "f", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d1:p3", "teacher_id": "t1", "room_id": "r1"},
            {"occurrence_id": "o1", "parallel_child_id": "g", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d1:p3", "teacher_id": "t2", "room_id": "r2"},
            {"occurrence_id": "o1", "parallel_child_id": "s", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d1:p3", "teacher_id": "t3", "room_id": "r3"},
        ),
    )
    right = _fake_candidate(
        cid="c2",
        profile="preference_focused",
        quality=0.8,
        gaps=2,
        assignments=(
            {"occurrence_id": "o1", "parallel_child_id": "f", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d2:p2", "teacher_id": "t1", "room_id": "r1"},
            {"occurrence_id": "o1", "parallel_child_id": "g", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d2:p2", "teacher_id": "t2", "room_id": "r2"},
            {"occurrence_id": "o1", "parallel_child_id": "s", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d2:p2", "teacher_id": "t3", "room_id": "r3"},
        ),
    )

    pair = _pairwise(left, right)
    assert pair.assignment_difference_count == 3
    assert int(pair.metric_deltas["class_facing_difference_count"]) == 1
    assert "parallel_block_move" in pair.reason_codes


def test_tradeoff_does_not_force_universal_recommendation() -> None:
    a = _fake_candidate(
        cid="c1",
        profile="configured",
        quality=0.92,
        gaps=4,
        assignments=({"occurrence_id": "o1", "parallel_child_id": None, "parallel_block_id": None, "class_id": "class_8a", "period_key": "d0:p1", "teacher_id": "t1", "room_id": "r1"},),
    )
    b = _fake_candidate(
        cid="c2",
        profile="balanced",
        quality=0.85,
        gaps=1,
        assignments=({"occurrence_id": "o1", "parallel_child_id": None, "parallel_block_id": None, "class_id": "class_8a", "period_key": "d0:p2", "teacher_id": "t1", "room_id": "r1"},),
    )

    comp = _comparison((a, b))
    assert comp is not None
    assert comp.recommended_candidate_id is None
    assert "tradeoff_no_universal_winner" in comp.recommendation_reason_codes
    assert any(item.get("reason_code") == "gap_preference_tradeoff" for item in comp.explanation_facts)


def test_deterministic_generation_keeps_ids_order_and_metrics_stable() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=2, candidate_profiles=("configured", "preference_focused"), deterministic=True)

    one = generate_timetable_candidates(problem, options=options)
    two = generate_timetable_candidates(problem, options=options)

    assert [c.candidate_id for c in one.candidates] == [c.candidate_id for c in two.candidates]
    assert [c.metrics for c in one.candidates] == [c.metrics for c in two.candidates]
    assert one.duration_ms == two.duration_ms == 0


def test_repair_metrics_report_not_available_when_baseline_is_unsupported() -> None:
    problem = replace(make_problem(with_baseline=True), baseline=replace(make_problem(with_baseline=True).baseline, supported=False, reason="baseline unavailable in production"))
    summary = _repair_impact_summary(problem, _fake_solver_result(status="feasible", feasible=True))
    assert summary["status"] == "not_available"
    assert summary["changed"] is None


def test_configured_profile_keeps_original_priority_contract() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), deterministic=True)

    result = generate_timetable_candidates(problem, options=options)
    assert result.candidates[0].candidate_profile == "configured"


def test_multi_period_move_counts_once_in_pairwise_diff() -> None:
    left = _fake_candidate(
        cid="c1",
        profile="configured",
        quality=0.9,
        gaps=1,
        assignments=(
            {
                "occurrence_id": "req_science#occ1",
                "parallel_child_id": None,
                "parallel_block_id": None,
                "class_id": "class_8a",
                "period_key": "d1:p3",
                "teacher_id": "t1",
                "room_id": "lab1",
                "periods_per_session": 2,
                "occupied_period_keys": ["d1:p3", "d1:p4"],
            },
        ),
    )
    right = _fake_candidate(
        cid="c2",
        profile="balanced",
        quality=0.9,
        gaps=1,
        assignments=(
            {
                "occurrence_id": "req_science#occ1",
                "parallel_child_id": None,
                "parallel_block_id": None,
                "class_id": "class_8a",
                "period_key": "d1:p4",
                "teacher_id": "t1",
                "room_id": "lab1",
                "periods_per_session": 2,
                "occupied_period_keys": ["d1:p4", "d1:p5"],
            },
        ),
    )

    pair = _pairwise(left, right)
    assert pair.assignment_difference_count == 1
    assert "period_move" in pair.reason_codes


def test_explanation_fact_contains_preference_unsatisfied() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_explanation_facts=True)
    fake = _fake_solver_result(status="feasible", feasible=True)

    with patch("services.gateway.timetable_setup.candidates.service.solve_scheduling_problem", return_value=fake):
        result = generate_timetable_candidates(problem, options=options)

    facts = {item.reason_code for item in result.candidates[0].explanation_facts}
    assert "preference_unsatisfied" in facts


def test_explanation_fact_contains_preference_satisfied() -> None:
    problem = make_problem(include_parallel=False)
    options = CandidateGenerationOptions(candidate_count=1, candidate_profiles=("configured",), include_explanation_facts=True)
    fake = replace(
        _fake_solver_result(status="feasible", feasible=True),
        objective_components=(
            SolverObjectiveComponent(key="teacher_preferences", priority="high", score=0, max_score=4, details={}),
            SolverObjectiveComponent(key="minimize_teacher_gaps", priority="normal", score=0, max_score=1, details={}),
        ),
    )

    with patch("services.gateway.timetable_setup.candidates.service.solve_scheduling_problem", return_value=fake):
        result = generate_timetable_candidates(problem, options=options)

    facts = {item.reason_code for item in result.candidates[0].explanation_facts}
    assert "preference_satisfied" in facts


def test_candidate_difference_explanation_fact_includes_parallel_block_reason() -> None:
    left = _fake_candidate(
        cid="c1",
        profile="configured",
        quality=0.95,
        gaps=1,
        assignments=(
            {"occurrence_id": "o1", "parallel_child_id": "f", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d1:p3", "teacher_id": "t1", "room_id": "r1"},
            {"occurrence_id": "o1", "parallel_child_id": "g", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d1:p3", "teacher_id": "t2", "room_id": "r2"},
        ),
    )
    right = _fake_candidate(
        cid="c2",
        profile="balanced",
        quality=0.9,
        gaps=1,
        assignments=(
            {"occurrence_id": "o1", "parallel_child_id": "f", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d2:p2", "teacher_id": "t1", "room_id": "r1"},
            {"occurrence_id": "o1", "parallel_child_id": "g", "parallel_block_id": "pb_lang", "class_id": "class_8a", "period_key": "d2:p2", "teacher_id": "t2", "room_id": "r2"},
        ),
    )

    comp = _comparison((left, right))
    assert comp is not None
    assert comp.recommended_candidate_id is not None
    facts = [item for item in comp.explanation_facts if item.get("reason_code") == "candidate_difference"]
    assert facts
    assert "parallel_block_move" in facts[0].get("reason_codes", [])
