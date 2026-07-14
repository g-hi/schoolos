from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


async def context_loader_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "context_loader")

    school_name = state.get("school_context", {}).get("school_name", "School")
    term_name = state.get("school_context", {}).get("term", "Current term")

    teacher_context = {
        "user_id": state.get("user_id"),
        "user_role": state.get("user_role"),
        "default_grade": state.get("structured_input", {}).get("grade", "Grade 5"),
        "default_subject": state.get("structured_input", {}).get("subject", "Science"),
    }
    school_context = {
        "school_name": school_name,
        "term": term_name,
        "tenant_slug": state.get("tenant_slug"),
    }
    retrieved_context = {
        "tenant_context": {"slug": state.get("tenant_slug")},
        "teacher_context": teacher_context,
        "curriculum_context": {
            "framework": state.get("structured_input", {}).get("curriculum", "Curriculum context pending source integration"),
        },
        "school_context": school_context,
    }

    state["teacher_context"] = teacher_context
    state["retrieved_context"] = retrieved_context

    finish_node(state, "context_loader", started)
    return state
