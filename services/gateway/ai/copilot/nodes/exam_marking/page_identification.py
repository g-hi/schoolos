"""
Page Identification node.

Identifies page numbers and checks for missing pages.
V1: uses teacher-supplied page_number metadata.
Future: OCR-based or QR/barcode identification.

If expected_page_count > 1 and a page is missing, the node flags it
and blocks processing until the teacher resolves the gap.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def page_identification_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "page_identification")

    inp = state.get("structured_input", {})
    pages: list[dict] = inp.get("pages", [])
    expected_pages: int = int(inp.get("expected_pages_per_student", 1))

    found_page_numbers = sorted({int(p.get("page_number", 0)) for p in pages if p.get("accepted_for_processing", True)})
    expected_set = set(range(1, expected_pages + 1))
    missing = sorted(expected_set - set(found_page_numbers))

    inp["page_identification"] = {
        "found_pages": found_page_numbers,
        "expected_pages": expected_pages,
        "missing_pages": missing,
        "complete": len(missing) == 0,
    }

    if missing:
        state["errors"] = state.get("errors", []) + [f"missing_page_{p}" for p in missing]

    state["structured_input"] = inp
    finish_node(state, "page_identification", started)
    return state
