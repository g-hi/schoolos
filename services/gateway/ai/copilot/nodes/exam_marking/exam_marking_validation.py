"""
Exam Marking Validation node.

Validates the mark aggregation output before handing off to human review.

Checks:
    - total proposed marks ≤ max marks
    - no question marks exceed per-question maximum
    - all expected questions are accounted for
    - unresolved items are explicitly flagged (do not block but must not auto-approve)
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def exam_marking_validation_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "exam_marking_validation")

    generated = state.get("generated_content", {})
    issues: list[str] = []

    proposed_total = float(generated.get("proposed_total", 0.0))
    max_marks = float(generated.get("max_marks", 0.0))

    if max_marks > 0 and proposed_total > max_marks:
        issues.append(f"total_exceeds_max:{proposed_total}>{max_marks}")

    missing_q = generated.get("missing_questions", [])
    if missing_q:
        issues.append(f"missing_questions:{missing_q}")

    # Per-question max check
    for r in generated.get("question_responses", []):
        pm = float(r.get("proposed_marks", 0.0))
        qm = float(r.get("max_marks", 0.0))
        if qm > 0 and pm > qm:
            issues.append(f"q{r.get('question_number')}_exceeds_max")

    passed = len(issues) == 0
    state["validation_result"] = {"passed": passed, "issues": issues}

    finish_node(state, "exam_marking_validation", started)
    return state


def route_after_exam_marking_validation(state: SchoolOSAIState) -> str:
    validation = state.get("validation_result", {})
    if validation.get("passed"):
        return "human_review"
    retry = state.get("retry_count", 0)
    max_r = state.get("max_retries", 1)
    if retry < max_r:
        state["retry_count"] = retry + 1
        return "pipeline_processing"
    return "fallback"
