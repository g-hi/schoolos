from __future__ import annotations

from dataclasses import dataclass

REPORT_STATUSES = {
    "draft",
    "generating",
    "pending_review",
    "changes_requested",
    "approved",
    "published",
    "generation_failed",
    "validation_failed",
    "archived",
}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"generating", "pending_review", "archived"},
    "generating": {"pending_review", "generation_failed", "validation_failed", "archived"},
    "pending_review": {"changes_requested", "approved", "archived"},
    "changes_requested": {"pending_review", "archived"},
    "approved": {"published", "pending_review", "archived"},
    "published": {"pending_review", "archived"},
    "generation_failed": {"generating", "pending_review", "archived"},
    "validation_failed": {"generating", "pending_review", "archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    reason: str | None = None


def ensure_status_known(status: str) -> None:
    if status not in REPORT_STATUSES:
        raise ValueError(f"Unknown weekly report status: {status}")


def can_transition(*, previous_status: str, new_status: str) -> TransitionDecision:
    ensure_status_known(previous_status)
    ensure_status_known(new_status)

    allowed = new_status in _ALLOWED_TRANSITIONS.get(previous_status, set())
    if allowed:
        return TransitionDecision(allowed=True)

    return TransitionDecision(
        allowed=False,
        reason=f"Transition not allowed: {previous_status} -> {new_status}",
    )
