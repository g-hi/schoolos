"""
Confidence Review node.

Applies configurable confidence thresholds.
Sorts the review queue: low-confidence questions appear first.
Flags unresolved and unanswered items.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

_HIGH = 0.90
_MEDIUM = 0.70


async def confidence_review_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "confidence_review")

    generated = state.get("generated_content", {})
    inp = state.get("structured_input", {})

    # Allow session-level threshold overrides
    high_threshold = float(inp.get("confidence_threshold_high", _HIGH))
    medium_threshold = float(inp.get("confidence_threshold_medium", _MEDIUM))

    responses: list[dict] = generated.get("question_responses", [])

    def _confidence_band(conf: float) -> str:
        if conf >= high_threshold:
            return "high"
        if conf >= medium_threshold:
            return "medium"
        return "low"

    flagged_questions: list[int] = []
    for r in responses:
        conf = float(r.get("confidence", 1.0) or 1.0)
        band = _confidence_band(conf)
        r["confidence_band"] = band
        if band == "low" or r.get("status") == "unresolved":
            flagged_questions.append(r.get("question_number", 0))
            r["requires_teacher_review"] = True

    # Sort: low confidence first, then medium, then high
    def _sort_key(r: dict) -> int:
        band = r.get("confidence_band", "high")
        return {"low": 0, "medium": 1, "high": 2}.get(band, 3)

    sorted_responses = sorted(responses, key=_sort_key)
    generated["question_responses"] = sorted_responses
    generated["flagged_questions"] = flagged_questions
    generated["confidence_summary"] = {
        "high_threshold": high_threshold,
        "medium_threshold": medium_threshold,
        "flagged_count": len(flagged_questions),
        "total_questions": len(responses),
    }

    state["generated_content"] = generated
    finish_node(state, "confidence_review", started)
    return state
