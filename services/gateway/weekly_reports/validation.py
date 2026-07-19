from __future__ import annotations

import re
from typing import Any

_ALLOWED_SECTIONS = {
    "weekly_overview",
    "attendance",
    "academic_progress",
    "homework_or_assignments",
    "behaviour_and_wellbeing",
    "achievements_and_strengths",
    "areas_needing_support",
    "teacher_comment",
    "suggested_parent_support",
    "data_availability_note",
}

_FULL_NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b")


def validate_content_structure(content: dict[str, Any], evidence_snapshot: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    reporting_context = evidence_snapshot.get("reporting_context") if isinstance(evidence_snapshot, dict) else {}
    student_display_name = ""
    if isinstance(reporting_context, dict):
        student_display_name = str(reporting_context.get("student_display_name") or "").strip()

    title = content.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append({"code": "missing_title", "message": "Report title is required."})

    sections = content.get("sections", [])
    if not isinstance(sections, list):
        errors.append({"code": "invalid_sections", "message": "Sections must be a list."})
        return errors

    evidence_ids = {
        item.get("evidence_id")
        for item in evidence_snapshot.get("evidence_items", [])
        if isinstance(item, dict)
    }

    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append({"code": "invalid_section", "message": f"Section {idx} must be an object."})
            continue

        section_type = section.get("section_type")
        if section_type not in _ALLOWED_SECTIONS:
            errors.append({"code": "invalid_section_type", "message": f"Section type '{section_type}' is not allowed."})

        content_text = section.get("content")
        if not isinstance(content_text, str) or not content_text.strip():
            errors.append({"code": "invalid_section_content", "message": f"Section {section_type} content is required."})

        if isinstance(content_text, str) and ("<" in content_text or ">" in content_text):
            errors.append({"code": "unsafe_html", "message": f"Section {section_type} contains unsafe HTML."})

        if isinstance(content_text, str) and student_display_name:
            mentioned_names = _FULL_NAME_PATTERN.findall(content_text)
            foreign_names = [name for name in mentioned_names if name != student_display_name]
            if foreign_names:
                errors.append(
                    {
                        "code": "foreign_student_name",
                        "message": f"Section {section_type} mentions unauthorized student names.",
                    }
                )

        used_ids = section.get("used_evidence_ids", [])
        if not isinstance(used_ids, list) or not all(isinstance(v, str) for v in used_ids):
            errors.append({"code": "invalid_used_evidence_ids", "message": f"Section {section_type} used_evidence_ids must be a string list."})
        else:
            for used_id in used_ids:
                if used_id not in evidence_ids:
                    errors.append({"code": "unknown_evidence_id", "message": f"Unknown evidence id: {used_id}"})

    if not any((isinstance(s, dict) and s.get("section_type") == "data_availability_note") for s in sections):
        errors.append({
            "code": "missing_data_availability_note",
            "message": "A data availability note section is required.",
        })

    return errors
