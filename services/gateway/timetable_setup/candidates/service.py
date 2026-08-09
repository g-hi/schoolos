from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from time import perf_counter
from typing import Any

from services.gateway.timetable_setup.candidates.contracts import (
    CandidateAttempt,
    CandidateComparison,
    CandidateGenerationOptions,
    CandidateGenerationResult,
    CandidatePairComparison,
    CandidateQualityComponent,
    ExplanationFact,
    TimetableCandidate,
)
from services.gateway.timetable_setup.scheduling_problem import ObjectiveRecord, SchedulingProblem
from services.gateway.timetable_setup.solver import SolveOptions, solve_scheduling_problem
from services.gateway.timetable_setup.solver.contracts import SolverAssignment, SolverResult


_PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "configured": {},
    "balanced": {},
    "preference_focused": {
        "teacher_preferences": "critical",
        "preference_fairness": "high",
        "minimize_teacher_gaps": "normal",
    },
    "compactness_focused": {
        "minimize_teacher_gaps": "critical",
        "workload_balance": "high",
        "subject_distribution": "normal",
    },
    "stability_focused": {
        "minimize_timetable_disruption": "critical",
        "preserve_existing_assignments": "critical",
        "teacher_preferences": "high",
    },
    "distribution_focused": {
        "subject_distribution": "critical",
        "workload_balance": "high",
        "teacher_preferences": "normal",
    },
}

_PRIORITY_WEIGHT = {
    "critical": 4.0,
    "high": 3.0,
    "normal": 2.0,
    "low": 1.0,
}


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_assignments(assignments: tuple[SolverAssignment, ...]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in sorted(
        assignments,
        key=lambda row: (
            row.class_id,
            row.day_key,
            row.period_key,
            row.occurrence_id,
            row.parallel_child_id or "",
            row.teacher_id or "",
            row.room_id or "",
        ),
    ):
        rows.append(
            {
                "occurrence_id": item.occurrence_id,
                "requirement_id": item.requirement_id,
                "class_id": item.class_id,
                "subject_id": item.subject_id,
                "day_key": item.day_key,
                "period_key": item.period_key,
                "teacher_id": item.teacher_id,
                "room_id": item.room_id,
                "parallel_block_id": item.parallel_block_id,
                "parallel_child_id": item.parallel_child_id,
                "fixed": item.fixed,
                "lock_state": item.lock_state,
                "periods_per_session": int(item.periods_per_session),
                "occupied_period_keys": list(item.occupied_period_keys),
            }
        )
    return tuple(rows)


def _normalize_class_facing(assignments: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    rows = [item for item in assignments if item.get("parallel_child_id") is None]
    rows.sort(key=lambda item: (item["class_id"], item["day_key"], item["period_key"], item["occurrence_id"]))
    return tuple(rows)


def _assignment_fingerprint(assignments: tuple[dict[str, Any], ...]) -> str:
    return _stable_hash(assignments)


def _candidate_id(problem_id: str, profile: str, assignment_fingerprint: str) -> str:
    seed = f"{problem_id}:{profile}:{assignment_fingerprint}"
    return f"cand_{_stable_hash(seed)[:16]}"


def _objective_priority_map(problem: SchedulingProblem) -> dict[str, str]:
    payload = {item.objective_key: item.priority_level for item in problem.optimization_objectives}
    return payload


def _apply_profile(problem: SchedulingProblem, profile: str) -> SchedulingProblem:
    overrides = _PROFILE_OVERRIDES.get(profile, {})
    if not overrides:
        return problem

    baseline = _objective_priority_map(problem)
    touched_keys = set(baseline.keys()) | set(overrides.keys())
    objective_rows = tuple(
        ObjectiveRecord(objective_key=key, priority_level=overrides.get(key, baseline.get(key, "normal")))
        for key in sorted(touched_keys)
    )
    return replace(problem, optimization_objectives=objective_rows)


def _quality_band(score: float | None) -> str:
    if score is None:
        return "unscored"
    if score >= 0.92:
        return "excellent"
    if score >= 0.80:
        return "good"
    if score >= 0.65:
        return "fair"
    return "poor"


def _preference_summary(result: SolverResult) -> dict[str, Any]:
    pref = next((item for item in result.objective_components if item.key == "teacher_preferences"), None)
    fairness = next((item for item in result.objective_components if item.key == "preference_fairness"), None)

    return {
        "score": pref.score if pref else None,
        "max_score": pref.max_score if pref else None,
        "priority": pref.priority if pref else None,
        "fairness_score": fairness.score if fairness else None,
        "fairness_max_score": fairness.max_score if fairness else None,
    }


def _quality_components(result: SolverResult) -> tuple[CandidateQualityComponent, ...]:
    rows: list[CandidateQualityComponent] = []
    for item in result.objective_components:
        rows.append(
            CandidateQualityComponent(
                key=item.key,
                score=float(item.score) if item.score is not None else None,
                max_score=float(item.max_score) if item.max_score is not None else None,
                weight=_PRIORITY_WEIGHT.get(item.priority, 1.0),
                priority=item.priority,
                status="ok" if (item.max_score or 0) == 0 or (item.score or 0) <= (item.max_score or 0) else "check",
                evidence=dict(item.details or {}),
            )
        )
    rows.sort(key=lambda row: (row.priority, row.key))
    return tuple(rows)


def _quality_score(components: tuple[CandidateQualityComponent, ...], *, feasible: bool) -> float | None:
    if not feasible:
        return None

    weighted_total = 0.0
    weighted_penalty = 0.0
    for row in components:
        max_score = float(row.max_score or 0.0)
        score = float(row.score or 0.0)
        weighted_total += row.weight * max_score
        weighted_penalty += row.weight * min(max_score, score)

    if weighted_total <= 0.0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (weighted_penalty / weighted_total)))


def _teacher_load_summary(assignments: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    load: dict[str, int] = {}
    for row in assignments:
        teacher_id = row.get("teacher_id")
        if not teacher_id:
            continue
        load[teacher_id] = load.get(teacher_id, 0) + len(row.get("occupied_period_keys") or [row.get("period_key")])

    if not load:
        return {"teacher_count": 0, "min": 0, "max": 0, "spread": 0}

    values = sorted(load.values())
    return {
        "teacher_count": len(values),
        "min": values[0],
        "max": values[-1],
        "spread": values[-1] - values[0],
    }


def _teacher_gap_summary(assignments: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    by_teacher_day: dict[tuple[str, str], list[int]] = {}
    for row in assignments:
        teacher_id = row.get("teacher_id")
        if not teacher_id:
            continue
        day = row.get("day_key")
        period = int(str(row.get("period_key")).split(":")[1][1:])
        by_teacher_day.setdefault((teacher_id, day), []).append(period)

    gap_count = 0
    for slots in by_teacher_day.values():
        values = sorted(set(slots))
        for index in range(1, len(values)):
            gap_count += max(0, values[index] - values[index - 1] - 1)

    return {
        "teacher_day_sequences": len(by_teacher_day),
        "gap_count": gap_count,
    }


def _subject_distribution_summary(assignments: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    by_class_subject_day: dict[tuple[str, str, str], int] = {}
    for row in assignments:
        subject_id = row.get("subject_id")
        if not subject_id:
            continue
        key = (row["class_id"], subject_id, row["day_key"])
        by_class_subject_day[key] = by_class_subject_day.get(key, 0) + 1

    max_daily = max(by_class_subject_day.values(), default=0)
    return {
        "tracked_buckets": len(by_class_subject_day),
        "max_daily_sessions_same_subject": max_daily,
    }


def _room_summary(assignments: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    room_usage: dict[str, int] = {}
    for row in assignments:
        room = row.get("room_id")
        if not room:
            continue
        room_usage[room] = room_usage.get(room, 0) + 1

    return {
        "rooms_used": len(room_usage),
        "max_room_sessions": max(room_usage.values(), default=0),
    }


def _repair_impact_summary(problem: SchedulingProblem, result: SolverResult) -> dict[str, Any]:
    if problem.generation_mode != "repair":
        return {"mode": problem.generation_mode, "baseline_supported": problem.baseline.supported, "change_count": None}

    if not problem.baseline.supported:
        return {
            "mode": problem.generation_mode,
            "baseline_supported": False,
            "status": "not_available",
            "reason": problem.baseline.reason,
            "unchanged": None,
            "changed": None,
            "moved_period": None,
            "teacher_change": None,
            "room_change": None,
            "affected_teacher_ids": tuple(),
            "affected_class_ids": tuple(),
            "affected_count": None,
        }

    baseline_map: dict[str, str] = {}
    for row in problem.baseline.assignments:
        key = str(row.get("occurrence_id"))
        period_key = row.get("period_key")
        if key and period_key:
            baseline_map[key] = period_key

    change_count = 0
    moved_period = 0
    teacher_change = 0
    room_change = 0
    affected_teachers: set[str] = set()
    affected_classes: set[str] = set()
    for row in result.assignments:
        occurrence_id = row.occurrence_id
        baseline_row = next((item for item in problem.baseline.assignments if str(item.get("occurrence_id")) == occurrence_id), None)
        if not baseline_row:
            continue

        changed = False
        if baseline_row.get("period_key") and baseline_row.get("period_key") != row.period_key:
            moved_period += 1
            changed = True
        if baseline_row.get("teacher_id") and baseline_row.get("teacher_id") != row.teacher_id:
            teacher_change += 1
            changed = True
            if row.teacher_id:
                affected_teachers.add(str(row.teacher_id))
        if baseline_row.get("room_id") and baseline_row.get("room_id") != row.room_id:
            room_change += 1
            changed = True

        if changed:
            change_count += 1
            affected_classes.add(str(row.class_id))

    return {
        "mode": problem.generation_mode,
        "baseline_supported": problem.baseline.supported,
        "baseline_assignment_count": len(baseline_map),
        "status": "available",
        "unchanged": max(0, len(baseline_map) - change_count),
        "changed": change_count,
        "moved_period": moved_period,
        "teacher_change": teacher_change,
        "room_change": room_change,
        "affected_teacher_ids": tuple(sorted(affected_teachers)),
        "affected_class_ids": tuple(sorted(affected_classes)),
        "affected_count": len(affected_classes),
        "change_count": change_count,
    }


def _metrics_payload(result: SolverResult, *, deterministic: bool) -> dict[str, Any]:
    payload = asdict(result.metrics)
    if deterministic:
        payload["runtime_ms"] = 0
    payload["objective_score"] = result.objective_score
    return payload


def _facts_from_solver(result: SolverResult, *, candidate_id: str) -> tuple[ExplanationFact, ...]:
    rows: list[ExplanationFact] = []

    for diag in result.diagnostics:
        rows.append(
            ExplanationFact(
                reason_code=diag.code,
                entity_type=diag.entity_type,
                entity_id=diag.entity_id,
                metric=None,
                expected=None,
                actual=None,
                related_candidate_id=candidate_id,
                evidence=dict(diag.details or {}),
            )
        )

    for item in result.objective_components:
        rows.append(
            ExplanationFact(
                reason_code=f"objective_{item.key}",
                entity_type="objective_component",
                entity_id=item.key,
                metric="penalty",
                expected=item.max_score,
                actual=item.score,
                related_candidate_id=candidate_id,
                evidence={"priority": item.priority, **dict(item.details or {})},
            )
        )

        if item.key == "teacher_preferences":
            rows.append(
                ExplanationFact(
                    reason_code="preference_satisfied" if int(item.score or 0) == 0 else "preference_unsatisfied",
                    entity_type="preference_summary",
                    entity_id=item.key,
                    metric="penalty",
                    expected=0,
                    actual=item.score,
                    related_candidate_id=candidate_id,
                    evidence={"priority": item.priority},
                )
            )

    rows.sort(key=lambda row: (row.reason_code, row.entity_type or "", row.entity_id or ""))
    return tuple(rows)


def _candidate_from_solver(problem: SchedulingProblem, profile: str, result: SolverResult, *, include_explanations: bool, deterministic: bool) -> TimetableCandidate:
    assignments = _normalize_assignments(result.assignments)
    class_rows = _normalize_class_facing(assignments)
    assignment_fp = _assignment_fingerprint(assignments)
    cid = _candidate_id(problem.problem_id, profile, assignment_fp)

    components = _quality_components(result)
    score = _quality_score(components, feasible=result.feasible)

    return TimetableCandidate(
        candidate_id=cid,
        problem_id=problem.problem_id,
        problem_fingerprint=problem.source_fingerprint,
        generation_configuration_id=problem.generation_configuration_id,
        generation_mode=problem.generation_mode,
        candidate_profile=profile,
        assignment_fingerprint=assignment_fp,
        solver_status=result.status,
        feasible=result.feasible,
        optimal=result.optimal,
        assignments=assignments,
        class_facing_assignments=class_rows,
        metrics=_metrics_payload(result, deterministic=deterministic),
        quality_score=score,
        quality_band=_quality_band(score),
        quality_components=components,
        preference_summary=_preference_summary(result),
        fairness_summary={
            "teacher_gap_count": result.metrics.teacher_gap_count,
        },
        workload_summary=_teacher_load_summary(assignments),
        gap_summary=_teacher_gap_summary(assignments),
        subject_distribution_summary=_subject_distribution_summary(assignments),
        room_summary=_room_summary(assignments),
        repair_impact_summary=_repair_impact_summary(problem, result),
        hard_constraint_summary=dict(result.hard_constraint_summary or {}),
        diagnostics=tuple(asdict(item) for item in result.diagnostics),
        explanation_facts=_facts_from_solver(result, candidate_id=cid) if include_explanations else tuple(),
        warnings=tuple(asdict(item) for item in result.warnings),
        solver_runtime_ms=0 if deterministic else int(result.metrics.runtime_ms),
        solver_statistics=dict(result.solver_statistics or {}),
        provenance={
            "source": "phase_10c_batch4_transient",
            "profile": profile,
            "deterministic": True,
        },
    )


def _assignment_index(candidate: TimetableCandidate) -> dict[str, dict[str, Any]]:
    return {
        f"{item['occurrence_id']}|{item.get('parallel_child_id') or ''}": item
        for item in candidate.assignments
    }


def _class_facing_index(candidate: TimetableCandidate) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for item in candidate.assignments:
        parallel_block_id = item.get("parallel_block_id")
        if parallel_block_id:
            key = f"parallel_block:{parallel_block_id}"
            payload[key] = {
                "key": key,
                "class_id": item.get("class_id"),
                "period_key": item.get("period_key"),
                "teacher_id": None,
                "room_id": None,
                "kind": "parallel_block",
            }
            continue

        key = f"occurrence:{item['occurrence_id']}"
        payload[key] = {
            "key": key,
            "class_id": item.get("class_id"),
            "period_key": item.get("period_key"),
            "teacher_id": item.get("teacher_id"),
            "room_id": item.get("room_id"),
            "kind": "occurrence",
        }
    return payload


def _pairwise(left: TimetableCandidate, right: TimetableCandidate) -> CandidatePairComparison:
    left_ix = _assignment_index(left)
    right_ix = _assignment_index(right)

    keys = sorted(set(left_ix.keys()) | set(right_ix.keys()))
    differences: list[dict[str, Any]] = []
    for key in keys:
        a = left_ix.get(key)
        b = right_ix.get(key)
        if a is None or b is None:
            differences.append({"kind": "missing", "assignment_key": key})
            continue
        changed: dict[str, Any] = {}
        for field in ("period_key", "teacher_id", "room_id"):
            if a.get(field) != b.get(field):
                changed[field] = {"left": a.get(field), "right": b.get(field)}
        if changed:
            differences.append({"kind": "changed", "assignment_key": key, "fields": changed})

    class_left = _class_facing_index(left)
    class_right = _class_facing_index(right)
    class_keys = sorted(set(class_left.keys()) | set(class_right.keys()))
    class_differences: list[dict[str, Any]] = []
    for key in class_keys:
        a = class_left.get(key)
        b = class_right.get(key)
        if a is None or b is None:
            class_differences.append({"kind": "missing", "class_key": key})
            continue
        changed: dict[str, Any] = {}
        for field in ("period_key", "teacher_id", "room_id"):
            if a.get(field) != b.get(field):
                changed[field] = {"left": a.get(field), "right": b.get(field)}
        if changed:
            class_differences.append({"kind": "changed", "class_key": key, "fields": changed, "class_id": a.get("class_id"), "kind_label": a.get("kind")})

    base = max(len(left.assignments), len(right.assignments), 1)
    delta = {
        "quality_score": None if left.quality_score is None or right.quality_score is None else round(float(left.quality_score) - float(right.quality_score), 6),
        "objective_score": (left.metrics.get("objective_score") or 0) - (right.metrics.get("objective_score") or 0),
        "teacher_gap_count": (left.metrics.get("teacher_gap_count") or 0) - (right.metrics.get("teacher_gap_count") or 0),
    }

    reason_codes: list[str] = []
    if delta["quality_score"] is not None:
        if delta["quality_score"] > 0:
            reason_codes.append("higher_quality_score")
        elif delta["quality_score"] < 0:
            reason_codes.append("lower_quality_score")
    if differences:
        reason_codes.append("assignment_difference")
    if class_differences:
        reason_codes.append("class_facing_difference")

    for entry in differences:
        fields = entry.get("fields", {}) if isinstance(entry, dict) else {}
        if "period_key" in fields:
            reason_codes.append("period_move")
        if "teacher_id" in fields:
            reason_codes.append("teacher_change")
        if "room_id" in fields:
            reason_codes.append("room_change")
    if any((entry.get("kind_label") == "parallel_block") for entry in class_differences if isinstance(entry, dict)):
        reason_codes.append("parallel_block_move")

    reason_codes = sorted(set(reason_codes))

    relation = "equivalent" if not differences and (delta["quality_score"] == 0 or delta["quality_score"] is None) else "different"

    return CandidatePairComparison(
        left_candidate_id=left.candidate_id,
        right_candidate_id=right.candidate_id,
        relation=relation,
        assignment_difference_count=len(differences),
        assignment_difference_ratio=round(len(differences) / base, 6),
        differences=tuple(differences),
        class_facing_differences=tuple(class_differences),
        metric_deltas={
            **delta,
            "class_facing_difference_count": len(class_differences),
            "class_facing_difference_ratio": round(len(class_differences) / max(len(class_left), len(class_right), 1), 6),
        },
        reason_codes=tuple(reason_codes),
    )


def _comparison(candidates: tuple[TimetableCandidate, ...]) -> CandidateComparison | None:
    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda row: (
            row.feasible,
            row.quality_score if row.quality_score is not None else -1.0,
            row.candidate_profile == "configured",
            row.candidate_id,
        ),
        reverse=True,
    )
    winner = ranked[0]

    explanation_facts: list[dict[str, Any]] = []
    if len(ranked) > 1:
        second = ranked[1]
        win_quality = winner.quality_score if winner.quality_score is not None else -1.0
        second_quality = second.quality_score if second.quality_score is not None else -1.0
        win_gap = int(winner.metrics.get("teacher_gap_count") or 0)
        second_gap = int(second.metrics.get("teacher_gap_count") or 0)

        # Trade-off: better quality but worse gaps (or vice versa) means no universal winner.
        if (win_quality > second_quality and win_gap > second_gap) or (win_quality < second_quality and win_gap < second_gap):
            explanation_facts.append(
                {
                    "reason_code": "gap_preference_tradeoff",
                    "left_candidate_id": winner.candidate_id,
                    "right_candidate_id": second.candidate_id,
                    "left_quality_score": winner.quality_score,
                    "right_quality_score": second.quality_score,
                    "left_teacher_gap_count": win_gap,
                    "right_teacher_gap_count": second_gap,
                }
            )
            return CandidateComparison(
                recommended_candidate_id=None,
                recommendation_reason_codes=("tradeoff_no_universal_winner",),
                pairwise=tuple(_pairwise(left, right) for index, left in enumerate(candidates) for right in candidates[index + 1 :]),
                explanation_facts=tuple(explanation_facts),
            )

    reason_codes = []
    if winner.feasible:
        reason_codes.append("feasible_preferred")
    if winner.quality_score is not None:
        reason_codes.append("highest_quality_score")

    pairs: list[CandidatePairComparison] = []
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            pair = _pairwise(left, right)
            pairs.append(pair)
            if pair.assignment_difference_count > 0 or int(pair.metric_deltas.get("class_facing_difference_count", 0)) > 0:
                explanation_facts.append(
                    {
                        "reason_code": "candidate_difference",
                        "left_candidate_id": pair.left_candidate_id,
                        "right_candidate_id": pair.right_candidate_id,
                        "assignment_difference_count": pair.assignment_difference_count,
                        "class_facing_difference_count": pair.metric_deltas.get("class_facing_difference_count", 0),
                        "reason_codes": list(pair.reason_codes),
                    }
                )

    return CandidateComparison(
        recommended_candidate_id=winner.candidate_id,
        recommendation_reason_codes=tuple(reason_codes),
        pairwise=tuple(pairs),
        explanation_facts=tuple(explanation_facts),
    )


def _profile_order(options: CandidateGenerationOptions) -> tuple[str, ...]:
    unique: list[str] = []
    for item in options.candidate_profiles:
        if item in _PROFILE_OVERRIDES and item not in unique:
            unique.append(item)
    if "configured" not in unique:
        unique.insert(0, "configured")
    return tuple(unique)


def generate_timetable_candidates(
    problem: SchedulingProblem,
    *,
    options: CandidateGenerationOptions,
) -> CandidateGenerationResult:
    started = perf_counter()
    opts = options.normalized()

    profiles = _profile_order(opts)
    profile_count = min(opts.candidate_count, len(profiles))

    attempts: list[CandidateAttempt] = []
    accepted: list[TimetableCandidate] = []
    dedupe: set[str] = set()

    for index in range(profile_count):
        profile = profiles[index]
        profile_problem = _apply_profile(problem, profile)

        solve_options = SolveOptions(
            max_time_seconds=opts.max_solver_time_seconds,
            deterministic_mode=True,
            random_seed=42 + index,
            num_search_workers=1,
            log_search_progress=False,
            stop_after_first_feasible=False,
        )

        result = solve_scheduling_problem(profile_problem, solve_options)
        candidate: TimetableCandidate | None = None
        status = "rejected"
        assignment_fingerprint: str | None = None
        candidate_id: str | None = None

        if result.feasible:
            candidate = _candidate_from_solver(
                profile_problem,
                profile,
                result,
                include_explanations=opts.include_explanation_facts,
                deterministic=opts.deterministic,
            )
            assignment_fingerprint = candidate.assignment_fingerprint
            duplicate = assignment_fingerprint in dedupe
            if duplicate:
                status = "duplicate_solution"
            else:
                status = "accepted"
                dedupe.add(assignment_fingerprint)
                accepted.append(candidate)
                candidate_id = candidate.candidate_id
        else:
            status = "no_feasible_solution"

        attempts.append(
            CandidateAttempt(
                profile=profile,
                status=status,
                solver_status=result.status,
                runtime_ms=0 if opts.deterministic else int(result.metrics.runtime_ms),
                candidate_id=candidate_id,
                assignment_fingerprint=assignment_fingerprint,
                diagnostics=tuple(asdict(item) for item in result.diagnostics),
                warnings=tuple(asdict(item) for item in result.warnings),
            )
        )

    accepted.sort(key=lambda row: row.candidate_id)
    candidates = tuple(accepted)

    warnings: list[dict[str, Any]] = []
    if len(candidates) < opts.candidate_count:
        warnings.append(
            {
                "code": "candidate_count_not_reached",
                "message": "Requested candidate count could not be reached due to deduplication or profile limits.",
                "requested": opts.candidate_count,
                "generated": len(candidates),
            }
        )
    if attempts and all(item.status == "duplicate_solution" for item in attempts):
        warnings.append(
            {
                "code": "no_distinct_alternative",
                "message": "All generated feasible candidates were equivalent duplicates.",
            }
        )

    comparison = _comparison(candidates) if opts.include_comparison else None

    diagnostics: list[dict[str, Any]] = []
    if not candidates:
        diagnostics.append(
            {
                "code": "no_candidate_generated",
                "message": "No candidate timetable was generated.",
                "severity": "blocker",
            }
        )
    for attempt in attempts:
        diagnostics.extend(attempt.diagnostics)

    elapsed_ms = 0 if opts.deterministic else int((perf_counter() - started) * 1000)
    return CandidateGenerationResult(
        problem_id=problem.problem_id,
        problem_fingerprint=problem.source_fingerprint,
        requested_count=opts.candidate_count,
        generated_count=len(candidates),
        candidates=candidates,
        comparison=comparison,
        attempts=tuple(attempts),
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        duration_ms=elapsed_ms,
        deterministic=opts.deterministic,
        provenance={
            "source": "phase_10c_batch4_transient",
            "persistence": "none",
            "timetable_version_created": False,
            "candidate_published": False,
        },
    )
