"""
Open-ended strategy — OCR + rubric-aware AI grading.

Pipeline:
OCR → Question Segmentation → Rubric-Aware AI Grading →
Confidence Scoring → Teacher Review

Sends ONE question at a time to the LLM.
Never sends the full exam.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.gateway.ai.exam_marking.strategies.base import StrategyInput, StrategyResult
from services.gateway.ai.exam_marking.telemetry import TelemetryCollector

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.provider_registry import ProviderRegistry

# Short-answer types that can bypass LLM if answer_key provides an exact match
_DETERMINISTIC_TYPES = {"true_false", "matching", "numeric", "fill_blank"}


class OpenEndedStrategy:
    strategy_name = "open_ended"

    async def process(self, inp: StrategyInput, registry: "ProviderRegistry") -> StrategyResult:
        telemetry_events: list[dict] = []
        question_responses: list[dict] = []
        proposed_total = 0.0
        max_marks_total = 0.0
        ai_graded_count = 0
        deterministic_count = 0
        token_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        estimated_cost = 0.0

        ak_lookup: dict[int, dict] = {
            int(item.get("question_number", 0)): item
            for item in inp.answer_key
        }
        rubric_criteria_lookup: dict[int, list[dict]] = {
            int(item.get("question_number", 0)): item.get("rubric_criteria", [])
            for item in inp.answer_key
        }

        # OCR all pages first
        extracted_texts: dict[int, str] = {}
        for page in inp.pages:
            storage_key: str = page.get("storage_key", "")
            page_number: int = int(page.get("page_number", 1))

            ocr_collector = TelemetryCollector(
                provider_name=registry.ocr.provider_name,
                strategy_name=self.strategy_name,
                operation="ocr_extraction",
            ).start()

            try:
                ocr_result = await registry.ocr.extract_text(storage_key, page_number)
                ot = ocr_collector.finish(confidence=ocr_result.overall_confidence, status="success")
                extracted_texts[page_number] = ocr_result.text
            except Exception as exc:
                ot = ocr_collector.finish(status="failed", error_message=f"OCR failed: {type(exc).__name__}")
                extracted_texts[page_number] = ""

            telemetry_events.append(ot.to_trace_event())

        # Grade question by question.
        # Iterate over the actual question numbers present in the answer key
        # rather than a sequential range.  This is critical for MixedPaperStrategy
        # which delegates a *subset* of questions (e.g. only Q2, Q3) whose numbers
        # do not start at 1.  Using range(1, N+1) would misalign answers and create
        # duplicate question-number entries in the combined result.
        full_text = "\n".join(extracted_texts.values())
        q_numbers = sorted(ak_lookup.keys()) if ak_lookup else list(range(1, inp.expected_question_count + 1))
        for q_num in q_numbers:
            ak_item = ak_lookup.get(q_num, {"max_marks": 1.0})
            max_q = float(ak_item.get("max_marks", 1.0))
            max_marks_total += max_q
            q_type = ak_item.get("question_type", "short_answer")

            # Try deterministic path first (no LLM)
            if q_type in _DETERMINISTIC_TYPES and ak_item.get("correct_answer"):
                student_answer = self._extract_answer_for_question(full_text, q_num)
                det_collector = TelemetryCollector(
                    provider_name="deterministic_grader",
                    strategy_name=self.strategy_name,
                    operation="deterministic_grading",
                    question_number=q_num,
                ).start()

                grading = registry.deterministic_grader.grade(
                    question_number=q_num,
                    extracted_answer=student_answer,
                    answer_key_item=ak_item,
                )
                dt = det_collector.finish(confidence=grading.confidence, status="success")
                telemetry_events.append(dt.to_trace_event())

                proposed_total += grading.proposed_marks
                deterministic_count += 1
                question_responses.append({
                    "question_number": q_num,
                    "question_type": q_type,
                    "extracted_answer": student_answer,
                    "extraction_confidence": 0.97,
                    "source_page": 1,
                    "source_reference": "",
                    "correct_answer": ak_item.get("correct_answer", ""),
                    "proposed_marks": grading.proposed_marks,
                    "max_marks": max_q,
                    "grading_method": "deterministic",
                    "confidence": grading.confidence,
                    "ambiguous_mark": False,
                    "requires_teacher_review": grading.requires_teacher_review,
                    "evidence": grading.evidence,
                    "rubric_result": {},
                    "status": "proposed",
                    "manual_edit_required": False,
                })
                continue

            # AI rubric grading path
            if registry.rubric_grader is None:
                # No LLM configured — mark as unresolved
                question_responses.append({
                    "question_number": q_num,
                    "question_type": q_type,
                    "extracted_answer": "",
                    "extraction_confidence": 0.0,
                    "source_page": 1,
                    "source_reference": "",
                    "correct_answer": "",
                    "proposed_marks": 0.0,
                    "max_marks": max_q,
                    "grading_method": "rubric_ai",
                    "confidence": 0.0,
                    "ambiguous_mark": False,
                    "requires_teacher_review": True,
                    "evidence": {"reason": "no_rubric_grader_configured"},
                    "rubric_result": {},
                    "status": "unresolved",
                    "manual_edit_required": True,
                })
                continue

            student_answer = self._extract_answer_for_question(full_text, q_num)
            rubric_criteria = rubric_criteria_lookup.get(q_num, [])
            if not rubric_criteria:
                rubric_criteria = [{"criterion": "Content", "max_marks": max_q, "description": ""}]

            ai_collector = TelemetryCollector(
                provider_name=registry.rubric_grader._provider.provider_name,
                strategy_name=self.strategy_name,
                operation="rubric_ai_grading",
                question_number=q_num,
            ).start()

            try:
                rubric_result = await registry.rubric_grader.grade(
                    question_number=q_num,
                    question_text=ak_item.get("question_text", f"Question {q_num}"),
                    student_answer=student_answer,
                    rubric_criteria=rubric_criteria,
                    max_marks=max_q,
                    teacher_guidance=inp.teacher_guidance,
                    curriculum_context=inp.curriculum_context,
                )
                at = ai_collector.finish(
                    confidence=rubric_result.confidence,
                    token_usage=rubric_result.token_usage,
                    status="success",
                )
            except Exception as exc:
                at = ai_collector.finish(status="failed", error_message=f"Rubric AI failed: {type(exc).__name__}")
                telemetry_events.append(at.to_trace_event())
                question_responses.append({
                    "question_number": q_num,
                    "question_type": q_type,
                    "extracted_answer": student_answer,
                    "extraction_confidence": 0.5,
                    "source_page": 1,
                    "source_reference": "",
                    "correct_answer": "",
                    "proposed_marks": 0.0,
                    "max_marks": max_q,
                    "grading_method": "rubric_ai",
                    "confidence": 0.0,
                    "ambiguous_mark": False,
                    "requires_teacher_review": True,
                    "evidence": {"reason": "ai_grading_failed"},
                    "rubric_result": {},
                    "status": "unresolved",
                    "manual_edit_required": True,
                })
                continue

            telemetry_events.append(at.to_trace_event())

            # Accumulate tokens
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                token_usage[k] = token_usage.get(k, 0) + rubric_result.token_usage.get(k, 0)

            proposed_total += rubric_result.proposed_marks
            ai_graded_count += 1

            question_responses.append({
                "question_number": q_num,
                "question_type": q_type,
                "extracted_answer": student_answer,
                "extraction_confidence": 0.85,
                "source_page": 1,
                "source_reference": "",
                "correct_answer": "",
                "proposed_marks": rubric_result.proposed_marks,
                "max_marks": max_q,
                "grading_method": "rubric_ai",
                "confidence": rubric_result.confidence,
                "ambiguous_mark": False,
                "requires_teacher_review": True,
                "evidence": {"summary": rubric_result.evidence[:200]},
                "rubric_result": {
                    "criteria": [
                        {
                            "criterion": cr.criterion,
                            "awarded": cr.awarded,
                            "max": cr.max,
                            "evidence": cr.evidence,
                        }
                        for cr in rubric_result.criteria_results
                    ],
                    "feedback": rubric_result.feedback,
                },
                "status": "proposed",
                "manual_edit_required": False,
            })

        return StrategyResult(
            question_responses=question_responses,
            proposed_total=round(proposed_total, 2),
            max_marks=round(max_marks_total, 2),
            processing_pipeline="rubric_ai" if ai_graded_count > 0 else "deterministic",
            telemetry_events=telemetry_events,
            requires_review=True,  # always True for open-ended
            unresolved_count=sum(1 for r in question_responses if r.get("status") == "unresolved"),
            objective_question_count=deterministic_count,
            ai_graded_count=ai_graded_count,
            deterministic_count=deterministic_count,
            token_usage=token_usage,
        )

    @staticmethod
    def _extract_answer_for_question(full_text: str, question_number: int) -> str:
        """
        Naive question segmentation — looks for 'Q{n}:' pattern.
        V1 returns the full text for single-question papers.
        Future: implement proper question boundary detection.
        """
        import re
        pattern = rf"Q{question_number}[:\.\s]+(.+?)(?=Q{question_number + 1}[:\.\s]|$)"
        match = re.search(pattern, full_text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()[:500]  # cap to 500 chars
        return full_text.strip()[:500]
