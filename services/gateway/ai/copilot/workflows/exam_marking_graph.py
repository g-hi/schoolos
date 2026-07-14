"""
Exam Marking LangGraph workflow.

Graph structure:
    request_validation → intent_router → session_loader → document_intake
    → scan_quality → page_identification → paper_classifier
    → marking_scheme_parser → pipeline_processing
    → mark_aggregation → confidence_review → exam_marking_validation
    → human_review → observability → END

    scan_quality can route to fallback if all pages are unacceptable.
    exam_marking_validation can retry pipeline_processing or route to fallback.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from services.gateway.ai.copilot.nodes.exam_marking.confidence_review import confidence_review_node
from services.gateway.ai.copilot.nodes.exam_marking.document_intake import document_intake_node
from services.gateway.ai.copilot.nodes.exam_marking.exam_marking_validation import (
    exam_marking_validation_node,
    route_after_exam_marking_validation,
)
from services.gateway.ai.copilot.nodes.exam_marking.human_review import exam_human_review_node
from services.gateway.ai.copilot.nodes.exam_marking.mark_aggregation import mark_aggregation_node
from services.gateway.ai.copilot.nodes.exam_marking.marking_scheme_parser import marking_scheme_parser_node
from services.gateway.ai.copilot.nodes.exam_marking.page_identification import page_identification_node
from services.gateway.ai.copilot.nodes.exam_marking.paper_classifier import paper_classifier_node
from services.gateway.ai.copilot.nodes.exam_marking.pipeline_processing import pipeline_processing_node
from services.gateway.ai.copilot.nodes.exam_marking.scan_quality import route_after_scan_quality, scan_quality_node
from services.gateway.ai.copilot.nodes.exam_marking.session_loader import session_loader_node
from services.gateway.ai.copilot.nodes.fallback import fallback_node
from services.gateway.ai.copilot.nodes.intent_router import intent_router_node
from services.gateway.ai.copilot.nodes.observability import observability_node
from services.gateway.ai.copilot.nodes.request_validation import request_validation_node
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState
from services.gateway.ai.exam_marking.grading.rubric_grader import RubricAIGrader
from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry


def _route_after_intent_exam(state: SchoolOSAIState) -> str:
    """Exam-marking specific intent routing — goes to session_loader, not context_loader."""
    if state.get("final_response"):
        return "fallback"
    return "session_loader"


def build_exam_marking_graph(provider: LLMProvider):
    """
    Build and compile the exam_marking LangGraph workflow.

    provider — the active LLMProvider (deterministic or Groq).
               Used only for rubric AI grading of open-ended questions.
    """
    # Build provider registry — rubric grader backed by the given LLM provider
    registry = ProviderRegistry(
        rubric_grader=RubricAIGrader(provider=provider),
    )

    graph = StateGraph(SchoolOSAIState)

    # Bind registry to pipeline_processing at build time
    async def pipeline_with_registry(state: SchoolOSAIState) -> SchoolOSAIState:
        return await pipeline_processing_node(state, registry)

    # ── Node registration ─────────────────────────────────────────────────────
    graph.add_node("request_validation", request_validation_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("session_loader", session_loader_node)
    graph.add_node("document_intake", document_intake_node)
    graph.add_node("scan_quality", scan_quality_node)
    graph.add_node("page_identification", page_identification_node)
    graph.add_node("paper_classifier", paper_classifier_node)
    graph.add_node("marking_scheme_parser", marking_scheme_parser_node)
    graph.add_node("pipeline_processing", pipeline_with_registry)
    graph.add_node("mark_aggregation", mark_aggregation_node)
    graph.add_node("confidence_review", confidence_review_node)
    graph.add_node("exam_marking_validation", exam_marking_validation_node)
    graph.add_node("human_review", exam_human_review_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("observability", observability_node)

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.set_entry_point("request_validation")
    graph.add_edge("request_validation", "intent_router")

    graph.add_conditional_edges(
        "intent_router",
        _route_after_intent_exam,
        {
            "session_loader": "session_loader",
            "fallback": "fallback",
        },
    )

    graph.add_edge("session_loader", "document_intake")
    graph.add_edge("document_intake", "scan_quality")

    graph.add_conditional_edges(
        "scan_quality",
        route_after_scan_quality,
        {
            "page_identification": "page_identification",
            "fallback": "fallback",
        },
    )

    graph.add_edge("page_identification", "paper_classifier")
    graph.add_edge("paper_classifier", "marking_scheme_parser")
    graph.add_edge("marking_scheme_parser", "pipeline_processing")
    graph.add_edge("pipeline_processing", "mark_aggregation")
    graph.add_edge("mark_aggregation", "confidence_review")
    graph.add_edge("confidence_review", "exam_marking_validation")

    graph.add_conditional_edges(
        "exam_marking_validation",
        route_after_exam_marking_validation,
        {
            "human_review": "human_review",
            "pipeline_processing": "pipeline_processing",
            "fallback": "fallback",
        },
    )

    graph.add_edge("human_review", "observability")
    graph.add_edge("fallback", "observability")
    graph.add_edge("observability", END)

    return graph.compile()
