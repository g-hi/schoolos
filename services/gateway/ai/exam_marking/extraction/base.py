"""
Document extraction protocols.

All extraction providers implement one of these protocols so the processing
strategies remain provider-agnostic.  Future providers — cloud OCR, local
Tesseract, Arabic OCR, Math OCR, handwriting recognition — register in
ProviderRegistry and implement the appropriate protocol here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ── OCR ──────────────────────────────────────────────────────────────────────

@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class WordResult:
    text: str
    confidence: float
    bbox: BoundingBox | None = None


@dataclass
class OCRResult:
    text: str
    words: list[WordResult]
    overall_confidence: float
    provider_name: str
    page_number: int = 1
    language_detected: str = "en"


@runtime_checkable
class OCRProvider(Protocol):
    provider_name: str

    async def extract_text(self, storage_key: str, page_number: int = 1) -> OCRResult:
        """Extract text from a stored image or document page."""
        ...


# ── MCQ / Printed-Answer extraction ──────────────────────────────────────────

@dataclass
class MCQResponse:
    question_number: int
    selected_option: str          # "A", "B", "C", "D", or raw text
    detection_method: str         # tick | circle | underline | shaded | written | matching
    confidence: float
    review_required: bool = False


@runtime_checkable
class MCQExtractor(Protocol):
    provider_name: str

    async def extract(
        self,
        storage_key: str,
        question_count: int,
        page_number: int = 1,
    ) -> list[MCQResponse]:
        """Detect and extract student-selected answers from a printed MCQ page."""
        ...


# ── Document text extraction (PDF / DOCX / TXT) ───────────────────────────────

@dataclass
class DocumentPage:
    page_number: int
    text: str
    confidence: float = 1.0


@dataclass
class DocumentExtractionResult:
    pages: list[DocumentPage]
    provider_name: str
    file_type: str


@runtime_checkable
class DocumentExtractor(Protocol):
    provider_name: str

    async def extract(self, storage_key: str, file_type: str) -> DocumentExtractionResult:
        """Extract text content from PDF, DOCX, or TXT files."""
        ...
