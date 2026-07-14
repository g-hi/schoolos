"""
OMR (Optical Mark Recognition) provider protocol and data types.

SchoolOS never uses an LLM for Scantron or bubble-sheet papers.
All OMR providers implement the OMRProvider protocol below.

Future providers:
    - OpenCV-based local OMR engine
    - Cloud OMR service adapter (GradeCam, Remark Office OMR, etc.)
Register them via ProviderRegistry.register_omr().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OMRTemplate:
    """Describes the layout of a bubble sheet so the provider knows
    how many questions to look for and how the bubbles are arranged."""
    question_count: int
    options_per_question: int = 4           # A, B, C, D
    version: str = "A"                      # support A/B versions
    student_id_bubbles: bool = False        # detect student ID rows
    numeric_bubbles: bool = False           # for numeric answer sheets
    layout_hints: dict = field(default_factory=dict)


@dataclass
class OMRQuestionResult:
    question_number: int
    detected_answer: str        # "A", "B", "C", "D", or "" if blank
    correct_answer: str
    awarded_marks: float
    max_marks: float
    confidence: float           # 0.0 – 1.0
    ambiguous_mark: bool        # multiple bubbles filled, erased mark, etc.
    review_required: bool       # True if confidence < threshold


@dataclass
class OMRResult:
    question_results: list[OMRQuestionResult]
    provider_name: str
    overall_confidence: float
    student_id_detected: str | None = None  # future: student-ID bubble row


@runtime_checkable
class OMRProvider(Protocol):
    provider_name: str

    async def process(self, storage_key: str, template: OMRTemplate) -> OMRResult:
        """
        Process a scanned bubble-sheet image and return per-question results.

        storage_key  — path / reference to the scanned image (not raw binary)
        template     — describes the expected layout of the answer sheet
        """
        ...
