from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


_REQUIRED_FIELDS_BY_INTENT = {
    "lesson_planning": ["grade", "subject", "topic", "duration_minutes"],
    "assessment_generation": [
        "curriculum",
        "grade",
        "subject",
        "topic",
        "learning_objectives",
        "difficulty",
        "assessment_type",
        "question_types",
        "number_of_questions",
        "total_marks",
        "duration_minutes",
        "language",
    ],
}


_QUESTION_BY_FIELD = {
    "curriculum": "Which curriculum should this assessment align to?",
    "grade": "Which grade is this for?",
    "subject": "Which subject is this assessment for?",
    "topic": "Which topic should this assessment focus on?",
    "learning_objectives": "What are the key learning objectives?",
    "difficulty": "What difficulty level do you want: Easy, Medium, or Hard?",
    "assessment_type": "Which assessment type should be generated?",
    "question_types": "Which question types should be included?",
    "number_of_questions": "How many questions should the assessment include?",
    "total_marks": "What is the total marks allocation?",
    "duration_minutes": "How long should the assessment be in minutes?",
    "language": "Which language should the assessment use?",
    "topic_lesson": "Which topic should this lesson focus on?",
}


_WORKFLOW_LABELS = {
    "lesson_planning": "lesson_planning",
    "assessment_generation": "assessment_generation",
}


def _first_question(missing_fields: list[str]) -> str:
    for field in missing_fields:
        if field in _QUESTION_BY_FIELD:
            return _QUESTION_BY_FIELD[field]
    return "Please provide the missing details to continue."


async def missing_information_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "missing_information")

    intent = state.get("intent", "lesson_planning")
    required_fields = _REQUIRED_FIELDS_BY_INTENT.get(intent, _REQUIRED_FIELDS_BY_INTENT["lesson_planning"])
    structured_input = state.get("structured_input", {})

    missing_fields: list[str] = []
    for field in required_fields:
        value = structured_input.get(field)
        if isinstance(value, list):
            if not value:
                missing_fields.append(field)
            continue
        if value is None or value == "":
            missing_fields.append(field)

    state["missing_fields"] = missing_fields

    if missing_fields:
        clarification = _first_question(missing_fields)
        state["clarification_question"] = clarification
        state["final_response"] = {
            "status": "needs_clarification",
            "request_id": state["request_id"],
            "conversation_id": state.get("conversation_id"),
            "intent": state.get("intent"),
            "message": clarification,
            "clarification_question": clarification,
            "missing_fields": missing_fields,
            "execution": {
                "workflow": _WORKFLOW_LABELS.get(intent, intent),
                "current_step": "missing_information",
                "validation_passed": False,
                "retry_count": state.get("retry_count", 0),
                "tenant_slug": state.get("tenant_slug"),
            },
        }

    finish_node(state, "missing_information", started)
    return state


def route_after_missing_information(state: SchoolOSAIState) -> str:
    if state.get("final_response"):
        return "observability"
    if state.get("intent") == "assessment_generation":
        return "assessment_generation"
    return "lesson_planning"
