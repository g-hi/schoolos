from __future__ import annotations

from langgraph.graph import END, StateGraph

from services.gateway.ai.copilot.nodes.assessment_generation import assessment_generation_node
from services.gateway.ai.copilot.nodes.context_loader import context_loader_node
from services.gateway.ai.copilot.nodes.fallback import fallback_node
from services.gateway.ai.copilot.nodes.human_approval import human_approval_node
from services.gateway.ai.copilot.nodes.intent_router import intent_router_node, route_after_intent
from services.gateway.ai.copilot.nodes.missing_information import (
    missing_information_node,
    route_after_missing_information,
)
from services.gateway.ai.copilot.nodes.observability import observability_node
from services.gateway.ai.copilot.nodes.request_validation import request_validation_node
from services.gateway.ai.copilot.nodes.revision import revision_node, route_after_revision
from services.gateway.ai.copilot.nodes.validation import route_after_validation, validation_node
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState


def build_assessment_generation_graph(provider: LLMProvider):
    graph = StateGraph(SchoolOSAIState)

    async def assessment_generation_with_provider(state: SchoolOSAIState) -> SchoolOSAIState:
        return await assessment_generation_node(state, provider)

    graph.add_node("request_validation", request_validation_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("context_loader", context_loader_node)
    graph.add_node("missing_information", missing_information_node)
    graph.add_node("assessment_generation", assessment_generation_with_provider)
    graph.add_node("validation", validation_node)
    graph.add_node("revision", revision_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("observability", observability_node)

    graph.set_entry_point("request_validation")
    graph.add_edge("request_validation", "intent_router")

    graph.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "context_loader": "context_loader",
            "fallback": "fallback",
        },
    )

    graph.add_edge("context_loader", "missing_information")

    graph.add_conditional_edges(
        "missing_information",
        route_after_missing_information,
        {
            "assessment_generation": "assessment_generation",
            "observability": "observability",
        },
    )

    graph.add_edge("assessment_generation", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "human_approval": "human_approval",
            "revision": "revision",
            "fallback": "fallback",
        },
    )

    graph.add_conditional_edges(
        "revision",
        route_after_revision,
        {
            "assessment_generation": "assessment_generation",
            "lesson_planning": "fallback",
        },
    )

    graph.add_edge("human_approval", "observability")
    graph.add_edge("fallback", "observability")
    graph.add_edge("observability", END)

    return graph.compile()