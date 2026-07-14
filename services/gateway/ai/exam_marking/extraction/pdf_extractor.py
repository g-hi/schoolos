"""
PDF and document text extraction provider (deterministic placeholder).

Future: swap DeterministicDocumentExtractor for a real adapter that calls
PyMuPDF, pdfplumber, python-docx, or a cloud Document AI service.
"""
from services.gateway.ai.exam_marking.extraction.image_ocr import DeterministicDocumentExtractor

__all__ = ["DeterministicDocumentExtractor"]
