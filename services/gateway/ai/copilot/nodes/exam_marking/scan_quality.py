"""
Scan Quality Validation node.

Runs ImageQualityChecker on every page in structured_input.pages.
Pages that fail quality checks are flagged with retake_required=True.

If ALL pages fail quality checks, the workflow routes to fallback.
If SOME pages fail, they are flagged and the rest proceed.
Teacher is notified of retake-required pages.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node
from services.gateway.ai.exam_marking.quality.image_quality import ImageQualityChecker

_checker = ImageQualityChecker()


async def scan_quality_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "scan_quality")

    inp = state.get("structured_input", {})
    pages: list[dict] = inp.get("pages", [])

    if not pages:
        inp["quality_summary"] = {"all_accepted": True, "retake_required_pages": [], "checked": 0}
        state["structured_input"] = inp
        finish_node(state, "scan_quality", started)
        return state

    retake_required: list[int] = []
    quality_results: list[dict] = []

    for page in pages:
        storage_key: str = page.get("storage_key", "")
        source: str = page.get("source", "upload")
        result = _checker.check(storage_key, source)

        page["quality_score"] = result.quality_score
        page["quality_warnings"] = result.warnings
        page["retake_required"] = result.retake_required
        page["accepted_for_processing"] = result.accepted_for_processing

        if result.retake_required:
            retake_required.append(page.get("page_number", 0))

        quality_results.append({
            "page_number": page.get("page_number", 0),
            "quality_score": result.quality_score,
            "warnings": result.warnings,
            "retake_required": result.retake_required,
        })

    all_accepted = len(retake_required) == 0
    inp["quality_results"] = quality_results
    inp["quality_summary"] = {
        "all_accepted": all_accepted,
        "retake_required_pages": retake_required,
        "checked": len(pages),
    }
    state["structured_input"] = inp

    finish_node(state, "scan_quality", started)
    return state


def route_after_scan_quality(state: SchoolOSAIState) -> str:
    inp = state.get("structured_input", {})
    summary = inp.get("quality_summary", {})
    retake = summary.get("retake_required_pages", [])
    pages = inp.get("pages", [])

    # If ALL pages require retake and there are pages → fail
    if retake and len(retake) == len(pages) and pages:
        state["final_response"] = {
            "status": "needs_clarification",
            "request_id": state.get("request_id", ""),
            "conversation_id": state.get("conversation_id"),
            "intent": state.get("intent"),
            "message": (
                f"All {len(pages)} uploaded pages failed quality checks "
                f"(pages: {retake}). Please retake the photos."
            ),
            "missing_fields": [f"page_{p}_retake" for p in retake],
            "execution": {
                "workflow": "exam_marking",
                "current_step": "scan_quality",
                "validation_passed": False,
                "retry_count": state.get("retry_count", 0),
                "tenant_slug": state.get("tenant_slug"),
            },
        }
        return "fallback"

    return "page_identification"
