from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def request_validation_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "request_validation")

    missing = []
    if not state.get("tenant_slug"):
        missing.append("tenant_slug")
    if not state.get("request_id"):
        missing.append("request_id")
    if not state.get("original_message"):
        missing.append("message")

    if missing:
        state.setdefault("errors", []).append(f"Missing request metadata: {', '.join(missing)}")
        state["final_response"] = {
            "status": "error",
            "request_id": state.get("request_id", "unknown"),
            "conversation_id": state.get("conversation_id"),
            "intent": state.get("intent"),
            "message": "Request metadata is incomplete.",
            "missing_fields": missing,
            "execution": {
                "workflow": "unknown",
                "current_step": "request_validation",
                "validation_passed": False,
                "retry_count": state.get("retry_count", 0),
                "tenant_slug": state.get("tenant_slug"),
            },
        }

    finish_node(state, "request_validation", started)
    return state
