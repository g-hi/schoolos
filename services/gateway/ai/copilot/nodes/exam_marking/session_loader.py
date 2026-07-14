"""
Session Loader node — loads or initialises the MarkingSession context.

Reads session_id from structured_input and populates structured_input
with session fields (exam title, answer key cache key, etc.) so downstream
nodes can access them without additional DB calls.

If no session_id is provided (first run), the node accepts the inline
structured_input as the session context (single-submission mode).
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def session_loader_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "session_loader")

    inp = state.get("structured_input", {})
    session_id: str = inp.get("session_id", "")

    # Populate defaults when operating in single-submission or synthetic mode.
    inp.setdefault("exam_title", "Exam")
    inp.setdefault("subject", "")
    inp.setdefault("grade", "")
    inp.setdefault("curriculum", "")
    inp.setdefault("paper_type", "open_ended")
    inp.setdefault("expected_question_count", len(inp.get("answer_key", [])) or 1)
    inp.setdefault("teacher_guidance", "")
    inp.setdefault("answer_key", [])
    inp.setdefault("marking_scheme", {})
    inp.setdefault("pages", [])

    state["structured_input"] = inp
    state["school_context"] = {
        **state.get("school_context", {}),
        "session_id": session_id,
        "exam_title": inp.get("exam_title"),
    }

    finish_node(state, "session_loader", started)
    return state
