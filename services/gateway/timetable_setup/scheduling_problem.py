from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ProblemIssue:
    code: str
    message: str
    severity: str
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    valid: bool
    blocker_count: int
    warning_count: int
    excluded_record_count: int
    blockers: tuple[ProblemIssue, ...]
    warnings: tuple[ProblemIssue, ...]
    exclusions: tuple[ProblemIssue, ...]
    source_summary: dict[str, Any]
    build_coverage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LogicalPeriod:
    key: str
    day_of_week: int
    period_number: int
    is_teaching_period: bool
    label: str
    starts_at: str | None
    ends_at: str | None
    duration_minutes: int | None


@dataclass(frozen=True, slots=True)
class TeacherProblemRecord:
    teacher_id: str
    user_id: str
    active: bool
    max_weekly_hours: int
    eligible_subject_ids: tuple[str, ...]
    weekly_load_limit_sessions: int | None
    daily_load_limit_sessions: int | None
    consecutive_session_limit: int | None
    available_period_keys: tuple[str, ...]
    unavailable_period_keys: tuple[str, ...]
    campus_id: str | None
    fixed_assignment_requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassProblemRecord:
    class_id: str
    code: str | None
    grade_reference: str
    active: bool
    campus_id: str | None
    schedulable_period_keys: tuple[str, ...]
    unavailable_period_keys: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    fixed_session_ids: tuple[str, ...]
    parallel_block_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubjectProblemRecord:
    subject_id: str
    code: str
    name: str
    required_weekly_sessions: int | None
    required_weekly_minutes: int | None
    min_daily_sessions: int | None
    max_daily_sessions: int | None
    room_requirements: tuple[str, ...]
    teacher_eligibility_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoomProblemRecord:
    room_id: str
    room_code: str
    room_name: str
    room_type: str
    capacity: int
    campus_id: str | None
    specialist_capabilities: tuple[str, ...]
    available_period_keys: tuple[str, ...]
    unavailable_period_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeachingRequirementRecord:
    requirement_id: str
    class_id: str
    subject_id: str
    teacher_id: str | None
    eligible_teacher_ids: tuple[str, ...]
    weekly_sessions: int
    weekly_minutes: int
    periods_per_session: int
    min_daily_sessions: int
    max_daily_sessions: int
    specialist_room_type: str | None
    preferred_period_numbers: tuple[int, ...]
    forbidden_period_numbers: tuple[int, ...]
    fixed_session_rule_indexes: tuple[int, ...]
    source_type: str


@dataclass(frozen=True, slots=True)
class FixedSessionRecord:
    fixed_session_id: str
    requirement_id: str
    class_id: str
    subject_id: str
    teacher_id: str | None
    room_id: str | None
    day_of_week: int
    period_number: int
    period_key: str
    enforcement_source: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PolicyConstraintRecord:
    constraint_id: str
    policy_set_id: str | None
    constraint_type: str
    category: str
    enforcement: str
    scope_type: str
    scope_reference_id: str | None
    scope_reference_code: str | None
    parameters: dict[str, Any]
    priority: int
    weight: float
    lifecycle_status: str
    exception_applied: bool


@dataclass(frozen=True, slots=True)
class TeacherPreferenceRecord:
    preference_id: str
    teacher_id: str
    preference_type: str
    strength: str
    weekday_values: tuple[int, ...]
    period_numbers: tuple[int, ...]
    effective_start_date: str | None
    effective_end_date: str | None
    source_type: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GenerationOverrideRecord:
    override_id: str
    configuration_id: str
    override_type: str
    strength: str
    scope_type: str
    scope_reference_id: str | None
    scope_reference_code: str | None
    payload: dict[str, Any]
    source_type: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LockRecord:
    lock_id: str
    configuration_id: str
    lock_state: str
    target_type: str
    target_reference_id: str | None
    target_reference_code: str | None
    day_of_week: int | None
    period_number: int | None
    period_end_number: int | None
    is_manual_hard_lock: bool
    source_type: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParallelChildRecord:
    child_id: str
    requirement_id: str | None
    subject_id: str | None
    teacher_id: str | None
    room_id: str | None
    sequence_order: int | None
    requirement: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParallelBlockRecord:
    block_id: str
    class_id: str
    display_label: str
    block_type: str
    synchronization_requirement: str
    active: bool
    source_type: str
    provenance: dict[str, Any]
    children: tuple[ParallelChildRecord, ...]


@dataclass(frozen=True, slots=True)
class BaselineSummary:
    supported: bool
    reason: str
    baseline_reference_type: str | None
    baseline_reference_id: str | None
    assignments: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ObjectiveRecord:
    objective_key: str
    priority_level: str


@dataclass(frozen=True, slots=True)
class SchedulingProblem:
    problem_id: str
    schema_version: str
    tenant_id: str
    academic_year_id: str
    term_id: str
    campus_id: str | None
    generation_configuration_id: str
    generation_mode: str
    built_at: datetime
    source_fingerprint: str
    source_revision: str
    school_week: dict[str, Any]
    logical_periods: tuple[LogicalPeriod, ...]
    bell_schedule_reference: dict[str, Any]
    teachers: tuple[TeacherProblemRecord, ...]
    classes: tuple[ClassProblemRecord, ...]
    subjects: tuple[SubjectProblemRecord, ...]
    rooms: tuple[RoomProblemRecord, ...]
    teaching_requirements: tuple[TeachingRequirementRecord, ...]
    fixed_sessions: tuple[FixedSessionRecord, ...]
    teacher_availability: dict[str, tuple[str, ...]]
    room_availability: dict[str, tuple[str, ...]]
    teacher_eligibility: dict[str, tuple[str, ...]]
    room_requirements: dict[str, tuple[str, ...]]
    policy_constraints: tuple[PolicyConstraintRecord, ...]
    teacher_preferences: tuple[TeacherPreferenceRecord, ...]
    generation_overrides: tuple[GenerationOverrideRecord, ...]
    locks: tuple[LockRecord, ...]
    parallel_lesson_blocks: tuple[ParallelBlockRecord, ...]
    baseline: BaselineSummary
    repair_scope: dict[str, Any]
    stability_mode: str
    optimization_objectives: tuple[ObjectiveRecord, ...]
    warnings: tuple[ProblemIssue, ...]
    exclusions: tuple[ProblemIssue, ...]
    provenance: dict[str, Any]
    validation_summary: ValidationSummary
    solver_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["built_at"] = self.built_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class SchedulingProblemBuildResult:
    problem: SchedulingProblem
    validation: ValidationSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem.to_dict(),
            "validation": asdict(self.validation),
            "solver_eligible": self.problem.solver_eligible,
        }
