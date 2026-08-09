from __future__ import annotations

import uuid

from services.gateway.timetable_setup import actions


def test_phase_10c_generation_agent_safe_actions() -> None:
    config_id = uuid.uuid4()
    block_id = uuid.uuid4()
    bell_schedule_id = uuid.uuid4()

    inspect = actions.inspect_generation_configuration(configuration_id=config_id)
    summary = actions.summarize_generation_controls(configuration_id=config_id)
    prefs = actions.list_teacher_scheduling_preferences()
    strength = actions.explain_teacher_preference_strength(strength="hard")
    locks = actions.list_timetable_locks(configuration_id=config_id)
    repair_scope = actions.explain_repair_scope(configuration_id=config_id)
    parallel = actions.list_parallel_lesson_blocks()
    parallel_explain = actions.explain_parallel_block(block_id=block_id)
    bell = actions.explain_bell_schedule_effect(bell_schedule_id=bell_schedule_id)
    readiness = actions.explain_generation_readiness()

    for payload in (
        inspect,
        summary,
        prefs,
        strength,
        locks,
        repair_scope,
        parallel,
        parallel_explain,
        bell,
        readiness,
    ):
        assert payload.get("safe") is True
        assert "requires_human_authorization" not in payload


def test_phase_10c_generation_proposal_actions_are_safe() -> None:
    proposal_payload = {"example": True}

    for payload in (
        actions.propose_teacher_scheduling_preference(payload=proposal_payload),
        actions.propose_generation_override(payload=proposal_payload),
        actions.propose_lock_scope(payload=proposal_payload),
        actions.propose_repair_scope(payload=proposal_payload),
        actions.propose_stability_mode(stability_mode="high"),
        actions.propose_generation_objective_priorities(priorities=[{"objective_key": "teacher_preferences", "priority_level": "high"}]),
        actions.propose_parallel_block_configuration(payload=proposal_payload),
    ):
        assert payload.get("safe") is True
        assert "requires_human_authorization" not in payload


def test_phase_10c_human_authorized_actions_are_explicit() -> None:
    config_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    lock_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    timetable_version_id = uuid.uuid4()

    assert actions.approve_generation_configuration(configuration_id=config_id)["requires_human_authorization"] is True
    assert actions.approve_permanent_policy_change(policy_set_id=policy_id)["requires_human_authorization"] is True
    assert actions.remove_principal_hard_lock(lock_id=lock_id)["requires_human_authorization"] is True
    assert actions.start_solver_generation(configuration_id=config_id)["requires_human_authorization"] is True
    assert actions.approve_timetable_candidate(candidate_id=candidate_id)["requires_human_authorization"] is True
    assert actions.publish_timetable(timetable_version_id=timetable_version_id)["requires_human_authorization"] is True
