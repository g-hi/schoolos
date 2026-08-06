from __future__ import annotations

import asyncio

from services.gateway.timetable_setup import centre


def test_approvals_queue_contains_human_authorization_flags() -> None:
    metrics = {
        "calendar_pending": 2,
        "pending_candidates": 1,
        "pending_plans": 1,
    }
    payload = asyncio.run(centre.get_approvals_queue(metrics))

    assert payload["pending_total"] == 4
    assert payload["items"]
    assert all(item["requires_human_authorization"] is True for item in payload["items"])
    assert any(item["blocks_generation"] is True for item in payload["items"])
