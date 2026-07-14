from __future__ import annotations

import logging
from time import perf_counter

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

logger = logging.getLogger(__name__)


async def observability_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "observability")

    total_latency_ms = sum(state.get("node_timings", {}).values())
    safe_log = {
        "request_id": state.get("request_id"),
        "tenant": state.get("tenant_slug"),
        "workflow": state.get("intent"),
        "provider": state.get("provider", "deterministic"),
        "token_usage": state.get("token_usage", {}),
        "latency_ms": round(total_latency_ms, 2),
        "validation": state.get("validation_result", {}),
        "errors": state.get("errors", []),
    }
    logger.info("copilot_workflow_completed | %s", safe_log)

    final_response = state.get("final_response", {})
    execution = final_response.get("execution", {})
    execution["current_step"] = execution.get("current_step", state.get("current_node", "observability"))
    final_response["execution"] = execution
    state["final_response"] = final_response

    finish_node(state, "observability", started)
    return state
