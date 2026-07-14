"""
ProviderRegistry — holds all processing provider instances.

Strategies receive a ProviderRegistry and call whichever providers they need.
New providers are registered here — not in the strategies or in LangGraph.

Default providers are all deterministic (suitable for testing and local dev).
Replace any provider by calling the appropriate register_* method at startup.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from services.gateway.ai.exam_marking.extraction.image_ocr import (
    DeterministicMCQExtractor,
    DeterministicOCRProvider,
)
from services.gateway.ai.exam_marking.grading.deterministic_grader import DeterministicGrader
from services.gateway.ai.exam_marking.omr.deterministic_omr import DeterministicOMRProvider

if TYPE_CHECKING:
    from services.gateway.ai.exam_marking.extraction.base import MCQExtractor, OCRProvider
    from services.gateway.ai.exam_marking.grading.rubric_grader import RubricAIGrader
    from services.gateway.ai.exam_marking.omr.base import OMRProvider


class ProviderRegistry:
    """
    Container for all processing providers.

    All providers default to deterministic implementations so tests and
    local development work without external services or API keys.
    """

    def __init__(
        self,
        omr_provider: "OMRProvider | None" = None,
        ocr_provider: "OCRProvider | None" = None,
        mcq_extractor: "MCQExtractor | None" = None,
        deterministic_grader: DeterministicGrader | None = None,
        rubric_grader: "RubricAIGrader | None" = None,
    ) -> None:
        self.omr: "OMRProvider" = omr_provider or DeterministicOMRProvider()
        self.ocr: "OCRProvider" = ocr_provider or DeterministicOCRProvider()
        self.mcq: "MCQExtractor" = mcq_extractor or DeterministicMCQExtractor()
        self.deterministic_grader: DeterministicGrader = deterministic_grader or DeterministicGrader()
        self.rubric_grader: "RubricAIGrader | None" = rubric_grader

    def register_omr(self, provider: "OMRProvider") -> None:
        """Register a production OMR provider (e.g. OpenCV, cloud OMR service)."""
        self.omr = provider

    def register_ocr(self, provider: "OCRProvider") -> None:
        """Register a production OCR provider (Tesseract, Cloud Vision, etc.)."""
        self.ocr = provider

    def register_mcq_extractor(self, extractor: "MCQExtractor") -> None:
        """Register a production MCQ answer extractor."""
        self.mcq = extractor

    def register_rubric_grader(self, grader: "RubricAIGrader") -> None:
        """Register a rubric AI grader backed by a real LLM provider."""
        self.rubric_grader = grader
