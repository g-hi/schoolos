from __future__ import annotations

from langgraph.graph import END, StateGraph

from services.gateway.ai.copilot.nodes.observability import observability_node
from services.gateway.ai.copilot.nodes.parent_assistant import (
    build_parent_audit_node,
    build_parent_bootstrap_node,
    build_parent_context_loader_node,
    build_parent_response_node,
    parent_intent_node,
    parent_student_resolution_node,
)
from services.gateway.ai.copilot.nodes.request_validation import request_validation_node
from services.gateway.ai.copilot.parent_assistant_data import (
    load_parent_bootstrap,
    load_pickup_status,
    load_timeline_events,
    load_today_schedule,
)
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState


def build_parent_assistant_graph(provider: LLMProvider, workflow_context: dict | None = None):
    workflow_context = workflow_context or {}
    db = workflow_context.get("db")
    if db is None:
        raise ValueError("Parent Assistant requires a database session in workflow context.")

    graph = StateGraph(SchoolOSAIState)

    graph.add_node("request_validation", request_validation_node)
    graph.add_node("parent_bootstrap", build_parent_bootstrap_node(lambda **kwargs: load_parent_bootstrap(db, **kwargs)))
    graph.add_node("parent_intent", parent_intent_node)
    graph.add_node("parent_student_resolution", parent_student_resolution_node)
    graph.add_node(
        "parent_context_loader",
        build_parent_context_loader_node(
            timeline_loader=lambda **kwargs: load_timeline_events(db, **kwargs),
            pickup_loader=lambda **kwargs: load_pickup_status(db, **kwargs),
            schedule_loader=lambda **kwargs: load_today_schedule(db, **kwargs),
        ),
    )
    graph.add_node("parent_response", build_parent_response_node(provider))
    graph.add_node("parent_audit", build_parent_audit_node(db))
    graph.add_node("observability", observability_node)

    graph.set_entry_point("request_validation")
    graph.add_edge("request_validation", "parent_bootstrap")
    graph.add_edge("parent_bootstrap", "parent_intent")
    graph.add_edge("parent_intent", "parent_student_resolution")
    graph.add_edge("parent_student_resolution", "parent_context_loader")
    graph.add_edge("parent_context_loader", "parent_response")
    graph.add_edge("parent_response", "parent_audit")
    graph.add_edge("parent_audit", "observability")
    graph.add_edge("observability", END)

    return graph.compile()