"""
Human Review node for exam marking.

Sets status to 'pending_review'.
All AI-proposed marks stay pending until the teacher explicitly approves.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def exam_human_review_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "human_review")

    generated = state.get("generated_content", {})
    inp = state.get("structured_input", {})
    pipeline = generated.get("processing_pipeline", "unknown")
    proposed = generated.get("proposed_total", 0.0)
    max_m = generated.get("max_marks", 0.0)
    pct = generated.get("percentage", 0.0)
    flagged = len(generated.get("flagged_questions", []))
    unresolved = generated.get("unresolved_count", 0)

    message = (
        f"Assessment processed via {pipeline} pipeline. "
        f"Proposed mark: {proposed}/{max_m} ({pct}%). "
        f"Flagged for review: {flagged} question(s). "
        f"Unresolved: {unresolved}. "
        "Review and approve each question before finalising."
    )

    state["approval_status"] = "pending_review"
    state["final_response"] = {
        "status": "pending_review",
        "request_id": state.get("request_id", ""),
        "conversation_id": state.get("conversation_id"),
        "intent": state.get("intent"),
        "message": message,
        "result": generated,
        "missing_fields": [],
        "execution": {
            "workflow": "exam_marking",
            "current_step": "human_review",
            "validation_passed": bool(state.get("validation_result", {}).get("passed")),
            "retry_count": state.get("retry_count", 0),
            "tenant_slug": state.get("tenant_slug"),
        },
    }

    finish_node(state, "human_review", started)
    return state
