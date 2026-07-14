"""
Pipeline Processing node — single LangGraph node that delegates to
the ProcessingStrategyFactory.

This node is the only touch point between LangGraph and the provider layer.
Adding a new provider or paper type never requires changing this node.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node
from services.gateway.ai.exam_marking.strategies.base import StrategyInput
from services.gateway.ai.exam_marking.strategies.factory import ProcessingStrategyFactory

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry


async def pipeline_processing_node(
    state: SchoolOSAIState,
    registry: "ProviderRegistry",
) -> SchoolOSAIState:
    started = start_node(state, "pipeline_processing")

    inp = state.get("structured_input", {})
    paper_type: str = inp.get("paper_type_classified", inp.get("paper_type", "open_ended"))
    answer_key: list[dict] = inp.get("normalized_answer_key", inp.get("answer_key", []))

    strategy = ProcessingStrategyFactory.get_strategy(paper_type)

    strategy_inp = StrategyInput(
        session_id=inp.get("session_id", ""),
        submission_id=inp.get("submission_id", ""),
        paper_type=paper_type,
        pages=inp.get("pages", []),
        answer_key=answer_key,
        marking_scheme=inp.get("normalized_rubric", inp.get("marking_scheme", {})),
        teacher_guidance=inp.get("teacher_guidance", ""),
        expected_question_count=int(
            inp.get("expected_question_count", len(answer_key)) or len(answer_key) or 1
        ),
        tenant_id=state.get("tenant_id", ""),
        subject=inp.get("subject", ""),
        curriculum_context=inp.get("curriculum", ""),
    )

    try:
        result = await strategy.process(strategy_inp, registry)
    except Exception as exc:
        state["errors"] = state.get("errors", []) + [f"pipeline_failed: {type(exc).__name__}"]
        state["generated_content"] = {
            "question_responses": [],
            "proposed_total": 0.0,
            "max_marks": 0.0,
            "processing_pipeline": paper_type,
            "requires_review": True,
            "failed": True,
        }
        finish_node(state, "pipeline_processing", started)
        return state

    state["generated_content"] = {
        "question_responses": result.question_responses,
        "proposed_total": result.proposed_total,
        "max_marks": result.max_marks,
        "processing_pipeline": result.processing_pipeline,
        "requires_review": result.requires_review,
        "unresolved_count": result.unresolved_count,
        "objective_question_count": result.objective_question_count,
        "ai_graded_count": result.ai_graded_count,
        "deterministic_count": result.deterministic_count,
        "estimated_cost_usd": result.estimated_cost_usd,
    }

    # Accumulate token usage into state (existing field, picked up by observability)
    existing_usage: dict = state.get("token_usage", {})
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        existing_usage[k] = existing_usage.get(k, 0) + result.token_usage.get(k, 0)
    state["token_usage"] = existing_usage

    # Append provider telemetry to execution_trace (observability_node reads this)
    trace: list[dict] = state.get("execution_trace", [])
    trace.extend(result.telemetry_events)
    state["execution_trace"] = trace

    finish_node(state, "pipeline_processing", started)
    return state
