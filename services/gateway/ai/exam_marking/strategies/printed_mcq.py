"""
Printed MCQ strategy — computer-vision extraction + deterministic grading.

No LLM involved.

Pipeline:
Image Processing → Question Region Detection →
Selected Answer Extraction → Deterministic Comparison → Teacher Review
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.gateway.ai.exam_marking.strategies.base import StrategyInput, StrategyResult
from services.gateway.ai.exam_marking.telemetry import TelemetryCollector

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry


class PrintedMCQStrategy:
    strategy_name = "printed_mcq"

    async def process(self, inp: StrategyInput, registry: "ProviderRegistry") -> StrategyResult:
        telemetry_events: list[dict] = []
        question_responses: list[dict] = []
        proposed_total = 0.0
        max_marks_total = 0.0
        objective_count = 0
        deterministic_count = 0

        ak_lookup: dict[int, dict] = {
            int(item.get("question_number", 0)): item
            for item in inp.answer_key
        }

        for page in inp.pages:
            storage_key: str = page.get("storage_key", "")
            page_number: int = int(page.get("page_number", 1))

            # Step 1: MCQ extraction
            collector = TelemetryCollector(
                provider_name=registry.mcq.provider_name,
                strategy_name=self.strategy_name,
                operation="mcq_answer_extraction",
            ).start()

            try:
                mcq_responses = await registry.mcq.extract(
                    storage_key,
                    question_count=inp.expected_question_count,
                    page_number=page_number,
                )
                t = collector.finish(
                    confidence=sum(r.confidence for r in mcq_responses) / max(len(mcq_responses), 1),
                    status="success",
                )
            except Exception as exc:
                t = collector.finish(status="failed", error_message=f"MCQ extraction failed: {type(exc).__name__}")
                telemetry_events.append(t.to_trace_event())
                continue

            telemetry_events.append(t.to_trace_event())

            # Step 2: Deterministic grading
            for mcq_r in mcq_responses:
                q_num = mcq_r.question_number
                ak_item = ak_lookup.get(q_num, {"max_marks": 1.0, "correct_answer": ""})
                max_q = float(ak_item.get("max_marks", 1.0))
                max_marks_total += max_q
                objective_count += 1

                grade_collector = TelemetryCollector(
                    provider_name="deterministic_grader",
                    strategy_name=self.strategy_name,
                    operation="deterministic_grading",
                    question_number=q_num,
                ).start()

                grading = registry.deterministic_grader.grade(
                    question_number=q_num,
                    extracted_answer=mcq_r.selected_option,
                    answer_key_item=ak_item,
                )

                gt = grade_collector.finish(confidence=grading.confidence, status="success")
                telemetry_events.append(gt.to_trace_event())

                proposed_total += grading.proposed_marks
                deterministic_count += 1

                question_responses.append({
                    "question_number": q_num,
                    "question_type": "mcq",
                    "extracted_answer": mcq_r.selected_option,
                    "extraction_confidence": mcq_r.confidence,
                    "source_page": page_number,
                    "source_reference": storage_key,
                    "correct_answer": ak_item.get("correct_answer", ""),
                    "proposed_marks": grading.proposed_marks,
                    "max_marks": max_q,
                    "grading_method": "vision",
                    "confidence": grading.confidence,
                    "ambiguous_mark": False,
                    "requires_teacher_review": grading.requires_teacher_review or mcq_r.review_required,
                    "evidence": grading.evidence,
                    "rubric_result": {},
                    "status": "proposed",
                    "manual_edit_required": False,
                })

        return StrategyResult(
            question_responses=question_responses,
            proposed_total=round(proposed_total, 2),
            max_marks=round(max_marks_total, 2),
            processing_pipeline="vision",
            telemetry_events=telemetry_events,
            requires_review=any(r.get("requires_teacher_review") for r in question_responses),
            unresolved_count=0,
            objective_question_count=objective_count,
            ai_graded_count=0,
            deterministic_count=deterministic_count,
        )
