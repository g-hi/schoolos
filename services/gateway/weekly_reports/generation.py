from __future__ import annotations

import json
from typing import Any

from services.gateway.ai.copilot.providers.base import LLMProvider


def build_deterministic_draft(*, student_display_name: str, class_name: str, week_start: str, week_end: str, evidence_snapshot: dict[str, Any]) -> dict[str, Any]:
    staff_notes = {}
    for item in evidence_snapshot.get("evidence_items", []):
        if isinstance(item, dict) and item.get("source_type") == "staff_input":
            staff_notes = ((item.get("facts") or {}).get("notes") or {})
            break

    sections = [
        {
            "section_type": "weekly_overview",
            "content": (
                f"This weekly report covers {student_display_name} in {class_name} for {week_start} to {week_end}. "
                "It summarizes verified information available in SchoolOS and staff-entered notes for this period."
            ),
            "used_evidence_ids": ["student_profile_1", "staff_input_1"],
        },
        {
            "section_type": "attendance",
            "content": "Attendance information was not available for this reporting week.",
            "used_evidence_ids": ["attendance_1"],
        },
        {
            "section_type": "academic_progress",
            "content": "No academic results were available for this period.",
            "used_evidence_ids": ["academic_1"],
        },
        {
            "section_type": "homework_or_assignments",
            "content": "Homework information is not currently connected to this student profile.",
            "used_evidence_ids": ["homework_1"],
        },
        {
            "section_type": "behaviour_and_wellbeing",
            "content": "Behaviour information was not available for this reporting week.",
            "used_evidence_ids": ["behaviour_1"],
        },
        {
            "section_type": "achievements_and_strengths",
            "content": (staff_notes.get("achievements") or staff_notes.get("strengths_observed") or "No verified achievements or strengths were entered for this period."),
            "used_evidence_ids": ["staff_input_1"],
        },
        {
            "section_type": "areas_needing_support",
            "content": (staff_notes.get("areas_needing_support") or "No specific areas needing support were entered for this period."),
            "used_evidence_ids": ["staff_input_1"],
        },
        {
            "section_type": "teacher_comment",
            "content": (staff_notes.get("weekly_teacher_summary") or "No additional weekly teacher summary was entered for this period."),
            "used_evidence_ids": ["staff_input_1"],
        },
        {
            "section_type": "suggested_parent_support",
            "content": (staff_notes.get("suggested_parent_support") or "No additional parent support suggestions were entered for this period."),
            "used_evidence_ids": ["staff_input_1"],
        },
        {
            "section_type": "data_availability_note",
            "content": "Unavailable data in this report reflects module availability only and should not be interpreted as student performance.",
            "used_evidence_ids": ["attendance_1", "academic_1", "homework_1", "behaviour_1"],
        },
    ]

    return {
        "title": f"Weekly Report: {student_display_name}",
        "sections": sections,
        "warnings": [],
    }


def _build_ai_prompt(*, evidence_snapshot: dict[str, Any], deterministic_draft: dict[str, Any]) -> str:
    payload = {
        "instructions": [
            "Rewrite and organize verified facts only.",
            "Do not invent claims, trends, diagnoses, or recommendations beyond provided staff notes.",
            "Preserve unavailable-data statements.",
            "Return JSON only with keys: title, sections[].section_type, sections[].content, sections[].used_evidence_ids, warnings.",
            "Do not use HTML.",
        ],
        "evidence_snapshot": evidence_snapshot,
        "fallback_draft_template": deterministic_draft,
    }
    return json.dumps(payload, ensure_ascii=True)


def _parse_ai_json(content: str) -> dict[str, Any] | None:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def generate_optional_ai_draft(
    *,
    provider: LLMProvider | None,
    deterministic_draft: dict[str, Any],
    evidence_snapshot: dict[str, Any],
    use_ai: bool,
) -> tuple[dict[str, Any], str | None]:
    if not use_ai or provider is None:
        return deterministic_draft, None

    prompt = _build_ai_prompt(evidence_snapshot=evidence_snapshot, deterministic_draft=deterministic_draft)
    try:
        result = await provider.generate(prompt)
    except Exception:
        return deterministic_draft, "provider_unavailable"

    parsed = _parse_ai_json(str(result.get("content", "")))
    if parsed is None:
        return deterministic_draft, "invalid_provider_output"

    return parsed, None
