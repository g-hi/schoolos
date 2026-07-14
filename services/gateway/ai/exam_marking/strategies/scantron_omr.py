"""
Scantron / Bubble-sheet OMR strategy.

Pipeline: OMR only — zero LLM calls.

Image Alignment → Template Detection → Bubble Detection →
Filled Bubble Recognition → Answer Extraction →
Answer Key Comparison → Score Calculation → Teacher Review queue
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.gateway.ai.exam_marking.omr.base import OMRTemplate
from services.gateway.ai.exam_marking.strategies.base import StrategyInput, StrategyResult
from services.gateway.ai.exam_marking.telemetry import TelemetryCollector

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry

# Confidence below this triggers review_required on individual questions.
_REVIEW_THRESHOLD = 0.90


class ScantronOMRStrategy:
    strategy_name = "scantron_omr"

    async def process(self, inp: StrategyInput, registry: "ProviderRegistry") -> StrategyResult:
        telemetry_events: list[dict] = []
        question_responses: list[dict] = []
        proposed_total = 0.0
        max_marks_total = 0.0
        unresolved_count = 0
        objective_count = 0

        # Build answer key lookup {question_number → answer_key_item}
        ak_lookup: dict[int, dict] = {
            int(item.get("question_number", 0)): item
            for item in inp.answer_key
        }

        template = OMRTemplate(
            question_count=inp.expected_question_count,
            options_per_question=4,
        )

        for page in inp.pages:
            storage_key: str = page.get("storage_key", "")
            page_number: int = int(page.get("page_number", 1))

            collector = TelemetryCollector(
                provider_name=registry.omr.provider_name,
                strategy_name=self.strategy_name,
                operation="omr_bubble_detection",
            ).start()

            try:
                omr_result = await registry.omr.process(storage_key, template)
                t = collector.finish(
                    confidence=omr_result.overall_confidence,
                    status="success",
                )
            except Exception as exc:
                t = collector.finish(status="failed", error_message=f"OMR failed: {type(exc).__name__}")
                telemetry_events.append(t.to_trace_event())
                continue

            telemetry_events.append(t.to_trace_event())

            for qr in omr_result.question_results:
                q_num = qr.question_number
                ak_item = ak_lookup.get(q_num, {})
                max_q = float(ak_item.get("max_marks", 1.0))
                max_marks_total += max_q
                objective_count += 1
                awarded = qr.awarded_marks
                proposed_total += awarded
                if qr.ambiguous_mark or qr.review_required:
                    unresolved_count += 1 if qr.ambiguous_mark else 0

                question_responses.append({
                    "question_number": q_num,
                    "question_type": "mcq",
                    "extracted_answer": qr.detected_answer,
                    "extraction_confidence": qr.confidence,
                    "source_page": page_number,
                    "source_reference": storage_key,
                    "correct_answer": qr.correct_answer,
                    "proposed_marks": awarded,
                    "max_marks": max_q,
                    "grading_method": "omr",
                    "confidence": qr.confidence,
                    "ambiguous_mark": qr.ambiguous_mark,
                    "requires_teacher_review": qr.review_required,
                    "evidence": {"omr_detected": qr.detected_answer, "correct": qr.correct_answer},
                    "rubric_result": {},
                    "status": "unresolved" if qr.ambiguous_mark else "proposed",
                    "manual_edit_required": qr.ambiguous_mark,
                })

        return StrategyResult(
            question_responses=question_responses,
            proposed_total=round(proposed_total, 2),
            max_marks=round(max_marks_total, 2),
            processing_pipeline="omr",
            telemetry_events=telemetry_events,
            requires_review=any(r.get("requires_teacher_review") for r in question_responses),
            unresolved_count=unresolved_count,
            objective_question_count=objective_count,
            ai_graded_count=0,
            deterministic_count=objective_count - unresolved_count,
        )
