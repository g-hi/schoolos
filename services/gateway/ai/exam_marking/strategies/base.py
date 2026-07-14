"""
Processing Strategy base types.

A ProcessingStrategy encapsulates the full provider orchestration for one
paper type.  The LangGraph pipeline_processing node holds a single call:

    result = await ProcessingStrategyFactory.get_strategy(paper_type).process(inp, registry)

Adding a new provider (Math OCR, Arabic OCR, Diagram Recognition) means:
    1. Register the new provider in ProviderRegistry.
    2. Optionally create a new ProcessingStrategy subclass.
    3. Register the strategy via ProcessingStrategyFactory.register().
    Zero LangGraph node changes required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry


# ── Strategy input ────────────────────────────────────────────────────────────

@dataclass
class StrategyInput:
    session_id: str
    submission_id: str
    paper_type: str                 # scantron | printed_mcq | mixed | open_ended
    pages: list[dict]               # [{page_id, storage_key, page_number}]
    answer_key: list[dict]          # normalised answer-key items
    marking_scheme: dict            # {rubric_criteria, total_marks, partial_credit_enabled}
    teacher_guidance: str
    expected_question_count: int
    tenant_id: str
    subject: str = ""
    curriculum_context: str = ""


# ── Strategy result ───────────────────────────────────────────────────────────

@dataclass
class StrategyResult:
    question_responses: list[dict]  # QuestionResponse-compatible dicts
    proposed_total: float
    max_marks: float
    processing_pipeline: str        # omr | vision | deterministic | rubric_ai | mixed
    telemetry_events: list[dict]    # ProviderTelemetry.to_trace_event() dicts
    requires_review: bool
    unresolved_count: int
    objective_question_count: int
    ai_graded_count: int
    deterministic_count: int
    token_usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    estimated_cost_usd: float = 0.0


# ── Protocol ─────────────────────────────────────────────────────────────────

@runtime_checkable
class ProcessingStrategy(Protocol):
    strategy_name: str

    async def process(
        self,
        inp: StrategyInput,
        registry: "ProviderRegistry",
    ) -> StrategyResult:
        """
        Execute the full processing pipeline for one AssessmentSubmission.

        inp      — submission context (pages, answer key, rubric, metadata)
        registry — available providers (OMR, OCR, MCQ extractor, graders)
        """
        ...
