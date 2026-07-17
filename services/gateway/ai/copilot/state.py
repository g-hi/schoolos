from __future__ import annotations

from datetime import date, datetime
from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID


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
    parent_profile: dict[str, Any]
    family_context: dict[str, Any]
    authorized_students: list[dict[str, Any]]
    parent_intent: str
    resolved_student: dict[str, Any]
    evidence_records: list[dict[str, Any]]
    source_items: list[dict[str, Any]]
    deterministic_suggestions: list[str]
    timeline_events: list[dict[str, Any]]
    pickup_records: list[dict[str, Any]]
    schedule_records: list[dict[str, Any]]
    schedule_timezone: str
    workflow_db: Any


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


def sanitize_state_for_checkpoint(state: SchoolOSAIState) -> dict[str, Any]:
    """Return a checkpoint-safe copy of workflow state.

    Only serializable workflow data is allowed into persisted checkpoint state.
    Runtime dependency injection must happen through graph construction or node
    closures, not through the state dictionary.
    """

    def _convert(value: Any, path: str) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        if isinstance(value, UUID):
            return str(value)

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, date):
            return value.isoformat()

        if isinstance(value, list):
            return [_convert(item, f"{path}[]") for item in value]

        if isinstance(value, tuple):
            return [_convert(item, f"{path}[]") for item in value]

        if isinstance(value, dict):
            converted: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"Checkpoint state contains non-string key at {path}.")
                converted[key] = _convert(item, f"{path}.{key}")
            return converted

        raise TypeError(
            f"Checkpoint state contains unsupported runtime value at {path}: {type(value).__name__}."
        )

    serializable_state = dict(state)
    serializable_state.pop("workflow_db", None)
    return _convert(serializable_state, "state")
