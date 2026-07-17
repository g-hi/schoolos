from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable
from uuid import UUID

from services.gateway.ai.audit import log_action
from services.gateway.ai.copilot.parent_assistant_data import (
    load_parent_bootstrap,
    load_pickup_status,
    load_timeline_events,
    load_today_schedule,
    resolve_school_timezone,
)
from services.gateway.ai.copilot.parent_prompt_builders import build_parent_summary_prompt
from services.gateway.ai.copilot.providers.base import LLMProvider
from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node


ParentLoader = Callable[..., Awaitable[Any]]

_SUPPORTED_PARENT_INTENTS = {
    "family_summary",
    "child_summary",
    "linked_children",
    "family_timeline",
    "child_schedule",
    "pickup_status",
    "module_availability",
    "help",
    "unsupported_or_out_of_scope",
}

_UNSAFE_PATTERNS = [
    (re.compile(r"ignore (all|your|previous) instructions", re.IGNORECASE), "I can only answer questions about your authorized family information."),
    (re.compile(r"system prompt|hidden prompt|developer prompt", re.IGNORECASE), "I can help with your family information, but I cannot reveal internal instructions."),
    (re.compile(r"token|password|secret|database record|sql", re.IGNORECASE), "I can help with your family information, but I cannot reveal sensitive system data."),
    (re.compile(r"all students|list every student|entire school", re.IGNORECASE), "I can only help with information for children linked to your account."),
    (re.compile(r"another family|another parent|someone else's child|someone elses child", re.IGNORECASE), "I can only help with information for children linked to your account."),
]

_WRITE_ACTION_PATTERN = re.compile(
    r"\b(send|book|create|cancel|pay|update|change|contact|message|notify|submit)\b",
    re.IGNORECASE,
)

_HTML_PATTERN = re.compile(r"<[^>]+>")

_ACTIVE_PICKUP_STATUSES = {"requested", "pending", "approved", "active", "in_progress", "awaiting_collection"}
_NO_EXPLICIT_CHILD_HINTS = ("this child", "my child", "that child", "the child", "our child")
_EXPLICIT_CHILD_REFERENCE_PATTERNS = [
    re.compile(r"\b(?:student\s*(?:id|number|no\.?|#)|id)\s*[:#-]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:about|for|on|of|regarding|regards|tell me about|give me information about|show me information about|what information is currently available for|what information is available for|what can i see for|which modules are available for|can i see)\s+([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,3})",
        re.IGNORECASE,
    ),
    re.compile(r"\b([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,3})'s\b", re.IGNORECASE),
]
_MODULE_AVAILABILITY_ORDER = [
    ("attendance", "Attendance"),
    ("homework", "Homework"),
    ("academics", "Academic information"),
    ("behaviour", "Behaviour information"),
]

_DEFAULT_SUGGESTIONS = {
    "family_summary": ["Show recent family updates", "How many children are linked to my account?"],
    "child_summary": ["Does this child have anything scheduled today?", "What information is available for this child?"],
    "linked_children": ["Show recent family updates", "What information is currently available for my children?"],
    "family_timeline": ["Show the latest family update", "Do I have an active pickup request?"],
    "child_schedule": ["Give me a summary of this child", "What information is available for this child?"],
    "pickup_status": ["Show recent family updates", "Which children are linked to my account?"],
    "module_availability": ["Give me a summary of this child", "Show recent family updates"],
    "help": ["Summarize my family", "Show recent family updates"],
    "unsupported_or_out_of_scope": ["What can you help me with?", "Show recent family updates"],
}


def _student_label(student: dict[str, Any]) -> dict[str, str | None]:
    return {"id": str(student.get("student_id")), "display_name": str(student.get("display_name", "Child"))}


def _normalize_reference_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _student_matches_reference(reference: str, student: dict[str, Any]) -> bool:
    normalized_reference = _normalize_reference_text(reference)
    if not normalized_reference:
        return False

    normalized_student_name = _normalize_reference_text(str(student.get("display_name", "")))
    normalized_student_id = _normalize_reference_text(str(student.get("student_id", "")))
    normalized_student_code = _normalize_reference_text(str(student.get("student_code", "")))

    if normalized_reference in {normalized_student_name, normalized_student_id, normalized_student_code}:
        return True

    if normalized_student_name and normalized_student_name in normalized_reference:
        return True

    reference_tokens = set(normalized_reference.split())
    student_tokens = set(normalized_student_name.split())
    if reference_tokens and reference_tokens.issubset(student_tokens):
        return True

    return False


def _resolve_reference_against_students(reference: str, authorized_students: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    matches = [student for student in authorized_students if _student_matches_reference(reference, student)]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches
    return None, []


def _detect_explicit_child_reference(message: str, authorized_students: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    normalized_message = _normalize_reference_text(message)
    if any(hint in normalized_message for hint in _NO_EXPLICIT_CHILD_HINTS):
        return None, [], False

    for student in authorized_students:
        if _student_matches_reference(message, student):
            return student, [], True

    candidate_references: list[str] = []
    for pattern in _EXPLICIT_CHILD_REFERENCE_PATTERNS:
        for match in pattern.finditer(message):
            candidate = match.group(1).strip()
            if candidate:
                candidate_references.append(candidate)

    if not candidate_references:
        return None, [], False

    for candidate in candidate_references:
        matched_student, ambiguous_matches = _resolve_reference_against_students(candidate, authorized_students)
        if matched_student:
            return matched_student, [], True
        if ambiguous_matches:
            return None, ambiguous_matches, True

    return None, [], True


def _is_duplicate_unavailable_reason(reason: str) -> bool:
    normalized = _normalize_reference_text(reason)
    duplicate_markers = {
        "not available yet",
        "information is not available yet",
        "currently unavailable",
        "not currently available",
        "unavailable",
    }
    return any(marker in normalized for marker in duplicate_markers)


def _make_sources(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"type": source_type, "label": label} for source_type, label in items]


def _complete_response(
    state: SchoolOSAIState,
    *,
    status: str,
    message: str,
    response_kind: str,
    parent_intent: str | None = None,
    requires_clarification: bool | None = None,
    unavailable_reason: str | None = None,
    student: dict[str, str | None] | None = None,
    sources: list[dict[str, str]] | None = None,
    suggested_questions: list[str] | None = None,
) -> None:
    state["final_response"] = {
        "status": status,
        "request_id": state["request_id"],
        "conversation_id": state.get("conversation_id"),
        "intent": state.get("intent"),
        "message": message,
        "missing_fields": state.get("missing_fields", []),
        "clarification_question": state.get("clarification_question") or None,
        "response_kind": response_kind,
        "parent_intent": parent_intent,
        "requires_clarification": requires_clarification,
        "unavailable_reason": unavailable_reason,
        "student": student,
        "sources": sources or [],
        "suggested_questions": suggested_questions or [],
        "execution": {
            "workflow": "parent_assistant",
            "current_step": state.get("current_node", "parent_assistant"),
            "validation_passed": bool(state.get("validation_result", {}).get("passed", False)),
            "retry_count": state.get("retry_count", 0),
            "tenant_slug": state.get("tenant_slug"),
        },
    }


def _detect_safety_refusal(message: str) -> str | None:
    for pattern, refusal in _UNSAFE_PATTERNS:
        if pattern.search(message):
            return refusal
    if _WRITE_ACTION_PATTERN.search(message):
        return "I can provide information only. I cannot perform actions such as sending messages, changing records, or managing pickups."
    return None


def _classify_intent(message: str) -> str:
    lowered = message.lower()
    if any(phrase in lowered for phrase in ["what can you help", "what questions", "help"]):
        return "help"
    if any(phrase in lowered for phrase in ["which children", "how many children", "linked to my account"]):
        return "linked_children"
    if any(phrase in lowered for phrase in ["timeline", "latest family update", "recent family updates", "recent family timeline"]):
        return "family_timeline"
    if any(phrase in lowered for phrase in ["pickup", "picked up", "active pickup"]):
        return "pickup_status"
    if any(
        phrase in lowered
        for phrase in [
            "what information is available",
            "what information is currently available",
            "what can i see",
            "what student information do you have",
            "what student information are available",
            "which modules are available",
            "module availability",
            "attendance information",
            "homework information",
            "behaviour information",
            "behavior information",
            "can i see",
            "is homework information available",
            "is attendance information available",
            "is behaviour information available",
            "is behavior information available",
            "attendance",
            "homework",
            "behaviour",
            "behavior",
            "academics",
        ]
    ):
        return "module_availability"
    if any(phrase in lowered for phrase in ["scheduled today", "timetable", "have today", "schedule today"]):
        return "child_schedule"
    if any(phrase in lowered for phrase in ["summarize my family", "what updates do i have", "summary of my family", "updates for my children"]):
        return "family_summary"
    if any(phrase in lowered for phrase in ["how is", "give me", "overview", "summary of", "tell me about"]) and any(char.isalpha() for char in lowered):
        return "child_summary"
    return "unsupported_or_out_of_scope"


def _match_student_name(message: str, authorized_students: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    lowered = message.lower()
    exact = [student for student in authorized_students if str(student.get("display_name", "")).lower() in lowered]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    partial_matches: list[dict[str, Any]] = []
    for student in authorized_students:
        parts = [part for part in str(student.get("display_name", "")).lower().split() if len(part) >= 3]
        if any(part in lowered for part in parts):
            partial_matches.append(student)

    if len(partial_matches) == 1:
        return partial_matches[0], []
    if len(partial_matches) > 1:
        return None, partial_matches
    return None, []


def _find_student_by_id(authorized_students: list[dict[str, Any]], student_id: str | None) -> dict[str, Any] | None:
    if not student_id:
        return None
    for student in authorized_students:
        if str(student.get("student_id")) == str(student_id):
            return student
    return None


def _requires_student(intent: str) -> bool:
    return intent in {"child_summary", "child_schedule", "module_availability"}


def _build_evidence(source_type: str, student_id: str | None, facts: dict[str, Any], counter: int) -> dict[str, Any]:
    return {
        "evidence_id": f"{source_type}_{counter}",
        "source_type": source_type,
        "student_id": student_id,
        "facts": facts,
    }


def build_parent_bootstrap_node(db_loader: ParentLoader):
    async def parent_bootstrap_node(state: SchoolOSAIState) -> SchoolOSAIState:
        started = start_node(state, "parent_bootstrap")
        if state.get("final_response"):
            finish_node(state, "parent_bootstrap", started)
            return state

        bootstrap = await db_loader(
            tenant_id=state.get("tenant_id", ""),
            parent_user_id=state.get("user_id", ""),
        )
        state["parent_profile"] = bootstrap["parent_profile"]
        state["family_context"] = bootstrap["family_context"]
        state["authorized_students"] = bootstrap["authorized_students"]
        finish_node(state, "parent_bootstrap", started)
        return state

    return parent_bootstrap_node


async def parent_intent_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "parent_intent")
    if state.get("final_response"):
        finish_node(state, "parent_intent", started)
        return state

    family_context = state.get("family_context", {})
    authorized_students = state.get("authorized_students", [])
    if not family_context.get("family_id"):
        _complete_response(
            state,
            status="unavailable",
            message="I could not find an active family for this account.",
            response_kind="unavailable",
            unavailable_reason="missing_family",
            parent_intent="family_summary",
            suggested_questions=["Which children are linked to my account?"],
        )
        finish_node(state, "parent_intent", started)
        return state

    if not authorized_students:
        _complete_response(
            state,
            status="unavailable",
            message="No children are currently linked to this account.",
            response_kind="unavailable",
            unavailable_reason="no_linked_children",
            parent_intent="linked_children",
            suggested_questions=["What can you help me with?"],
        )
        finish_node(state, "parent_intent", started)
        return state

    original_message = str(state.get("original_message", "")).strip()
    refusal = _detect_safety_refusal(original_message)
    if refusal:
        state["parent_intent"] = "unsupported_or_out_of_scope"
        _complete_response(
            state,
            status="unsupported_intent",
            message=refusal,
            response_kind="refusal",
            parent_intent="unsupported_or_out_of_scope",
            suggested_questions=_DEFAULT_SUGGESTIONS["unsupported_or_out_of_scope"],
        )
        finish_node(state, "parent_intent", started)
        return state

    state["parent_intent"] = _classify_intent(original_message)
    if state["parent_intent"] not in _SUPPORTED_PARENT_INTENTS:
        state["parent_intent"] = "unsupported_or_out_of_scope"

    if state["parent_intent"] == "help":
        _complete_response(
            state,
            status="completed",
            message="I can help with family summaries, linked children, recent family timeline updates, pickup status, timetable questions for a linked child, and which information is currently available.",
            response_kind="help",
            parent_intent="help",
            suggested_questions=_DEFAULT_SUGGESTIONS["help"],
        )
    elif state["parent_intent"] == "unsupported_or_out_of_scope":
        _complete_response(
            state,
            status="unsupported_intent",
            message="I can provide information from SchoolOS for children linked to your account, but I cannot handle that request.",
            response_kind="unsupported",
            parent_intent="unsupported_or_out_of_scope",
            suggested_questions=_DEFAULT_SUGGESTIONS["unsupported_or_out_of_scope"],
        )

    finish_node(state, "parent_intent", started)
    return state


async def parent_student_resolution_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "parent_student_resolution")
    if state.get("final_response"):
        finish_node(state, "parent_student_resolution", started)
        return state

    authorized_students = list(state.get("authorized_students", []))
    intent = str(state.get("parent_intent", "unsupported_or_out_of_scope"))
    active_student_id = str(state.get("structured_input", {}).get("active_student_id") or "") or None


    explicit_student, ambiguous_matches, has_explicit_reference = _detect_explicit_child_reference(
        str(state.get("original_message", "")),
        authorized_students,
    )

    if explicit_student:
        state["resolved_student"] = explicit_student
        finish_node(state, "parent_student_resolution", started)
        return state

    if has_explicit_reference and not ambiguous_matches:
        clarification = "I could not find that child among the children linked to your account."
        state["clarification_question"] = ""
        state["missing_fields"] = ["linked_child_reference"]
        _complete_response(
            state,
            status="unavailable",
            message=clarification,
            response_kind="unavailable",
            unavailable_reason="child_not_linked",
            parent_intent=intent,
            suggested_questions=[],
        )
        finish_node(state, "parent_student_resolution", started)
        return state

    matched_student = None
    if active_student_id:
        matched_student = _find_student_by_id(authorized_students, active_student_id)
    if not matched_student and len(authorized_students) == 1:
        matched_student = authorized_students[0]

    if ambiguous_matches:
        options = [str(student.get("display_name")) for student in ambiguous_matches]
        clarification = f"Which child do you mean: {' or '.join(options)}?"
        state["clarification_question"] = clarification
        state["missing_fields"] = ["student_reference"]
        _complete_response(
            state,
            status="needs_clarification",
            message=clarification,
            response_kind="clarification",
            parent_intent=intent,
            requires_clarification=True,
            suggested_questions=[],
        )
        finish_node(state, "parent_student_resolution", started)
        return state

    if ambiguous_matches:
        options = [str(student.get("display_name")) for student in ambiguous_matches]
        clarification = f"Which child do you mean: {' or '.join(options)}?"
        state["clarification_question"] = clarification
        state["missing_fields"] = ["student_reference"]
        _complete_response(
            state,
            status="needs_clarification",
            message=clarification,
            response_kind="clarification",
            parent_intent=intent,
            requires_clarification=True,
            suggested_questions=[],
        )
        finish_node(state, "parent_student_resolution", started)
        return state

    if _requires_student(intent) and not matched_student:
        clarification = "Which child do you mean?"
        state["clarification_question"] = clarification
        state["missing_fields"] = ["student_reference"]
        _complete_response(
            state,
            status="needs_clarification",
            message=clarification,
            response_kind="clarification",
            parent_intent=intent,
            requires_clarification=True,
            suggested_questions=[],
        )
        finish_node(state, "parent_student_resolution", started)
        return state

    if matched_student:
        state["resolved_student"] = matched_student

    finish_node(state, "parent_student_resolution", started)
    return state


def build_parent_context_loader_node(
    *,
    timeline_loader: ParentLoader,
    pickup_loader: ParentLoader,
    schedule_loader: ParentLoader,
):
    async def parent_context_loader_node(state: SchoolOSAIState) -> SchoolOSAIState:
        started = start_node(state, "parent_context_loader")
        if state.get("final_response"):
            finish_node(state, "parent_context_loader", started)
            return state

        intent = str(state.get("parent_intent", "unsupported_or_out_of_scope"))
        family_context = dict(state.get("family_context", {}))
        resolved_student = state.get("resolved_student")
        evidence_records: list[dict[str, Any]] = []
        source_items: list[dict[str, str]] = []
        counter = 1

        if intent == "linked_children":
            students = list(state.get("authorized_students", []))
            for student in students:
                evidence_records.append(
                    _build_evidence(
                        "student_profile",
                        str(student.get("student_id")),
                        {
                            "display_name": student.get("display_name"),
                            "class_name": student.get("class_name"),
                        },
                        counter,
                    )
                )
                counter += 1
            source_items = _make_sources(("student_profile", "Student Profile"))

        elif intent == "family_timeline":
            events = await timeline_loader(
                tenant_id=state.get("tenant_id", ""),
                family_id=family_context.get("family_id"),
                student_id=str(resolved_student.get("student_id")) if resolved_student else None,
                limit=5,
            )
            for event in events:
                evidence_records.append(
                    _build_evidence(
                        "family_timeline",
                        event.get("student_id"),
                        {
                            "title": event.get("title"),
                            "description": event.get("description"),
                            "occurred_at": event.get("occurred_at"),
                        },
                        counter,
                    )
                )
                counter += 1
            state["timeline_events"] = events
            source_items = _make_sources(("family_timeline", "Family Timeline"))

        elif intent == "pickup_status":
            pickups = await pickup_loader(
                tenant_id=state.get("tenant_id", ""),
                parent_user_id=state.get("user_id", ""),
                student_id=str(resolved_student.get("student_id")) if resolved_student else None,
            )
            for pickup in pickups:
                evidence_records.append(
                    _build_evidence(
                        "pickup",
                        pickup.get("student_id"),
                        {
                            "status": pickup.get("status"),
                            "requested_at": pickup.get("requested_at"),
                            "released_at": pickup.get("released_at"),
                        },
                        counter,
                    )
                )
                counter += 1
            state["pickup_records"] = pickups
            source_items = _make_sources(("pickup", "Pickup Information"))

        elif intent == "child_schedule" and resolved_student:
            school_timezone, now_local = resolve_school_timezone(tenant_settings=state.get("school_context", {}))
            schedule = await schedule_loader(
                tenant_id=state.get("tenant_id", ""),
                student_id=str(resolved_student.get("student_id")),
                class_id=str(resolved_student.get("class_id")),
                academic_year=str(resolved_student.get("academic_year")),
                current_day_of_week=now_local.weekday(),
            )
            for entry in schedule:
                evidence_records.append(
                    _build_evidence(
                        "class_timetable",
                        entry.get("student_id"),
                        {
                            "period_name": entry.get("period_name"),
                            "start_time": entry.get("start_time"),
                            "end_time": entry.get("end_time"),
                            "school_timezone": school_timezone,
                        },
                        counter,
                    )
                )
                counter += 1
            state["schedule_records"] = schedule
            state["schedule_timezone"] = school_timezone
            source_items = _make_sources(("class_timetable", "Class Timetable"))

        elif intent == "module_availability" and resolved_student:
            evidence_records.append(
                _build_evidence(
                    "student_profile",
                    str(resolved_student.get("student_id")),
                    {
                        "display_name": resolved_student.get("display_name"),
                        "class_name": resolved_student.get("class_name"),
                        "homeroom_teacher": resolved_student.get("homeroom_teacher"),
                        "module_availability": resolved_student.get("module_availability"),
                    },
                    counter,
                )
            )
            source_items = _make_sources(("student_profile", "Student Profile"))

        elif intent in {"child_summary", "family_summary"}:
            if resolved_student:
                evidence_records.append(
                    _build_evidence(
                        "student_profile",
                        str(resolved_student.get("student_id")),
                        {
                            "display_name": resolved_student.get("display_name"),
                            "class_name": resolved_student.get("class_name"),
                            "homeroom_teacher": resolved_student.get("homeroom_teacher"),
                            "module_availability": resolved_student.get("module_availability"),
                        },
                        counter,
                    )
                )
                counter += 1
                events = await timeline_loader(
                    tenant_id=state.get("tenant_id", ""),
                    family_id=family_context.get("family_id"),
                    student_id=str(resolved_student.get("student_id")),
                    limit=2,
                )
                for event in events:
                    evidence_records.append(
                        _build_evidence(
                            "family_timeline",
                            event.get("student_id"),
                            {
                                "title": event.get("title"),
                                "occurred_at": event.get("occurred_at"),
                            },
                            counter,
                        )
                    )
                    counter += 1
                state["timeline_events"] = events
                source_items = _make_sources(("student_profile", "Student Profile"), ("family_timeline", "Family Timeline"))
            else:
                students = list(state.get("authorized_students", []))
                evidence_records.append(
                    _build_evidence(
                        "family_profile",
                        None,
                        {
                            "family_name": family_context.get("family_name"),
                            "linked_children_count": len(students),
                            "children": [
                                {
                                    "display_name": student.get("display_name"),
                                    "class_name": student.get("class_name"),
                                }
                                for student in students
                            ],
                        },
                        counter,
                    )
                )
                counter += 1
                preview_events = await timeline_loader(
                    tenant_id=state.get("tenant_id", ""),
                    family_id=family_context.get("family_id"),
                    student_id=None,
                    limit=3,
                )
                for event in preview_events:
                    evidence_records.append(
                        _build_evidence(
                            "family_timeline",
                            event.get("student_id"),
                            {
                                "title": event.get("title"),
                                "occurred_at": event.get("occurred_at"),
                            },
                            counter,
                        )
                    )
                    counter += 1
                state["timeline_events"] = preview_events
                source_items = _make_sources(("student_profile", "Student Profile"), ("family_timeline", "Family Timeline"))

        state["evidence_records"] = evidence_records
        state["source_items"] = source_items
        state["deterministic_suggestions"] = _DEFAULT_SUGGESTIONS.get(intent, _DEFAULT_SUGGESTIONS["help"])
        finish_node(state, "parent_context_loader", started)
        return state

    return parent_context_loader_node


def _deterministic_message(state: SchoolOSAIState) -> tuple[str, str | None]:
    intent = str(state.get("parent_intent", "unsupported_or_out_of_scope"))
    resolved_student = state.get("resolved_student")

    if intent == "linked_children":
        students = list(state.get("authorized_students", []))
        names = ", ".join(str(student.get("display_name")) for student in students)
        return f"You have {len(students)} linked child{'ren' if len(students) != 1 else ''}: {names}.", None

    if intent == "family_timeline":
        events = list(state.get("timeline_events", []))
        if not events:
            return "No family timeline events have been published yet.", "empty_timeline"
        latest = events[0]
        return f"The latest family update is {latest.get('title')}.", None

    if intent == "pickup_status":
        pickups = list(state.get("pickup_records", []))
        if not pickups:
            return "I could not find an active pickup request.", "no_active_pickup"
        active = next((pickup for pickup in pickups if str(pickup.get("status", "")).lower() in _ACTIVE_PICKUP_STATUSES), None)
        student_name = str(resolved_student.get("display_name")) if resolved_student else "your child"
        if active:
            return (
                f"{student_name} currently has an active pickup request. Its verified status is {active.get('status')}.",
                None,
            )
        latest = pickups[0]
        return (
            f"{student_name} does not currently have an active pickup request. His latest pickup request was {latest.get('status')}.",
            None,
        )

    if intent == "module_availability" and resolved_student:
        modules = dict(resolved_student.get("module_availability", {}))
        lines = [f"Verified information available for {resolved_student.get('display_name')}:"]
        for module_key, label in _MODULE_AVAILABILITY_ORDER:
            availability = dict(modules.get(module_key, {}))
            available = bool(availability.get("available", False))
            reason = availability.get("reason") or "Not available yet."
            if available:
                lines.append(f"- {label}: available")
            else:
                if isinstance(reason, str) and reason.strip() and not _is_duplicate_unavailable_reason(reason):
                    lines.append(f"- {label}: not available yet ({reason.strip()})")
                else:
                    lines.append(f"- {label}: not available yet")
        return "\n".join(lines), None

    if intent == "child_schedule" and resolved_student:
        schedule = list(state.get("schedule_records", []))
        if not schedule:
            return f"{resolved_student.get('display_name')} does not have any timetable entries scheduled today.", "empty_schedule"
        first = schedule[0]
        count = len(schedule)
        return (
            f"{resolved_student.get('display_name')} has {count} timetable entr{'ies' if count != 1 else 'y'} today. The first period is {first.get('period_name')} for {first.get('subject_name')} from {first.get('start_time')} to {first.get('end_time')}.",
            None,
        )

    if intent == "child_summary" and resolved_student:
        events = list(state.get("timeline_events", []))
        base = f"{resolved_student.get('display_name')} is in {resolved_student.get('class_name')}"
        if resolved_student.get("homeroom_teacher"):
            base = f"{base} with homeroom teacher {resolved_student.get('homeroom_teacher')}"
        if events:
            return f"{base}. The latest visible family update is {events[0].get('title')}.", None
        return f"{base}. No recent family timeline events are currently available for this child.", None

    students = list(state.get("authorized_students", []))
    timeline_events = list(state.get("timeline_events", []))
    message = f"Your family has {len(students)} linked child{'ren' if len(students) != 1 else ''}."
    if timeline_events:
        message = f"{message} The latest family update is {timeline_events[0].get('title')}."
    else:
        message = f"{message} No family timeline events have been published yet."
    return message, None


def _parse_provider_payload(raw_content: str) -> dict[str, Any] | None:
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_provider_payload(state: SchoolOSAIState, payload: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    evidence_records = {item["evidence_id"]: item for item in state.get("evidence_records", [])}
    used_evidence_ids = payload.get("used_evidence_ids", [])
    if not isinstance(used_evidence_ids, list) or not all(isinstance(item, str) for item in used_evidence_ids):
        issues.append("used_evidence_ids")
    else:
        for evidence_id in used_evidence_ids:
            if evidence_id not in evidence_records:
                issues.append(f"unknown_evidence:{evidence_id}")

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        issues.append("message")
    else:
        if _HTML_PATTERN.search(message):
            issues.append("html_content")
        if _WRITE_ACTION_PATTERN.search(message) and re.search(r"\b(i|we)\s+(sent|created|cancelled|updated|booked|paid|contacted)\b", message, re.IGNORECASE):
            issues.append("claimed_write_action")

    mentioned_students = payload.get("mentioned_students", [])
    allowed_names = {str(student.get("display_name")) for student in state.get("authorized_students", [])}
    if not isinstance(mentioned_students, list) or not all(isinstance(item, str) for item in mentioned_students):
        issues.append("mentioned_students")
    else:
        for name in mentioned_students:
            if name not in allowed_names:
                issues.append(f"unauthorized_student:{name}")

    return len(issues) == 0, issues


def build_parent_response_node(provider: LLMProvider):
    async def parent_response_node(state: SchoolOSAIState) -> SchoolOSAIState:
        started = start_node(state, "parent_response")
        if state.get("final_response"):
            finish_node(state, "parent_response", started)
            return state

        intent = str(state.get("parent_intent", "unsupported_or_out_of_scope"))
        deterministic_message, unavailable_reason = _deterministic_message(state)
        response_kind = "answer" if not unavailable_reason else "unavailable"

        use_provider = intent in {"family_summary", "child_summary"}
        state["provider"] = getattr(provider, "provider_name", "unknown")
        payload = None
        validation_issues: list[str] = []
        if use_provider:
            prompt = build_parent_summary_prompt(state)
            response = await provider.generate(prompt)
            state["token_usage"] = response.get("token_usage", {})
            payload = _parse_provider_payload(str(response.get("content", "")))
            if payload is None:
                validation_issues = ["malformed_output"]
            else:
                valid, validation_issues = _validate_provider_payload(state, payload)
                if not valid:
                    payload = None

        if payload is not None:
            message = str(payload.get("message", "")).strip()
            state["validation_result"] = {"passed": True, "issues": []}
            suggested = [item for item in payload.get("suggested_questions", []) if isinstance(item, str)][:3]
            if not suggested:
                suggested = list(state.get("deterministic_suggestions", []))
        else:
            message = deterministic_message
            state["validation_result"] = {"passed": False if validation_issues else True, "issues": validation_issues}
            suggested = list(state.get("deterministic_suggestions", []))

        student = _student_label(state["resolved_student"]) if state.get("resolved_student") else None
        _complete_response(
            state,
            status="completed" if not unavailable_reason else "unavailable",
            message=message,
            response_kind=response_kind,
            parent_intent=intent,
            unavailable_reason=unavailable_reason,
            student=student,
            sources=list(state.get("source_items", [])),
            suggested_questions=suggested,
        )

        finish_node(state, "parent_response", started)
        return state

    return parent_response_node


def build_parent_audit_node(db: Any):
    async def parent_audit_node(state: SchoolOSAIState) -> SchoolOSAIState:
        started = start_node(state, "parent_audit")
        if state.get("final_response") and db is not None:
            parent_profile = dict(state.get("parent_profile", {}))
            resolved_student = state.get("resolved_student") or {}
            actor_id = parent_profile.get("user_id")
            student_id = resolved_student.get("student_id")
            try:
                await log_action(
                    db=db,
                    tenant_id=UUID(str(state.get("tenant_id"))),
                    action="parent.assistant_used",
                    entity_type="User",
                    entity_id=UUID(str(actor_id)) if actor_id else None,
                    actor_id=UUID(str(actor_id)) if actor_id else None,
                    details={
                        "workflow": "parent_assistant",
                        "parent_intent": state.get("parent_intent"),
                        "status": state.get("final_response", {}).get("status"),
                        "student_id": str(student_id) if student_id else None,
                        "validation_issues": state.get("validation_result", {}).get("issues", []),
                    },
                )
            except Exception as exc:
                state.setdefault("errors", []).append(f"audit:{exc}")

        finish_node(state, "parent_audit", started)
        return state

    return parent_audit_node