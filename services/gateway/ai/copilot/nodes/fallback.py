from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def fallback_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "fallback")

    final_response = state.get("final_response")
    if not final_response:
        validation_issues = state.get("validation_result", {}).get("issues", [])
        message = "Unable to complete the workflow safely."
        if validation_issues:
            message = f"Generated output failed validation: {', '.join(validation_issues)}."

        state["final_response"] = {
            "status": "error",
            "request_id": state["request_id"],
            "conversation_id": state.get("conversation_id"),
            "intent": state.get("intent"),
            "message": message,
            "missing_fields": [],
            "execution": {
                "workflow": "fallback",
                "current_step": "fallback",
                "validation_passed": False,
                "retry_count": state.get("retry_count", 0),
                "tenant_slug": state.get("tenant_slug"),
            },
        }

    finish_node(state, "fallback", started)
    return state
