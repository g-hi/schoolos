from __future__ import annotations

import uuid

from services.gateway.timetable_setup import actions


def test_proposal_actions_are_safe_and_do_not_authorize_approval_or_activation() -> None:
    proposal = actions.propose_constraint(payload={"constraint_type": "teacher_unavailable"})
    policy_proposal = actions.propose_policy_set(payload={"name": "Draft Policy"})
    exception_proposal = actions.propose_exception_request(payload={"reason": "Exam week override"})
    diagnostics_proposal = actions.inspect_policy_diagnostics()
    conflict_proposal = actions.explain_policy_conflicts()
    feasibility_proposal = actions.analyze_policy_feasibility()
    impact_proposal = actions.summarize_policy_impact()
    resolution_proposal = actions.recommend_policy_resolution()
    readiness_proposal = actions.inspect_policy_readiness()
    effective_policy_proposal = actions.inspect_effective_policy()
    effective_constraints_proposal = actions.inspect_effective_constraints()
    authorization_proposal = actions.inspect_scheduling_authorization()

    assert proposal.get("safe") is True
    assert "requires_human_authorization" not in proposal
    assert policy_proposal.get("safe") is True
    assert "requires_human_authorization" not in policy_proposal
    assert exception_proposal.get("safe") is True
    assert "requires_human_authorization" not in exception_proposal
    assert diagnostics_proposal.get("safe") is True
    assert conflict_proposal.get("safe") is True
    assert feasibility_proposal.get("safe") is True
    assert impact_proposal.get("safe") is True
    assert resolution_proposal.get("safe") is True
    assert readiness_proposal.get("safe") is True
    assert effective_policy_proposal.get("safe") is True
    assert effective_constraints_proposal.get("safe") is True
    assert authorization_proposal.get("safe") is True


def test_human_authorized_actions_are_explicitly_marked() -> None:
    policy_id = uuid.uuid4()
    constraint_id = uuid.uuid4()
    exception_id = uuid.uuid4()

    assert actions.approve_policy(policy_set_id=policy_id)["requires_human_authorization"] is True
    assert actions.activate_policy(policy_set_id=policy_id)["requires_human_authorization"] is True
    assert actions.approve_constraint(constraint_id=constraint_id)["requires_human_authorization"] is True
    assert actions.activate_constraint(constraint_id=constraint_id)["requires_human_authorization"] is True
    assert actions.approve_exception(exception_id=exception_id)["requires_human_authorization"] is True
    assert actions.revoke_exception(exception_id=exception_id)["requires_human_authorization"] is True
