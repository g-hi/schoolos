from __future__ import annotations

import uuid

from services.gateway.timetable_setup import actions


def test_phase_10c_candidate_safe_actions() -> None:
    config_id = uuid.uuid4()

    payloads = (
        actions.inspect_timetable_candidates_preview(configuration_id=config_id),
        actions.explain_candidate_tradeoffs(configuration_id=config_id),
        actions.compare_timetable_candidates(configuration_id=config_id),
    )

    for payload in payloads:
        assert payload.get("safe") is True
        assert "requires_human_authorization" not in payload


def test_phase_10c_candidate_proposal_action_is_safe() -> None:
    config_id = uuid.uuid4()
    payload = actions.propose_candidate_generation_options(configuration_id=config_id, payload={"candidate_count": 3})

    assert payload.get("safe") is True
    assert "requires_human_authorization" not in payload


def test_phase_10c_candidate_human_actions_are_explicit() -> None:
    cid = uuid.uuid4()
    payload = actions.approve_candidate_selection(candidate_id=cid)
    assert payload["requires_human_authorization"] is True
    assert actions.approve_timetable_candidate(candidate_id=cid)["requires_human_authorization"] is True
    assert actions.publish_timetable(timetable_version_id=uuid.uuid4())["requires_human_authorization"] is True
