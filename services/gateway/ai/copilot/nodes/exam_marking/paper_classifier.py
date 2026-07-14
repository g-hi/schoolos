"""
Paper Type Classifier node.

Teacher-selected paper_type always overrides automatic classification.
V1: automatic classification is a stub (always returns teacher selection).
Future: replace _auto_classify() with computer-vision paper-type detection.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

_VALID_TYPES = {"scantron", "printed_mcq", "mixed", "open_ended"}


async def paper_classifier_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "paper_classifier")

    inp = state.get("structured_input", {})
    teacher_selected: str = inp.get("paper_type", "open_ended").lower().strip()

    # Teacher selection always wins
    classified = teacher_selected if teacher_selected in _VALID_TYPES else "open_ended"

    # Future automatic classification hook
    if classified == "open_ended" and not teacher_selected:
        classified = _auto_classify(inp.get("pages", []))

    inp["paper_type_classified"] = classified
    state["structured_input"] = inp

    finish_node(state, "paper_classifier", started)
    return state


def _auto_classify(pages: list[dict]) -> str:
    """
    Placeholder for future computer-vision paper-type detection.
    V1: returns 'open_ended' (safest default — uses full review path).
    Future: analyse page image to detect bubble patterns, MCQ layout, etc.
    """
    return "open_ended"
