"""
Deterministic OCR provider — returns structured synthetic results.

Used in all tests and local development.  Replace with a real OCR adapter
(Tesseract, Google Cloud Vision, Azure Document Intelligence) by registering
a new OCRProvider implementation in ProviderRegistry.
"""
from __future__ import annotations

from services.gateway.ai.exam_marking.extraction.base import OCRResult, WordResult


class DeterministicOCRProvider:
    provider_name = "deterministic_ocr"

    async def extract_text(self, storage_key: str, page_number: int = 1) -> OCRResult:
        # Synthetic response for local development and testing.
        synthetic_text = (
            "Q1: The process by which plants make food using sunlight is photosynthesis.\n"
            "Q2: Water boils at 100 degrees Celsius at sea level.\n"
            "Q3: The mitochondria is the powerhouse of the cell.\n"
        )
        words = [
            WordResult(text=word, confidence=0.97)
            for word in synthetic_text.split()
        ]
        return OCRResult(
            text=synthetic_text,
            words=words,
            overall_confidence=0.97,
            provider_name=self.provider_name,
            page_number=page_number,
        )


class DeterministicMCQExtractor:
    provider_name = "deterministic_mcq"

    async def extract(
        self,
        storage_key: str,
        question_count: int,
        page_number: int = 1,
    ):
        from services.gateway.ai.exam_marking.extraction.base import MCQResponse

        # Deterministic answers: Q1→B, Q2→A, Q3→C, cycling for larger papers
        options = ["B", "A", "C", "D", "A", "B"]
        return [
            MCQResponse(
                question_number=i + 1,
                selected_option=options[i % len(options)],
                detection_method="written",
                confidence=0.96,
            )
            for i in range(question_count)
        ]


class DeterministicDocumentExtractor:
    provider_name = "deterministic_doc"

    async def extract(self, storage_key: str, file_type: str):
        from services.gateway.ai.exam_marking.extraction.base import (
            DocumentExtractionResult,
            DocumentPage,
        )
        return DocumentExtractionResult(
            pages=[
                DocumentPage(
                    page_number=1,
                    text="Q1: Photosynthesis\nQ2: 100 degrees\nQ3: Mitochondria",
                )
            ],
            provider_name=self.provider_name,
            file_type=file_type,
        )
