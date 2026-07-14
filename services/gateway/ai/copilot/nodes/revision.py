from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def revision_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "revision")

    # Retry is explicitly bounded to prevent uncontrolled graph loops.
    state["retry_count"] = state.get("retry_count", 0) + 1

    issues = state.get("validation_result", {}).get("issues", [])
    workflow = state.get("intent", "lesson_planning")
    revision_note = "Ensure all required output sections are present."
    if issues:
        revision_note = f"Ensure these sections are complete: {', '.join(issues)}."

    if workflow == "assessment_generation":
        revision_note = f"Assessment revisions required for: {', '.join(issues) if issues else 'content quality'}"

    retrieved_context = state.setdefault("retrieved_context", {})
    retrieved_context["revision_note"] = revision_note

    finish_node(state, "revision", started)
    return state


def route_after_revision(state: SchoolOSAIState) -> str:
    # Transition back to the workflow-specific generation node.
    if state.get("intent") == "assessment_generation":
        return "assessment_generation"
    return "lesson_planning"
