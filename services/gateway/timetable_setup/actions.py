from __future__ import annotations

import uuid
from datetime import date as date_type

from shared.db.models import (
    BellSchedule,
    OperationalCalendarEvent,
    TeachingRoom,
    WeeklyTeachingRequirement,
)


# Agent-safe proposal contracts: these create candidate records only.
# Approval is an explicit leadership action and is never implicit.

def propose_calendar_entry(*, tenant_id: uuid.UUID, actor_id: uuid.UUID, payload: dict) -> OperationalCalendarEvent:
    return OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        academic_year_id=payload.get("academic_year_id"),
        term_id=payload.get("term_id"),
        event_name=payload["event_name"],
        description=payload.get("description"),
        start_date=payload["start_date"],
        end_date=payload["end_date"],
        is_all_day=payload.get("is_all_day", True),
        event_type=payload["event_type"],
        teaching_day_effect=payload.get("teaching_day_effect", "no_change"),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        source_reference=payload.get("source_reference"),
        import_batch_id=payload.get("import_batch_id"),
        original_source_text=payload.get("original_source_text"),
        created_by_user_id=actor_id,
        reviewed_by_user_id=None,
        approved_by_user_id=None,
        is_active=True,
    )


def propose_bell_schedule(*, tenant_id: uuid.UUID, actor_id: uuid.UUID, payload: dict) -> BellSchedule:
    return BellSchedule(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        academic_year_id=payload.get("academic_year_id"),
        term_id=payload.get("term_id"),
        school_week_config_id=payload.get("school_week_config_id"),
        name=payload["name"],
        schedule_type=payload.get("schedule_type", "normal"),
        effective_start_date=payload.get("effective_start_date"),
        effective_end_date=payload.get("effective_end_date"),
        is_default=payload.get("is_default", False),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
        created_by_user_id=actor_id,
        approved_by_user_id=None,
    )


def propose_room_mapping(*, tenant_id: uuid.UUID, payload: dict) -> TeachingRoom:
    return TeachingRoom(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        room_code=payload["room_code"],
        room_name=payload["room_name"],
        room_type=payload["room_type"],
        capacity=payload.get("capacity", 0),
        floor_or_location=payload.get("floor_or_location"),
        specialist_capabilities=payload.get("specialist_capabilities", []),
        accessibility_notes=payload.get("accessibility_notes"),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
    )


def propose_teaching_requirement(*, tenant_id: uuid.UUID, payload: dict) -> WeeklyTeachingRequirement:
    return WeeklyTeachingRequirement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload["campus_id"],
        academic_year_id=payload["academic_year_id"],
        term_id=payload["term_id"],
        class_id=payload["class_id"],
        subject_id=payload["subject_id"],
        teacher_id=payload.get("teacher_id"),
        sessions_per_week=payload["sessions_per_week"],
        periods_per_session=payload.get("periods_per_session", 1),
        min_daily_sessions=payload.get("min_daily_sessions", 0),
        max_daily_sessions=payload.get("max_daily_sessions", 3),
        double_period_mode=payload.get("double_period_mode", "none"),
        specialist_room_type=payload.get("specialist_room_type"),
        preferred_period_numbers=payload.get("preferred_period_numbers", []),
        forbidden_period_numbers=payload.get("forbidden_period_numbers", []),
        has_fixed_sessions=payload.get("has_fixed_sessions", False),
        fixed_session_rules=payload.get("fixed_session_rules", []),
        priority=payload.get("priority", 100),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
    )


def run_timetable_readiness(*, checked_at: date_type | None = None) -> dict:
    return {
        "action": "run_timetable_readiness",
        "checked_at": checked_at,
        "note": "Invoke services.gateway.timetable_setup.readiness.compute_timetable_input_readiness with tenant-scoped DB session.",
    }


def inspect_workbook(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "inspect_workbook",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Read-only inspection of workbook summary, sheets, mappings and diagnostics.",
    }


def propose_sheet_mappings(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "propose_sheet_mappings",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Produce deterministic mapping suggestions only; does not confirm or persist approvals.",
    }


def propose_column_mappings(*, batch_id: uuid.UUID, sheet_name: str) -> dict:
    return {
        "action": "propose_column_mappings",
        "batch_id": str(batch_id),
        "sheet_name": sheet_name,
        "safe": True,
        "note": "Suggest column mappings and confidence metadata only.",
    }


def explain_workbook_diagnostics(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "explain_workbook_diagnostics",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Summarizes blockers/warnings/information without changing commit state.",
    }


def validate_workbook(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "validate_workbook",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Runs deterministic validation checks only.",
    }


def summarize_commit_plan(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "summarize_commit_plan",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Produces expected create/update/unchanged/rejected counts before approval.",
    }


def get_setup_centre_summary() -> dict:
    return {
        "action": "get_setup_centre_summary",
        "safe": True,
        "note": "Read-only unified timetable setup summary.",
    }


def inspect_policy_diagnostics() -> dict:
    return {
        "action": "inspect_policy_diagnostics",
        "safe": True,
        "note": "Read-only timetable policy diagnostics summary.",
    }


def explain_policy_conflicts() -> dict:
    return {
        "action": "explain_policy_conflicts",
        "safe": True,
        "note": "Read-only conflict inspection for active and reviewable timetable policy scopes.",
    }


def analyze_policy_feasibility() -> dict:
    return {
        "action": "analyze_policy_feasibility",
        "safe": True,
        "note": "Read-only feasibility diagnostics for timetable policies and weekly requirements.",
    }


def summarize_policy_impact() -> dict:
    return {
        "action": "summarize_policy_impact",
        "safe": True,
        "note": "Read-only impact analysis for timetable policy scopes.",
    }


def recommend_policy_resolution() -> dict:
    return {
        "action": "recommend_policy_resolution",
        "safe": True,
        "note": "Read-only resolution guidance for timetable policy conflicts and feasibility issues.",
    }


def inspect_policy_readiness() -> dict:
    return {
        "action": "inspect_policy_readiness",
        "safe": True,
        "note": "Read-only timetable policy readiness gate summary.",
    }


def inspect_effective_policy() -> dict:
    return {
        "action": "inspect_effective_policy",
        "safe": True,
        "note": "Read-only effective policy-set resolution for scheduling authorization.",
    }


def inspect_effective_constraints() -> dict:
    return {
        "action": "inspect_effective_constraints",
        "safe": True,
        "note": "Read-only effective constraint resolution for the selected timetable policy.",
    }


def inspect_scheduling_authorization() -> dict:
    return {
        "action": "inspect_scheduling_authorization",
        "safe": True,
        "note": "Read-only authorization gate that explains whether scheduling may proceed.",
    }


def get_setup_steps() -> dict:
    return {
        "action": "get_setup_steps",
        "safe": True,
        "note": "Read-only step registry and progress overview.",
    }


def get_setup_step_detail(*, step_key: str) -> dict:
    return {
        "action": "get_setup_step_detail",
        "step_key": step_key,
        "safe": True,
        "note": "Read-only step details including blockers, counts, and policy rules.",
    }


def get_unified_setup_issues() -> dict:
    return {
        "action": "get_unified_setup_issues",
        "safe": True,
        "note": "Read-only issue aggregation across timetable setup.",
    }


def get_pending_setup_approvals() -> dict:
    return {
        "action": "get_pending_setup_approvals",
        "safe": True,
        "note": "Read-only pending approval queue.",
    }


def get_recent_setup_activity() -> dict:
    return {
        "action": "get_recent_setup_activity",
        "safe": True,
        "note": "Read-only recent activity feed.",
    }


def explain_setup_progress() -> dict:
    return {
        "action": "explain_setup_progress",
        "safe": True,
        "note": "Explains weighted progress and applicable steps without making decisions.",
    }


def explain_generation_readiness() -> dict:
    return {
        "action": "explain_generation_readiness",
        "safe": True,
        "note": "Explains why generation is or is not allowed.",
    }


def recommend_next_setup_action() -> dict:
    return {
        "action": "recommend_next_setup_action",
        "safe": True,
        "note": "Proposes the best next setup step without changing state.",
    }


def propose_issue_resolution_plan(*, issue_key: str) -> dict:
    return {
        "action": "propose_issue_resolution_plan",
        "issue_key": issue_key,
        "safe": True,
        "note": "Suggests a deterministic resolution plan only.",
    }


def propose_setup_sequence() -> dict:
    return {
        "action": "propose_setup_sequence",
        "safe": True,
        "note": "Suggests an ordered setup sequence only.",
    }


def summarize_pending_reviews() -> dict:
    return {
        "action": "summarize_pending_reviews",
        "safe": True,
        "note": "Summarizes pending reviews without approving anything.",
    }


def summarize_import_status() -> dict:
    return {
        "action": "summarize_import_status",
        "safe": True,
        "note": "Summarizes workbook and PDF import states without committing.",
    }


def list_policy_sets() -> dict:
    return {"action": "list_policy_sets", "safe": True, "note": "Read-only policy set listing."}


def get_policy_set(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "get_policy_set", "policy_set_id": str(policy_set_id), "safe": True}


def list_constraints(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "list_constraints", "policy_set_id": str(policy_set_id), "safe": True}


def inspect_timetable_version(*, version_id: uuid.UUID) -> dict:
    return {
        "action": "inspect_timetable_version",
        "version_id": str(version_id),
        "safe": True,
        "note": "Read-only timetable version details and immutable assignment snapshot metadata.",
    }


def list_timetable_versions(*, timetable_id: uuid.UUID) -> dict:
    return {
        "action": "list_timetable_versions",
        "timetable_id": str(timetable_id),
        "safe": True,
        "note": "Read-only list of timetable versions with lifecycle and effective-date summaries.",
    }


def explain_version_diff(*, left_version_id: uuid.UUID, right_version_id: uuid.UUID) -> dict:
    return {
        "action": "explain_version_diff",
        "left_version_id": str(left_version_id),
        "right_version_id": str(right_version_id),
        "safe": True,
        "note": "Read-only canonical occurrence diff summary and explainability payload.",
    }


def explain_repair_impact(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_repair_impact",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only repair impact preview classification.",
    }


def inspect_effective_timetable_version(*, timetable_id: uuid.UUID, on_date: date_type) -> dict:
    return {
        "action": "inspect_effective_timetable_version",
        "timetable_id": str(timetable_id),
        "on_date": on_date.isoformat(),
        "safe": True,
        "note": "Read-only effective-date timetable version resolution.",
    }


def explain_supersession(*, version_id: uuid.UUID) -> dict:
    return {
        "action": "explain_supersession",
        "version_id": str(version_id),
        "safe": True,
        "note": "Read-only supersession chain and effective-window explanation.",
    }


def explain_publication_readiness(*, version_id: uuid.UUID) -> dict:
    return {
        "action": "explain_publication_readiness",
        "version_id": str(version_id),
        "safe": True,
        "note": "Read-only publication readiness checks; no operational state changes.",
    }


def propose_repair_scope_expansion(*, configuration_id: uuid.UUID, from_scope: str, to_scope: str) -> dict:
    return {
        "action": "propose_repair_scope_expansion",
        "configuration_id": str(configuration_id),
        "from_scope": from_scope,
        "to_scope": to_scope,
        "safe": True,
        "note": "Proposal only. Scope expansion requires explicit human approval.",
    }


def propose_candidate_for_review(*, version_id: uuid.UUID) -> dict:
    return {
        "action": "propose_candidate_for_review",
        "version_id": str(version_id),
        "safe": True,
        "note": "Proposal only. Submission remains a human workflow action.",
    }


def propose_effective_date(*, version_id: uuid.UUID, effective_from: date_type) -> dict:
    return {
        "action": "propose_effective_date",
        "version_id": str(version_id),
        "effective_from": effective_from.isoformat(),
        "safe": True,
        "note": "Proposal only. Publication remains principal-authorized.",
    }


def propose_lock_revision(*, lock_id: uuid.UUID) -> dict:
    return {
        "action": "propose_lock_revision",
        "lock_id": str(lock_id),
        "safe": True,
        "note": "Proposal only. Manual hard-lock removal remains human-controlled.",
    }


def get_constraint(*, constraint_id: uuid.UUID) -> dict:
    return {"action": "get_constraint", "constraint_id": str(constraint_id), "safe": True}


def get_constraint_type(*, constraint_type: str) -> dict:
    return {"action": "get_constraint_type", "constraint_type": constraint_type, "safe": True}


def explain_constraint(*, constraint_id: uuid.UUID) -> dict:
    return {
        "action": "explain_constraint",
        "constraint_id": str(constraint_id),
        "safe": True,
        "note": "Deterministic explanation only; no lifecycle transitions.",
    }


def summarize_policy_effect(*, policy_set_id: uuid.UUID) -> dict:
    return {
        "action": "summarize_policy_effect",
        "policy_set_id": str(policy_set_id),
        "safe": True,
        "note": "Summarizes projected policy effects without activating policies.",
    }


def list_pending_policy_reviews() -> dict:
    return {
        "action": "list_pending_policy_reviews",
        "safe": True,
        "note": "Read-only pending review queue.",
    }


def list_policy_exceptions() -> dict:
    return {"action": "list_policy_exceptions", "safe": True}


def propose_policy_set(*, payload: dict) -> dict:
    return {
        "action": "propose_policy_set",
        "payload": payload,
        "safe": True,
        "note": "Proposal only; does not approve or activate.",
    }


def propose_constraint(*, payload: dict) -> dict:
    return {
        "action": "propose_constraint",
        "payload": payload,
        "safe": True,
        "note": "Proposal only; no lifecycle transitions.",
    }


def propose_constraint_priority(*, constraint_id: uuid.UUID, priority: int) -> dict:
    return {
        "action": "propose_constraint_priority",
        "constraint_id": str(constraint_id),
        "priority": priority,
        "safe": True,
        "note": "Priority recommendation only.",
    }


def propose_exception_request(*, payload: dict) -> dict:
    return {
        "action": "propose_exception_request",
        "payload": payload,
        "safe": True,
        "note": "Exception request proposal only.",
    }


def explain_policy_tradeoff(*, policy_set_id: uuid.UUID) -> dict:
    return {
        "action": "explain_policy_tradeoff",
        "policy_set_id": str(policy_set_id),
        "safe": True,
        "note": "Tradeoff analysis only.",
    }


def identify_missing_constraints(*, policy_set_id: uuid.UUID) -> dict:
    return {
        "action": "identify_missing_constraints",
        "policy_set_id": str(policy_set_id),
        "safe": True,
        "note": "Gap analysis only.",
    }


def approve_policy(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "approve_policy", "policy_set_id": str(policy_set_id), "requires_human_authorization": True}


def activate_policy(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "activate_policy", "policy_set_id": str(policy_set_id), "requires_human_authorization": True}


def suspend_policy(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "suspend_policy", "policy_set_id": str(policy_set_id), "requires_human_authorization": True}


def retire_policy(*, policy_set_id: uuid.UUID) -> dict:
    return {"action": "retire_policy", "policy_set_id": str(policy_set_id), "requires_human_authorization": True}


def approve_constraint(*, constraint_id: uuid.UUID) -> dict:
    return {"action": "approve_constraint", "constraint_id": str(constraint_id), "requires_human_authorization": True}


def activate_constraint(*, constraint_id: uuid.UUID) -> dict:
    return {"action": "activate_constraint", "constraint_id": str(constraint_id), "requires_human_authorization": True}


def approve_exception(*, exception_id: uuid.UUID) -> dict:
    return {"action": "approve_exception", "exception_id": str(exception_id), "requires_human_authorization": True}


def revoke_exception(*, exception_id: uuid.UUID) -> dict:
    return {"action": "revoke_exception", "exception_id": str(exception_id), "requires_human_authorization": True}


def inspect_generation_configuration(*, configuration_id: uuid.UUID) -> dict:
    return {"action": "inspect_generation_configuration", "configuration_id": str(configuration_id), "safe": True}


def summarize_generation_controls(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "summarize_generation_controls",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only summary of generation controls and readiness.",
    }


def list_teacher_scheduling_preferences() -> dict:
    return {"action": "list_teacher_scheduling_preferences", "safe": True}


def explain_teacher_preference_strength(*, strength: str) -> dict:
    return {
        "action": "explain_teacher_preference_strength",
        "strength": strength,
        "safe": True,
    }


def list_timetable_locks(*, configuration_id: uuid.UUID) -> dict:
    return {"action": "list_timetable_locks", "configuration_id": str(configuration_id), "safe": True}


def explain_repair_scope(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_repair_scope",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def list_parallel_lesson_blocks() -> dict:
    return {"action": "list_parallel_lesson_blocks", "safe": True}


def explain_parallel_block(*, block_id: uuid.UUID) -> dict:
    return {"action": "explain_parallel_block", "block_id": str(block_id), "safe": True}


def explain_bell_schedule_effect(*, bell_schedule_id: uuid.UUID) -> dict:
    return {
        "action": "explain_bell_schedule_effect",
        "bell_schedule_id": str(bell_schedule_id),
        "safe": True,
        "note": "Explains logical-period vs clock-time impact without mutating timetable assignments.",
    }


def inspect_scheduling_problem_summary(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "inspect_scheduling_problem_summary",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only summary of normalized scheduling inputs and solver eligibility gate.",
    }


def explain_problem_build_blockers(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_problem_build_blockers",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only explanation of deterministic build blockers and warnings.",
    }


def summarize_scheduling_inputs(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "summarize_scheduling_inputs",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def explain_parallel_block_normalization(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_parallel_block_normalization",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def explain_repair_inputs(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_repair_inputs",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def explain_lock_inputs(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_lock_inputs",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def explain_generation_objectives(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_generation_objectives",
        "configuration_id": str(configuration_id),
        "safe": True,
    }


def propose_teacher_scheduling_preference(*, payload: dict) -> dict:
    return {
        "action": "propose_teacher_scheduling_preference",
        "payload": payload,
        "safe": True,
        "note": "Proposal only; no automatic approval.",
    }


def propose_generation_override(*, payload: dict) -> dict:
    return {
        "action": "propose_generation_override",
        "payload": payload,
        "safe": True,
        "note": "Proposal only; no permanent policy mutation.",
    }


def propose_lock_scope(*, payload: dict) -> dict:
    return {
        "action": "propose_lock_scope",
        "payload": payload,
        "safe": True,
    }


def propose_repair_scope(*, payload: dict) -> dict:
    return {
        "action": "propose_repair_scope",
        "payload": payload,
        "safe": True,
    }


def propose_stability_mode(*, stability_mode: str) -> dict:
    return {
        "action": "propose_stability_mode",
        "stability_mode": stability_mode,
        "safe": True,
    }


def propose_generation_objective_priorities(*, priorities: list[dict]) -> dict:
    return {
        "action": "propose_generation_objective_priorities",
        "priorities": priorities,
        "safe": True,
    }


def propose_parallel_block_configuration(*, payload: dict) -> dict:
    return {
        "action": "propose_parallel_block_configuration",
        "payload": payload,
        "safe": True,
    }


def propose_problem_input_correction(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_problem_input_correction",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
        "note": "Proposal only; does not mutate canonical setup or policy records.",
    }


def propose_generation_configuration_revision(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_generation_configuration_revision",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
    }


def propose_lock_adjustment(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_lock_adjustment",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
    }


def propose_preference_adjustment(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_preference_adjustment",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
    }


def propose_repair_scope_adjustment(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_repair_scope_adjustment",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
    }


def override_solver_eligibility(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "override_solver_eligibility",
        "configuration_id": str(configuration_id),
        "requires_human_authorization": True,
    }


def approve_generation_configuration(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "approve_generation_configuration",
        "configuration_id": str(configuration_id),
        "requires_human_authorization": True,
    }


def approve_permanent_policy_change(*, policy_set_id: uuid.UUID) -> dict:
    return {
        "action": "approve_permanent_policy_change",
        "policy_set_id": str(policy_set_id),
        "requires_human_authorization": True,
    }


def remove_principal_hard_lock(*, lock_id: uuid.UUID) -> dict:
    return {
        "action": "remove_principal_hard_lock",
        "lock_id": str(lock_id),
        "requires_human_authorization": True,
    }


def start_solver_generation(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "start_solver_generation",
        "configuration_id": str(configuration_id),
        "requires_human_authorization": True,
    }


def inspect_timetable_candidates_preview(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "inspect_timetable_candidates_preview",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only transient candidate generation and comparison preview.",
    }


def explain_candidate_tradeoffs(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "explain_candidate_tradeoffs",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only explainability summary for candidate score trade-offs.",
    }


def compare_timetable_candidates(*, configuration_id: uuid.UUID) -> dict:
    return {
        "action": "compare_timetable_candidates",
        "configuration_id": str(configuration_id),
        "safe": True,
        "note": "Read-only pairwise comparison of transient candidates.",
    }


def propose_candidate_generation_options(*, configuration_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_candidate_generation_options",
        "configuration_id": str(configuration_id),
        "payload": payload,
        "safe": True,
        "note": "Proposal only; no candidate persistence or publication.",
    }


def approve_candidate_selection(*, candidate_id: uuid.UUID) -> dict:
    return {
        "action": "approve_candidate_selection",
        "candidate_id": str(candidate_id),
        "requires_human_authorization": True,
        "note": "Human-only decision marker; does not persist timetable in Batch 4.",
    }


def approve_timetable_candidate(*, candidate_id: uuid.UUID) -> dict:
    return {
        "action": "approve_timetable_candidate",
        "candidate_id": str(candidate_id),
        "requires_human_authorization": True,
    }


def publish_timetable(*, timetable_version_id: uuid.UUID) -> dict:
    return {
        "action": "publish_timetable",
        "timetable_version_id": str(timetable_version_id),
        "requires_human_authorization": True,
    }


def explain_readiness_blocker(*, blocker_key: str) -> dict:
    return {
        "action": "explain_readiness_blocker",
        "blocker_key": blocker_key,
        "safe": True,
        "note": "Explains deterministic blocker causes and next action.",
    }


def list_upcoming_events(*, days: int = 14) -> dict:
    return {"action": "list_upcoming_events", "days": days, "safe": True}


def get_today_events() -> dict:
    return {"action": "get_today_events", "safe": True}


def get_week_events() -> dict:
    return {"action": "get_week_events", "safe": True}


def explain_event(*, event_id: uuid.UUID) -> dict:
    return {"action": "explain_event", "event_id": str(event_id), "safe": True}


def find_event_conflicts(*, start_date: date_type, end_date: date_type) -> dict:
    return {
        "action": "find_event_conflicts",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "safe": True,
    }


def calculate_event_impact(*, event_id: uuid.UUID) -> dict:
    return {"action": "calculate_event_impact", "event_id": str(event_id), "safe": True}


def get_changed_events(*, since: date_type) -> dict:
    return {"action": "get_changed_events", "since": since.isoformat(), "safe": True}


def get_cancelled_events(*, since: date_type | None = None) -> dict:
    return {
        "action": "get_cancelled_events",
        "since": since.isoformat() if since else None,
        "safe": True,
    }


def get_pending_calendar_approvals() -> dict:
    return {"action": "get_pending_calendar_approvals", "safe": True}


def inspect_calendar_pdf(*, document_id: uuid.UUID) -> dict:
    return {"action": "inspect_calendar_pdf", "document_id": str(document_id), "safe": True}


def extract_calendar_text(*, document_id: uuid.UUID) -> dict:
    return {
        "action": "extract_calendar_text",
        "document_id": str(document_id),
        "safe": True,
        "note": "Extraction only; cannot approve or commit candidates.",
    }


def propose_calendar_candidates(*, document_id: uuid.UUID) -> dict:
    return {
        "action": "propose_calendar_candidates",
        "document_id": str(document_id),
        "safe": True,
        "note": "Candidate proposal only.",
    }


def classify_calendar_candidate(*, candidate_id: uuid.UUID) -> dict:
    return {"action": "classify_calendar_candidate", "candidate_id": str(candidate_id), "safe": True}


def propose_manual_calendar_event(*, payload: dict) -> dict:
    return {
        "action": "propose_manual_calendar_event",
        "payload": payload,
        "safe": True,
        "note": "Creates draft intent only; no approval or publication.",
    }


def propose_event_update(*, event_id: uuid.UUID, payload: dict) -> dict:
    return {"action": "propose_event_update", "event_id": str(event_id), "payload": payload, "safe": True}


def propose_event_reschedule(*, event_id: uuid.UUID, payload: dict) -> dict:
    return {
        "action": "propose_event_reschedule",
        "event_id": str(event_id),
        "payload": payload,
        "safe": True,
    }


def propose_event_cancellation(*, event_id: uuid.UUID, reason: str) -> dict:
    return {
        "action": "propose_event_cancellation",
        "event_id": str(event_id),
        "reason": reason,
        "safe": True,
    }


def prepare_notification_plan(*, event_id: uuid.UUID, trigger_reason: str) -> dict:
    return {
        "action": "prepare_notification_plan",
        "event_id": str(event_id),
        "trigger_reason": trigger_reason,
        "safe": True,
    }


def prepare_event_reminder(*, event_id: uuid.UUID) -> dict:
    return {"action": "prepare_event_reminder", "event_id": str(event_id), "safe": True}


def summarize_calendar_changes(*, since: date_type) -> dict:
    return {"action": "summarize_calendar_changes", "since": since.isoformat(), "safe": True}


def explain_calendar_diagnostics(*, document_id: uuid.UUID) -> dict:
    return {"action": "explain_calendar_diagnostics", "document_id": str(document_id), "safe": True}


def approve_calendar_candidate(*, candidate_id: uuid.UUID) -> dict:
    return {"action": "approve_calendar_candidate", "candidate_id": str(candidate_id), "requires_human_authorization": True}


def reject_calendar_candidate(*, candidate_id: uuid.UUID) -> dict:
    return {"action": "reject_calendar_candidate", "candidate_id": str(candidate_id), "requires_human_authorization": True}


def approve_calendar_event(*, event_id: uuid.UUID) -> dict:
    return {"action": "approve_calendar_event", "event_id": str(event_id), "requires_human_authorization": True}


def publish_calendar_event(*, event_id: uuid.UUID) -> dict:
    return {"action": "publish_calendar_event", "event_id": str(event_id), "requires_human_authorization": True}


def approve_event_update(*, event_id: uuid.UUID) -> dict:
    return {"action": "approve_event_update", "event_id": str(event_id), "requires_human_authorization": True}


def approve_event_reschedule(*, event_id: uuid.UUID) -> dict:
    return {"action": "approve_event_reschedule", "event_id": str(event_id), "requires_human_authorization": True}


def approve_event_cancellation(*, event_id: uuid.UUID) -> dict:
    return {"action": "approve_event_cancellation", "event_id": str(event_id), "requires_human_authorization": True}


def approve_notification_plan(*, plan_id: uuid.UUID) -> dict:
    return {"action": "approve_notification_plan", "plan_id": str(plan_id), "requires_human_authorization": True}


def execute_calendar_commit(*, document_id: uuid.UUID) -> dict:
    return {"action": "execute_calendar_commit", "document_id": str(document_id), "requires_human_authorization": True}
