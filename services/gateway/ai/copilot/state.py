from __future__ import annotations

from time import perf_counter
from typing import Any, TypedDict


class SchoolOSAIState(TypedDict, total=False):
    tenant_id: str
    tenant_slug: str
    user_id: str
    user_role: str
    conversation_id: str
    request_id: str
    intent: str
    original_message: str
    structured_input: dict[str, Any]
    teacher_context: dict[str, Any]
    school_context: dict[str, Any]
    retrieved_context: dict[str, Any]
    missing_fields: list[str]
    clarification_question: str
    generated_content: dict[str, Any]
    validation_result: dict[str, Any]
    approval_status: str
    errors: list[str]
    retry_count: int
    max_retries: int
    current_node: str
    execution_trace: list[dict[str, Any]]
    node_timings: dict[str, float]
    final_response: dict[str, Any]
    provider: str
    token_usage: dict[str, Any]


def ensure_state_defaults(state: SchoolOSAIState) -> SchoolOSAIState:
    state.setdefault("structured_input", {})
    state.setdefault("teacher_context", {})
    state.setdefault("school_context", {})
    state.setdefault("retrieved_context", {})
    state.setdefault("missing_fields", [])
    state.setdefault("errors", [])
    state.setdefault("retry_count", 0)
    state.setdefault("max_retries", 1)
    state.setdefault("execution_trace", [])
    state.setdefault("node_timings", {})
    state.setdefault("validation_result", {"passed": False, "issues": []})
    state.setdefault("generated_content", {})
    state.setdefault("approval_status", "pending")
    state.setdefault("token_usage", {})
    return state


def start_node(state: SchoolOSAIState, node_name: str) -> float:
    state["current_node"] = node_name
    return perf_counter()


def finish_node(state: SchoolOSAIState, node_name: str, started_at: float) -> None:
    elapsed_ms = (perf_counter() - started_at) * 1000
    state["node_timings"][node_name] = round(elapsed_ms, 2)
    state["execution_trace"].append(
        {
            "node": node_name,
            "latency_ms": round(elapsed_ms, 2),
        }
    )
