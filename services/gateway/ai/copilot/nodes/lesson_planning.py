from __future__ import annotations

from typing import Any

from services.gateway.ai.copilot.prompt_builders import build_lesson_planning_prompt
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


def _format_structured_output(state: SchoolOSAIState, generated_markdown: str) -> dict[str, Any]:
    data = state.get("structured_input", {})
    if data.get("force_validation_failure"):
        return {
            "lesson_overview": "",
            "learning_objectives": [],
            "materials": [],
            "activities": [],
            "differentiation": [],
            "assessment": [],
            "homework": "",
            "reflection": "",
            "raw_markdown": generated_markdown,
        }

    grade = data.get("grade", "Grade 5")
    subject = data.get("subject", "Science")
    topic = data.get("topic", state.get("original_message", "Requested topic"))
    duration = data.get("duration_minutes", 45)

    return {
        "lesson_overview": f"A {duration}-minute {subject} lesson for Grade {grade} on {topic}.",
        "learning_objectives": [
            "Understand the core concept",
            "Apply the concept in guided practice",
        ],
        "materials": ["Whiteboard", "Workbook", "Exit ticket"],
        "activities": [
            "Starter and prior knowledge activation",
            "Guided instruction",
            "Collaborative activity",
        ],
        "differentiation": [
            "Provide scaffolded examples",
            "Offer extension challenge",
        ],
        "assessment": ["Exit ticket"],
        "homework": "Complete one reinforcement activity",
        "reflection": "Record what to adjust for next lesson.",
        "raw_markdown": generated_markdown,
    }


async def lesson_planning_node(state: SchoolOSAIState, provider: LLMProvider) -> SchoolOSAIState:
    started = start_node(state, "lesson_planning")

    prompt = build_lesson_planning_prompt(state)
    response = await provider.generate(prompt)

    generated_markdown = response.get("content", "").strip()
    state["provider"] = getattr(provider, "provider_name", "unknown")
    state["token_usage"] = response.get("token_usage", {})
    state["generated_content"] = _format_structured_output(state, generated_markdown)

    finish_node(state, "lesson_planning", started)
    return state
