from __future__ import annotations

from typing import Any

from services.gateway.ai.copilot.prompt_builders import build_assessment_generation_prompt
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


def _ensure_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or default
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()] or default
    return default


def _difficulty_distribution(difficulty: str, question_count: int) -> dict[str, int]:
    normalized = (difficulty or "").strip().lower()
    if normalized == "easy":
        return {"easy": question_count, "medium": 0, "hard": 0}
    if normalized == "hard":
        medium = max(1, question_count // 3)
        return {"easy": 0, "medium": medium, "hard": max(0, question_count - medium)}
    easy = max(1, question_count // 3)
    hard = max(1, question_count // 4)
    medium = max(0, question_count - easy - hard)
    return {"easy": easy, "medium": medium, "hard": hard}


def _format_structured_output(state: SchoolOSAIState, generated_markdown: str) -> dict[str, Any]:
    data = state.get("structured_input", {})
    if data.get("force_validation_failure"):
        return {
            "instructions": "",
            "questions": [],
            "marks_allocation": [],
            "total_marks": 0,
            "answer_key_preview": [],
            "rubric_preview": [],
            "teacher_notes": "",
            "difficulty_distribution": {"easy": 0, "medium": 0, "hard": 0},
            "bloom_coverage": {"placeholder": True},
            "raw_markdown": generated_markdown,
        }

    grade = str(data.get("grade", "5"))
    subject = str(data.get("subject", "Science"))
    topic = str(data.get("topic", state.get("original_message", "Requested topic")))
    assessment_type = str(data.get("assessment_type", "Quiz"))
    difficulty = str(data.get("difficulty", "Medium"))
    number_of_questions = int(data.get("number_of_questions", 10) or 10)
    total_marks = int(data.get("total_marks", max(number_of_questions * 2, 10)) or max(number_of_questions * 2, 10))
    language = str(data.get("language", "English"))
    teacher_notes = str(data.get("teacher_notes", "No additional notes"))
    objectives = _ensure_list(data.get("learning_objectives"), ["Understand core concept", "Apply concept to examples"])
    question_types = _ensure_list(data.get("question_types"), ["Mix of Question Types"])
    base_marks = max(1, total_marks // max(number_of_questions, 1))
    remainder = max(0, total_marks - (base_marks * number_of_questions))

    questions: list[dict[str, Any]] = []
    marks_allocation: list[dict[str, Any]] = []
    answer_key_preview: list[dict[str, Any]] = []

    for index in range(number_of_questions):
        q_marks = base_marks + (1 if index < remainder else 0)
        q_type = question_types[index % len(question_types)]
        question_text = f"{q_type} question on {topic} linked to objective: {objectives[index % len(objectives)]}."
        questions.append(
            {
                "number": index + 1,
                "type": q_type,
                "text": question_text,
                "marks": q_marks,
            }
        )
        marks_allocation.append({"question": index + 1, "marks": q_marks})
        answer_key_preview.append(
            {
                "question": index + 1,
                "expected_answer": f"Model answer guidance for question {index + 1}.",
            }
        )

    rubric_preview = [
        {"criterion": "Accuracy", "descriptor": "Conceptually correct response.", "marks": max(1, total_marks // 3)},
        {"criterion": "Application", "descriptor": "Applies knowledge to context.", "marks": max(1, total_marks // 3)},
        {"criterion": "Clarity", "descriptor": "Communicates reasoning clearly.", "marks": max(1, total_marks - (2 * max(1, total_marks // 3)))},
    ]

    instructions = (
        f"{assessment_type} for Grade {grade} {subject}. "
        f"Topic: {topic}. Language: {language}. Answer all questions and show working where required."
    )

    return {
        "assessment_metadata": {
            "assessment_type": assessment_type,
            "grade": grade,
            "subject": subject,
            "topic": topic,
            "difficulty": difficulty,
            "question_types": question_types,
        },
        "instructions": instructions,
        "questions": questions,
        "marks_allocation": marks_allocation,
        "total_marks": total_marks,
        "answer_key_preview": answer_key_preview,
        "rubric_preview": rubric_preview,
        "teacher_notes": teacher_notes,
        "difficulty_distribution": _difficulty_distribution(difficulty, number_of_questions),
        "bloom_coverage": {"placeholder": True, "message": "Bloom taxonomy scoring will be added in a future workflow."},
        "raw_markdown": generated_markdown,
    }


async def assessment_generation_node(state: SchoolOSAIState, provider: LLMProvider) -> SchoolOSAIState:
    started = start_node(state, "assessment_generation")

    prompt = build_assessment_generation_prompt(state)
    response = await provider.generate(prompt)

    generated_markdown = response.get("content", "").strip()
    state["provider"] = getattr(provider, "provider_name", "unknown")
    state["token_usage"] = response.get("token_usage", {})
    state["generated_content"] = _format_structured_output(state, generated_markdown)

    finish_node(state, "assessment_generation", started)
    return state