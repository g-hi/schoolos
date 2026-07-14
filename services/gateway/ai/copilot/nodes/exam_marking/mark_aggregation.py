"""
Mark Aggregation node.

Calculates totals and quality counts from question_responses in generated_content.
Enforces: marks ≤ maximum, no negative marks (unless override configured),
          all expected questions accounted for.
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

_CONFIDENCE_HIGH = 0.90
_CONFIDENCE_MEDIUM = 0.70


async def mark_aggregation_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "mark_aggregation")

    generated = state.get("generated_content", {})
    inp = state.get("structured_input", {})
    responses: list[dict] = generated.get("question_responses", [])
    expected_count: int = int(inp.get("expected_question_count", len(responses)) or len(responses))
    allow_negative: bool = bool(inp.get("allow_negative_marks", False))

    proposed_total = 0.0
    max_marks_total = 0.0
    unanswered_count = 0
    unresolved_count = 0
    low_confidence_count = 0
    review_required_count = 0

    validated_responses: list[dict] = []
    errors: list[str] = []

    for r in responses:
        max_q = float(r.get("max_marks", 0.0))
        proposed = float(r.get("proposed_marks", 0.0))

        # Enforce marks ≤ maximum
        if proposed > max_q:
            r["proposed_marks"] = max_q
            proposed = max_q
            errors.append(f"q{r.get('question_number')}_capped_to_max")

        # Enforce no negative marks unless configured
        if not allow_negative and proposed < 0:
            r["proposed_marks"] = 0.0
            proposed = 0.0

        max_marks_total += max_q
        proposed_total += proposed

        extracted = r.get("extracted_answer", "")
        if not extracted or extracted.strip() == "":
            unanswered_count += 1

        if r.get("status") == "unresolved":
            unresolved_count += 1

        conf = float(r.get("confidence", 1.0) or 1.0)
        if conf < _CONFIDENCE_MEDIUM:
            low_confidence_count += 1

        if r.get("requires_teacher_review"):
            review_required_count += 1

        validated_responses.append(r)

    # Check expected question count
    found_q_numbers = {r.get("question_number") for r in responses}
    missing_q = [q for q in range(1, expected_count + 1) if q not in found_q_numbers]

    percentage = round((proposed_total / max_marks_total * 100), 2) if max_marks_total > 0 else 0.0

    generated["question_responses"] = validated_responses
    generated["proposed_total"] = round(proposed_total, 2)
    generated["max_marks"] = round(max_marks_total, 2)
    generated["percentage"] = percentage
    generated["unanswered_count"] = unanswered_count
    generated["unresolved_count"] = unresolved_count
    generated["low_confidence_count"] = low_confidence_count
    generated["review_required_count"] = review_required_count
    generated["missing_questions"] = missing_q
    generated["aggregation_errors"] = errors

    state["generated_content"] = generated

    if errors:
        state["errors"] = state.get("errors", []) + errors

    finish_node(state, "mark_aggregation", started)
    return state
