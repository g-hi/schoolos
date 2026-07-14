"""
Marking Scheme Parser node.

Normalises the raw answer_key and marking_scheme from structured_input
into canonical form consumed by all processing strategies.

Canonical answer_key item:
    {
        "question_number": int,
        "question_type":   str,  # mcq | true_false | matching | numeric | short_answer | essay
        "question_text":   str,
        "correct_answer":  str,
        "max_marks":       float,
        "accepted_alternatives": list[str],
        "numeric_tolerance": float | None,
        "partial_credit":  float | None,
        "rubric_criteria": list[dict],  # for open-ended questions
        "case_sensitive":  bool,
    }
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

_VALID_Q_TYPES = {"mcq", "true_false", "matching", "numeric", "fill_blank", "short_answer", "essay"}


def _normalise_item(raw: dict, index: int) -> dict:
    q_type = str(raw.get("question_type", "short_answer")).lower().strip()
    if q_type not in _VALID_Q_TYPES:
        q_type = "short_answer"

    return {
        "question_number": int(raw.get("question_number", index + 1)),
        "question_type": q_type,
        "question_text": str(raw.get("question_text", f"Question {index + 1}")),
        "correct_answer": str(raw.get("correct_answer", raw.get("answer", ""))),
        "max_marks": float(raw.get("max_marks", raw.get("marks", 1.0))),
        "accepted_alternatives": [str(a) for a in raw.get("accepted_alternatives", [])],
        "numeric_tolerance": raw.get("numeric_tolerance"),
        "partial_credit": raw.get("partial_credit"),
        "rubric_criteria": raw.get("rubric_criteria", []),
        "case_sensitive": bool(raw.get("case_sensitive", False)),
    }


async def marking_scheme_parser_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "marking_scheme_parser")

    inp = state.get("structured_input", {})
    raw_answer_key: list[dict] = inp.get("answer_key", [])
    marking_scheme: dict = inp.get("marking_scheme", {})

    normalised_key = [_normalise_item(item, i) for i, item in enumerate(raw_answer_key)]

    # If no answer key provided, build a synthetic one for testing
    if not normalised_key:
        q_count = int(inp.get("expected_question_count", 1))
        total = float(inp.get("total_marks", q_count))
        per_q = round(total / max(q_count, 1), 2)
        normalised_key = [
            {
                "question_number": i + 1,
                "question_type": "short_answer",
                "question_text": f"Question {i + 1}",
                "correct_answer": "",
                "max_marks": per_q,
                "accepted_alternatives": [],
                "numeric_tolerance": None,
                "partial_credit": None,
                "rubric_criteria": [],
                "case_sensitive": False,
            }
            for i in range(q_count)
        ]

    inp["normalized_answer_key"] = normalised_key
    inp["normalized_rubric"] = {
        "total_marks": sum(item["max_marks"] for item in normalised_key),
        "partial_credit_enabled": marking_scheme.get("partial_credit_enabled", False),
        "rubric_criteria": marking_scheme.get("rubric_criteria", []),
    }
    state["structured_input"] = inp

    finish_node(state, "marking_scheme_parser", started)
    return state
