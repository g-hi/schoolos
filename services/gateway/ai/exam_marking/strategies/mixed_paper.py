"""
Mixed paper strategy — combines OMR/Vision for objective questions
and OCR + Rubric AI for open-ended questions.

Routes each question to the cheapest effective method:
    True/False, MCQ, Matching, Numeric → deterministic or vision
    Short Answer, Essay → OCR + Rubric AI
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.gateway.ai.exam_marking.strategies.base import StrategyInput, StrategyResult
from services.gateway.ai.exam_marking.strategies.open_ended import OpenEndedStrategy
from services.gateway.ai.exam_marking.strategies.printed_mcq import PrintedMCQStrategy

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry

_OBJECTIVE_TYPES = {"mcq", "true_false", "matching", "numeric", "fill_blank"}


class MixedPaperStrategy:
    strategy_name = "mixed"

    async def process(self, inp: StrategyInput, registry: "ProviderRegistry") -> StrategyResult:
        # Split answer key into objective and open-ended subsets
        objective_ak = [
            item for item in inp.answer_key
            if item.get("question_type", "short_answer") in _OBJECTIVE_TYPES
        ]
        open_ended_ak = [
            item for item in inp.answer_key
            if item.get("question_type", "short_answer") not in _OBJECTIVE_TYPES
        ]

        telemetry_events: list[dict] = []
        question_responses: list[dict] = []
        token_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # Process objective questions with PrintedMCQStrategy
        if objective_ak:
            obj_inp = StrategyInput(
                session_id=inp.session_id,
                submission_id=inp.submission_id,
                paper_type="printed_mcq",
                pages=inp.pages,
                answer_key=objective_ak,
                marking_scheme=inp.marking_scheme,
                teacher_guidance=inp.teacher_guidance,
                expected_question_count=len(objective_ak),
                tenant_id=inp.tenant_id,
                subject=inp.subject,
                curriculum_context=inp.curriculum_context,
            )
            obj_result = await PrintedMCQStrategy().process(obj_inp, registry)
            question_responses.extend(obj_result.question_responses)
            telemetry_events.extend(obj_result.telemetry_events)

        # Process open-ended questions with OpenEndedStrategy
        if open_ended_ak:
            oe_inp = StrategyInput(
                session_id=inp.session_id,
                submission_id=inp.submission_id,
                paper_type="open_ended",
                pages=inp.pages,
                answer_key=open_ended_ak,
                marking_scheme=inp.marking_scheme,
                teacher_guidance=inp.teacher_guidance,
                expected_question_count=len(open_ended_ak),
                tenant_id=inp.tenant_id,
                subject=inp.subject,
                curriculum_context=inp.curriculum_context,
            )
            oe_result = await OpenEndedStrategy().process(oe_inp, registry)
            question_responses.extend(oe_result.question_responses)
            telemetry_events.extend(oe_result.telemetry_events)
            for k in token_usage:
                token_usage[k] += oe_result.token_usage.get(k, 0)

        # Aggregate totals
        proposed_total = sum(r.get("proposed_marks", 0.0) for r in question_responses)
        max_marks = sum(r.get("max_marks", 0.0) for r in question_responses)
        ai_graded = sum(1 for r in question_responses if r.get("grading_method") == "rubric_ai")
        det_count = sum(1 for r in question_responses if r.get("grading_method") in ("deterministic", "vision", "omr"))

        return StrategyResult(
            question_responses=question_responses,
            proposed_total=round(proposed_total, 2),
            max_marks=round(max_marks, 2),
            processing_pipeline="mixed",
            telemetry_events=telemetry_events,
            requires_review=any(r.get("requires_teacher_review") for r in question_responses),
            unresolved_count=sum(1 for r in question_responses if r.get("status") == "unresolved"),
            objective_question_count=det_count,
            ai_graded_count=ai_graded,
            deterministic_count=det_count,
            token_usage=token_usage,
        )
