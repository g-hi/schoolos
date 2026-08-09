from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


_ALLOWED_PROFILES = (
    "configured",
    "balanced",
    "preference_focused",
    "compactness_focused",
    "stability_focused",
    "distribution_focused",
)


@dataclass(frozen=True, slots=True)
class CandidateGenerationOptions:
    candidate_count: int = 1
    max_solver_time_seconds: float = 8.0
    deterministic: bool = True
    candidate_profiles: tuple[str, ...] = tuple()
    include_comparison: bool = True
    include_explanation_facts: bool = True
    response_mode: str = "summary"

    def normalized(self) -> CandidateGenerationOptions:
        count = max(1, min(5, int(self.candidate_count)))
        seconds = float(max(0.1, min(30.0, self.max_solver_time_seconds)))

        profiles = tuple(item for item in self.candidate_profiles if item in _ALLOWED_PROFILES)
        if not profiles:
            profiles = ("configured",)

        mode = self.response_mode if self.response_mode in {"summary", "detailed"} else "summary"

        return CandidateGenerationOptions(
            candidate_count=count,
            max_solver_time_seconds=seconds,
            deterministic=bool(self.deterministic),
            candidate_profiles=profiles,
            include_comparison=bool(self.include_comparison),
            include_explanation_facts=bool(self.include_explanation_facts),
            response_mode=mode,
        )


@dataclass(frozen=True, slots=True)
class CandidateQualityComponent:
    key: str
    score: float | None
    max_score: float | None
    weight: float
    priority: str
    status: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExplanationFact:
    reason_code: str
    entity_type: str | None
    entity_id: str | None
    metric: str | None
    expected: Any
    actual: Any
    related_constraint_id: str | None = None
    related_preference_id: str | None = None
    related_candidate_id: str | None = None
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TimetableCandidate:
    candidate_id: str
    problem_id: str
    problem_fingerprint: str
    generation_configuration_id: str
    generation_mode: str
    candidate_profile: str
    assignment_fingerprint: str
    solver_status: str
    feasible: bool
    optimal: bool
    assignments: tuple[dict[str, Any], ...]
    class_facing_assignments: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]
    quality_score: float | None
    quality_band: str
    quality_components: tuple[CandidateQualityComponent, ...]
    preference_summary: dict[str, Any]
    fairness_summary: dict[str, Any]
    workload_summary: dict[str, Any]
    gap_summary: dict[str, Any]
    subject_distribution_summary: dict[str, Any]
    room_summary: dict[str, Any]
    repair_impact_summary: dict[str, Any]
    hard_constraint_summary: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...]
    explanation_facts: tuple[ExplanationFact, ...]
    warnings: tuple[dict[str, Any], ...]
    solver_runtime_ms: int
    solver_statistics: dict[str, Any]
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CandidateAttempt:
    profile: str
    status: str
    solver_status: str
    runtime_ms: int
    candidate_id: str | None
    assignment_fingerprint: str | None
    diagnostics: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CandidatePairComparison:
    left_candidate_id: str
    right_candidate_id: str
    relation: str
    assignment_difference_count: int
    assignment_difference_ratio: float
    differences: tuple[dict[str, Any], ...]
    class_facing_differences: tuple[dict[str, Any], ...]
    metric_deltas: dict[str, Any]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    recommended_candidate_id: str | None
    recommendation_reason_codes: tuple[str, ...]
    pairwise: tuple[CandidatePairComparison, ...]
    explanation_facts: tuple[dict[str, Any], ...] = tuple()


@dataclass(frozen=True, slots=True)
class CandidateGenerationResult:
    problem_id: str
    problem_fingerprint: str
    requested_count: int
    generated_count: int
    candidates: tuple[TimetableCandidate, ...]
    comparison: CandidateComparison | None
    attempts: tuple[CandidateAttempt, ...]
    warnings: tuple[dict[str, Any], ...]
    diagnostics: tuple[dict[str, Any], ...]
    duration_ms: int
    deterministic: bool
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [
            {
                **asdict(candidate),
                "quality_components": [asdict(item) for item in candidate.quality_components],
                "explanation_facts": [asdict(item) for item in candidate.explanation_facts],
            }
            for candidate in self.candidates
        ]
        return payload
