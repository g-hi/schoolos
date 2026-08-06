from __future__ import annotations

import uuid
from datetime import date

from services.gateway.timetable_setup import actions


def test_proposal_actions_are_safe_and_non_authorizing() -> None:
    candidate = actions.propose_calendar_candidates(document_id=uuid.uuid4())
    extract = actions.extract_calendar_text(document_id=uuid.uuid4())
    proposed_event = actions.propose_manual_calendar_event(payload={"event_name": "Event"})

    assert candidate["safe"] is True
    assert extract["safe"] is True
    assert proposed_event["safe"] is True


def test_human_authorized_actions_require_authorization_flag() -> None:
    for payload in (
        actions.approve_calendar_candidate(candidate_id=uuid.uuid4()),
        actions.reject_calendar_candidate(candidate_id=uuid.uuid4()),
        actions.approve_calendar_event(event_id=uuid.uuid4()),
        actions.publish_calendar_event(event_id=uuid.uuid4()),
        actions.approve_event_update(event_id=uuid.uuid4()),
        actions.approve_event_reschedule(event_id=uuid.uuid4()),
        actions.approve_event_cancellation(event_id=uuid.uuid4()),
        actions.approve_notification_plan(plan_id=uuid.uuid4()),
        actions.execute_calendar_commit(document_id=uuid.uuid4()),
    ):
        assert payload["requires_human_authorization"] is True


def test_read_actions_return_safe_contracts() -> None:
    assert actions.get_today_events()["safe"] is True
    assert actions.get_week_events()["safe"] is True
    assert actions.list_upcoming_events(days=7)["safe"] is True
    assert actions.calculate_event_impact(event_id=uuid.uuid4())["safe"] is True
    assert actions.get_changed_events(since=date(2026, 1, 1))["safe"] is True
