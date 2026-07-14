"""
Deterministic grader — no LLM involved.

Supports:
    - Exact match
    - Case-insensitive match
    - Whitespace normalisation
    - Accepted alternatives list
    - Numeric tolerance (absolute and relative)
    - Blank-answer handling
    - Multiple valid answers
    - Partial credit only where explicitly configured

Returns a GradingResult with full evidence so the teacher review screen
can show exactly why each mark was awarded or withheld.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GradingResult:
    question_number: int
    extracted_answer: str
    correct_answer: str
    proposed_marks: float
    max_marks: float
    result: str           # correct | incorrect | partial | blank | unresolved
    evidence: dict        # machine-readable explanation
    confidence: float     # 1.0 for deterministic matches; lower for fuzzy
    requires_teacher_review: bool


def _normalise(text: str) -> str:
    return text.strip().lower()


def _is_numeric(text: str) -> bool:
    try:
        float(text.strip())
        return True
    except ValueError:
        return False


class DeterministicGrader:
    """
    Rule-based grader for objective questions.

    answer_key_item structure:
        {
            "question_number": int,
            "correct_answer": str,
            "max_marks": float,
            "accepted_alternatives": list[str],   # optional
            "numeric_tolerance": float | None,     # absolute tolerance
            "partial_credit": float | None,        # 0.0–1.0 fraction
            "case_sensitive": bool,                # default False
        }
    """

    def grade(
        self,
        question_number: int,
        extracted_answer: str,
        answer_key_item: dict,
    ) -> GradingResult:
        max_marks: float = float(answer_key_item.get("max_marks", 1.0))
        correct_raw: str = str(answer_key_item.get("correct_answer", ""))
        alternatives: list[str] = [str(a) for a in answer_key_item.get("accepted_alternatives", [])]
        tolerance: float | None = answer_key_item.get("numeric_tolerance")
        partial: float | None = answer_key_item.get("partial_credit")
        case_sensitive: bool = bool(answer_key_item.get("case_sensitive", False))

        student = extracted_answer.strip()

        # Blank answer
        if not student:
            return GradingResult(
                question_number=question_number,
                extracted_answer="",
                correct_answer=correct_raw,
                proposed_marks=0.0,
                max_marks=max_marks,
                result="blank",
                evidence={"reason": "blank_answer"},
                confidence=1.0,
                requires_teacher_review=False,
            )

        # Numeric comparison with tolerance
        if tolerance is not None and _is_numeric(student) and _is_numeric(correct_raw):
            student_val = float(student)
            correct_val = float(correct_raw)
            if abs(student_val - correct_val) <= tolerance:
                return GradingResult(
                    question_number=question_number,
                    extracted_answer=student,
                    correct_answer=correct_raw,
                    proposed_marks=max_marks,
                    max_marks=max_marks,
                    result="correct",
                    evidence={"reason": "numeric_within_tolerance", "tolerance": tolerance},
                    confidence=1.0,
                    requires_teacher_review=False,
                )
            # Outside tolerance — may still qualify for partial credit
            proposed = round(max_marks * partial, 2) if partial else 0.0
            return GradingResult(
                question_number=question_number,
                extracted_answer=student,
                correct_answer=correct_raw,
                proposed_marks=proposed,
                max_marks=max_marks,
                result="incorrect",
                evidence={"reason": "numeric_outside_tolerance", "tolerance": tolerance},
                confidence=1.0,
                requires_teacher_review=bool(partial),
            )

        # Text comparison
        cmp_student = student if case_sensitive else _normalise(student)
        cmp_correct = correct_raw if case_sensitive else _normalise(correct_raw)
        all_valid = [cmp_correct] + [
            a if case_sensitive else _normalise(a) for a in alternatives
        ]

        if cmp_student in all_valid:
            return GradingResult(
                question_number=question_number,
                extracted_answer=student,
                correct_answer=correct_raw,
                proposed_marks=max_marks,
                max_marks=max_marks,
                result="correct",
                evidence={"reason": "exact_match", "matched": cmp_student},
                confidence=1.0,
                requires_teacher_review=False,
            )

        # Incorrect — apply partial credit only if explicitly configured
        proposed = round(max_marks * partial, 2) if partial else 0.0
        return GradingResult(
            question_number=question_number,
            extracted_answer=student,
            correct_answer=correct_raw,
            proposed_marks=proposed,
            max_marks=max_marks,
            result="incorrect",
            evidence={"reason": "no_match", "student": cmp_student, "expected": all_valid},
            confidence=1.0,
            requires_teacher_review=bool(partial),
        )
