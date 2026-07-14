from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def human_approval_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "human_approval")

    workflow = state.get("intent", "lesson_planning")
    message = "Generated output is ready for teacher review."
    if workflow == "lesson_planning":
        message = "Lesson plan generated and ready for teacher review."
    elif workflow == "assessment_generation":
        message = "Assessment draft generated and ready for teacher review."

    state["approval_status"] = "pending_review"
    state["final_response"] = {
        "status": "pending_review",
        "request_id": state["request_id"],
        "conversation_id": state.get("conversation_id"),
        "intent": state.get("intent"),
        "message": message,
        "result": state.get("generated_content", {}),
        "missing_fields": [],
        "execution": {
            "workflow": workflow,
            "current_step": "human_approval",
            "validation_passed": bool(state.get("validation_result", {}).get("passed")),
            "retry_count": state.get("retry_count", 0),
            "tenant_slug": state.get("tenant_slug"),
        },
    }

    finish_node(state, "human_approval", started)
    return state
