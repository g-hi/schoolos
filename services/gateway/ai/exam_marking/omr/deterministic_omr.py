"""
Deterministic OMR provider.

Returns structured synthetic results for all tests and local development.
No image-processing dependency required.

Future: replace with an OpenCV OMR engine or a cloud OMR adapter by
implementing OMRProvider and registering via ProviderRegistry.register_omr().
"""
from __future__ import annotations

from services.gateway.ai.exam_marking.omr.base import (
    OMRProvider,
    OMRQuestionResult,
    OMRResult,
    OMRTemplate,
)

# Deterministic answer pattern for synthetic tests: cycles A→B→C→D
_SYNTHETIC_ANSWERS = ["A", "B", "C", "D"]


class DeterministicOMRProvider:
    """
    Test/local implementation of OMRProvider.

    Returns a complete, structurally valid OMRResult.
    Confidence is always 0.98 so the happy-path test passes without review.
    One question per paper (Q3) is intentionally marked ambiguous to exercise
    the ambiguous-mark review path.
    """

    provider_name = "deterministic_omr"

    async def process(self, storage_key: str, template: OMRTemplate) -> OMRResult:
        results: list[OMRQuestionResult] = []

        for i in range(template.question_count):
            q_num = i + 1
            detected = _SYNTHETIC_ANSWERS[i % len(_SYNTHETIC_ANSWERS)]
            # Correct answer rotated one position ahead so Q1 is always wrong
            # (tests incorrect-answer path) and Q2 onwards are correct.
            correct = _SYNTHETIC_ANSWERS[(i + 1) % len(_SYNTHETIC_ANSWERS)]
            correct = detected if i % 2 == 0 else correct  # even Qs are correct
            awarded = template.options_per_question > 0 and detected == correct
            ambiguous = q_num == 3  # Q3 is synthetically ambiguous
            confidence = 0.72 if ambiguous else 0.98

            results.append(
                OMRQuestionResult(
                    question_number=q_num,
                    detected_answer=detected,
                    correct_answer=correct,
                    awarded_marks=1.0 if awarded else 0.0,
                    max_marks=1.0,
                    confidence=confidence,
                    ambiguous_mark=ambiguous,
                    review_required=ambiguous or confidence < 0.90,
                )
            )

        overall = sum(r.confidence for r in results) / max(len(results), 1)
        return OMRResult(
            question_results=results,
            provider_name=self.provider_name,
            overall_confidence=round(overall, 3),
        )
