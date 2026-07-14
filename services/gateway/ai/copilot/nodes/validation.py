from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


_REQUIRED_OUTPUT_FIELDS = [
    "lesson_overview",
    "learning_objectives",
    "materials",
    "activities",
    "differentiation",
    "assessment",
    "homework",
    "reflection",
]


def _validate_lesson_planning(generated: dict) -> list[str]:
    return [field for field in _REQUIRED_OUTPUT_FIELDS if not generated.get(field)]


def _validate_assessment_generation(generated: dict) -> list[str]:
    issues: list[str] = []

    questions = generated.get("questions", [])
    marks_allocation = generated.get("marks_allocation", [])
    total_marks = generated.get("total_marks", 0)
    metadata = generated.get("assessment_metadata", {})
    question_types = metadata.get("question_types", []) if isinstance(metadata, dict) else []
    difficulty_distribution = generated.get("difficulty_distribution", {})
    bloom_coverage = generated.get("bloom_coverage", {})

    if not questions:
        issues.append("question_count")

    if not marks_allocation or sum(item.get("marks", 0) for item in marks_allocation if isinstance(item, dict)) != total_marks:
        issues.append("marks_allocation")

    if not difficulty_distribution:
        issues.append("difficulty_balance")

    if not question_types or len(set(str(item) for item in question_types)) == 0:
        issues.append("question_diversity")

    required_sections = ["instructions", "questions", "marks_allocation", "answer_key_preview", "rubric_preview", "teacher_notes"]
    for section in required_sections:
        if not generated.get(section):
            issues.append(f"required_sections:{section}")

    if not isinstance(bloom_coverage, dict):
        issues.append("bloom_coverage_placeholder")

    return issues


async def validation_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "validation")

    generated = state.get("generated_content", {})
    intent = state.get("intent", "lesson_planning")
    if intent == "assessment_generation":
        issues = _validate_assessment_generation(generated)
    else:
        issues = _validate_lesson_planning(generated)

    passed = len(issues) == 0

    state["validation_result"] = {"passed": passed, "issues": issues}
    finish_node(state, "validation", started)
    return state


def route_after_validation(state: SchoolOSAIState) -> str:
    validation = state.get("validation_result", {})
    if validation.get("passed"):
        return "human_approval"
    if state.get("retry_count", 0) < state.get("max_retries", 1):
        return "revision"
    return "fallback"
