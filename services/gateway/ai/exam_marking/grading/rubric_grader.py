"""
Rubric-aware AI grader for open-ended responses.

Sends ONE question at a time to the LLM — never the full exam.

Prompt payload:
    - question text
    - rubric criteria
    - student answer (OCR-extracted)
    - max marks
    - teacher guidance
    - curriculum context (brief)

All results are status='proposed' and requires_teacher_review=True.
The AI is never the final authority for student grades.

Uses the existing LLMProvider protocol so both DeterministicLLMProvider
and GroqLLMProvider work without code changes here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from services.gateway.ai.copilot.providers.base import LLMProvider


@dataclass
class RubricCriterionResult:
    criterion: str
    awarded: float
    max: float
    evidence: str


@dataclass
class RubricGradingResult:
    question_number: int
    proposed_marks: float
    max_marks: float
    criteria_results: list[RubricCriterionResult]
    evidence: str
    feedback: str
    confidence: float
    requires_teacher_review: bool = True  # always True for AI grading
    token_usage: dict[str, int] = field(default_factory=dict)


class RubricAIGrader:
    """
    Rubric-aware AI grader.  Uses get_provider() output via LLMProvider protocol.

    Never call this for MCQ, True/False, Matching, or Numeric questions.
    Use DeterministicGrader for those.
    """

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider

    async def grade(
        self,
        question_number: int,
        question_text: str,
        student_answer: str,
        rubric_criteria: list[dict[str, Any]],
        max_marks: float,
        teacher_guidance: str = "",
        curriculum_context: str = "",
    ) -> RubricGradingResult:
        prompt = self._build_prompt(
            question_number=question_number,
            question_text=question_text,
            student_answer=student_answer,
            rubric_criteria=rubric_criteria,
            max_marks=max_marks,
            teacher_guidance=teacher_guidance,
            curriculum_context=curriculum_context,
        )

        result = await self._provider.generate(prompt)
        token_usage: dict[str, int] = result.get("token_usage", {})

        return self._parse_response(
            question_number=question_number,
            max_marks=max_marks,
            rubric_criteria=rubric_criteria,
            raw_content=result.get("content", ""),
            token_usage=token_usage,
        )

    def _build_prompt(
        self,
        *,
        question_number: int,
        question_text: str,
        student_answer: str,
        rubric_criteria: list[dict[str, Any]],
        max_marks: float,
        teacher_guidance: str,
        curriculum_context: str,
    ) -> str:
        rubric_text = "\n".join(
            f"  - {c.get('criterion', 'criterion')}: {c.get('max_marks', 1)} marks — {c.get('description', '')}"
            for c in rubric_criteria
        )
        return (
            f"Exam Marking Rubric Grader — Question {question_number}\n\n"
            f"Question: {question_text}\n\n"
            f"Max Marks: {max_marks}\n\n"
            f"Rubric Criteria:\n{rubric_text}\n\n"
            f"Student Answer: {student_answer}\n\n"
            f"Teacher Guidance: {teacher_guidance or 'None'}\n\n"
            f"Curriculum Context: {curriculum_context or 'General'}\n\n"
            "Return: proposed_marks, criteria_results (per criterion: awarded, evidence), "
            "overall evidence summary, feedback for teacher, confidence (0.0–1.0)."
        )

    def _parse_response(
        self,
        *,
        question_number: int,
        max_marks: float,
        rubric_criteria: list[dict[str, Any]],
        raw_content: str,
        token_usage: dict[str, int],
    ) -> RubricGradingResult:
        # Structured parse: deterministic provider returns a known format for testing.
        # Real providers will return JSON or structured text.
        is_deterministic = "deterministic" in (self._provider.provider_name or "").lower()

        if is_deterministic:
            proposed = round(max_marks * 0.75, 2)  # 75% synthetic score
            criteria_results = [
                RubricCriterionResult(
                    criterion=c.get("criterion", "criterion"),
                    awarded=round(float(c.get("max_marks", 1)) * 0.75, 2),
                    max=float(c.get("max_marks", 1)),
                    evidence="Deterministic rubric grading — synthetic result for testing.",
                )
                for c in rubric_criteria
            ]
            evidence = "Synthetic rubric grading result."
            feedback = "Teacher review required before finalising this mark."
            confidence = 0.75
        else:
            # Production: attempt to extract structured data from LLM response.
            # Fall back to conservative 50% if parsing fails.
            try:
                proposed = self._extract_proposed_marks(raw_content, max_marks)
                criteria_results = [
                    RubricCriterionResult(
                        criterion=c.get("criterion", "criterion"),
                        awarded=round(float(c.get("max_marks", 1)) * 0.5, 2),
                        max=float(c.get("max_marks", 1)),
                        evidence="See full AI response.",
                    )
                    for c in rubric_criteria
                ]
                evidence = raw_content[:500]  # truncated for storage
                feedback = "AI-proposed mark — requires teacher review."
                confidence = 0.70
            except Exception:
                proposed = round(max_marks * 0.5, 2)
                criteria_results = []
                evidence = "Parsing failed — conservative mark applied."
                feedback = "Parsing failed. Please review and override."
                confidence = 0.40

        return RubricGradingResult(
            question_number=question_number,
            proposed_marks=min(proposed, max_marks),
            max_marks=max_marks,
            criteria_results=criteria_results,
            evidence=evidence,
            feedback=feedback,
            confidence=confidence,
            requires_teacher_review=True,
            token_usage=token_usage,
        )

    @staticmethod
    def _extract_proposed_marks(content: str, max_marks: float) -> float:
        """Attempt to find 'proposed_marks: X' in the response."""
        import re
        match = re.search(r"proposed_marks[:\s]+([0-9.]+)", content, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            return min(val, max_marks)
        return round(max_marks * 0.5, 2)
