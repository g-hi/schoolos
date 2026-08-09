from __future__ import annotations

import uuid

from services.gateway.timetable_setup import actions


def test_phase_10c_problem_safe_actions() -> None:
    config_id = uuid.uuid4()

    payloads = (
        actions.inspect_scheduling_problem_summary(configuration_id=config_id),
        actions.explain_problem_build_blockers(configuration_id=config_id),
        actions.summarize_scheduling_inputs(configuration_id=config_id),
        actions.explain_parallel_block_normalization(configuration_id=config_id),
        actions.explain_repair_inputs(configuration_id=config_id),
        actions.explain_lock_inputs(configuration_id=config_id),
        actions.explain_generation_objectives(configuration_id=config_id),
    )

    for payload in payloads:
        assert payload.get("safe") is True
        assert "requires_human_authorization" not in payload


def test_phase_10c_problem_proposal_actions_are_safe() -> None:
    config_id = uuid.uuid4()
    proposal_payload = {"example": True}

    payloads = (
        actions.propose_problem_input_correction(configuration_id=config_id, payload=proposal_payload),
        actions.propose_generation_configuration_revision(configuration_id=config_id, payload=proposal_payload),
        actions.propose_lock_adjustment(configuration_id=config_id, payload=proposal_payload),
        actions.propose_preference_adjustment(configuration_id=config_id, payload=proposal_payload),
        actions.propose_repair_scope_adjustment(configuration_id=config_id, payload=proposal_payload),
    )

    for payload in payloads:
        assert payload.get("safe") is True
        assert "requires_human_authorization" not in payload


def test_phase_10c_problem_human_actions_are_explicit() -> None:
    config_id = uuid.uuid4()

    assert actions.override_solver_eligibility(configuration_id=config_id)["requires_human_authorization"] is True
    assert actions.start_solver_generation(configuration_id=config_id)["requires_human_authorization"] is True
