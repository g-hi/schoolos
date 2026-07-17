from __future__ import annotations

import json

from services.gateway.ai.copilot.state import SchoolOSAIState


def build_parent_summary_prompt(state: SchoolOSAIState) -> str:
    parent_intent = state.get("parent_intent", "family_summary")
    evidence = state.get("evidence_records", [])
    suggestions = state.get("deterministic_suggestions", [])

    prompt = {
        "role": "SchoolOS Parent Assistant",
        "instructions": [
            "Use only the supplied evidence.",
            "Do not invent facts, actions, or students.",
            "Return JSON only.",
            "Use plain text only. Do not include HTML or markdown.",
            "If no evidence supports a detail, omit it.",
        ],
        "intent": parent_intent,
        "response_schema": {
            "message": "string",
            "used_evidence_ids": ["string"],
            "suggested_questions": ["string"],
            "mentioned_students": ["string"],
        },
        "suggestion_candidates": suggestions,
        "evidence_records": evidence,
    }
    return json.dumps(prompt, ensure_ascii=True)