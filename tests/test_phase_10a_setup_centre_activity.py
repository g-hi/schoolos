from __future__ import annotations

from services.gateway.timetable_setup import centre


def test_activity_detail_summary_is_primitive_and_bounded() -> None:
    details = {
        "a": "one",
        "b": 2,
        "c": True,
        "d": None,
        "e": {"nested": "ignored"},
        "f": ["ignored"],
        "g": "included",
        "h": "truncated",
    }
    summary = centre._summarize_audit_details(details)
    assert "e" not in summary
    assert "f" not in summary
    assert len(summary) <= 6
