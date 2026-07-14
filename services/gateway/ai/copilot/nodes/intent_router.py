from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


def normalize_intent(raw_intent: str) -> str:
    normalized = (raw_intent or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"lesson_planning", "lesson"}:
        return "lesson_planning"
    if normalized in {
        "assessment",
        "assessment_studio",
        "assessment_generation",
        "quiz",
        "worksheet",
        "homework",
        "test",
        "exam_generation",
        "generate_assessment",
    }:
        return "assessment_generation"
    if normalized in {
        "exam_marking",
        "exam_marking_studio",
        "exam marking",
        "mark_exam",
        "mark exam",
        "grade_exam",
        "grade exam",
        "mark_student_paper",
        "mark student paper",
        "grade_student_paper",
        "grade student paper",
        "mark_assessment",
        "mark assessment",
        "grade_assessment",
        "grade assessment",
        "exam_correction",
        "exam correction",
        "paper_marking",
        "paper marking",
        "marking_studio",
        "marking studio",
        "assessment_review",
        "assessment review",
        "scan_exam",
        "scan exam",
        "batch_marking",
        "batch marking",
    }:
        return "exam_marking"
    return normalized or "unknown"


async def intent_router_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "intent_router")

    normalized = normalize_intent(state.get("intent", ""))
    state["intent"] = normalized

    if normalized not in {"lesson_planning", "assessment_generation", "exam_marking"}:
        state["final_response"] = {
            "status": "unsupported_intent",
            "request_id": state["request_id"],
            "conversation_id": state.get("conversation_id"),
            "intent": normalized,
            "message": "This request is outside the currently enabled workflows.",
            "missing_fields": [],
            "execution": {
                "workflow": "fallback",
                "current_step": "intent_router",
                "validation_passed": False,
                "retry_count": state.get("retry_count", 0),
                "tenant_slug": state.get("tenant_slug"),
            },
        }

    finish_node(state, "intent_router", started)
    return state


def route_after_intent(state: SchoolOSAIState) -> str:
    if state.get("final_response"):
        return "fallback"
    return "context_loader"
