from __future__ import annotations

import uuid
from datetime import date as date_type

from shared.db.models import (
    BellSchedule,
    OperationalCalendarEvent,
    TeachingRoom,
    WeeklyTeachingRequirement,
)


# Agent-safe proposal contracts: these create candidate records only.
# Approval is an explicit leadership action and is never implicit.

def propose_calendar_entry(*, tenant_id: uuid.UUID, actor_id: uuid.UUID, payload: dict) -> OperationalCalendarEvent:
    return OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        academic_year_id=payload.get("academic_year_id"),
        term_id=payload.get("term_id"),
        event_name=payload["event_name"],
        description=payload.get("description"),
        start_date=payload["start_date"],
        end_date=payload["end_date"],
        is_all_day=payload.get("is_all_day", True),
        event_type=payload["event_type"],
        teaching_day_effect=payload.get("teaching_day_effect", "no_change"),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        source_reference=payload.get("source_reference"),
        import_batch_id=payload.get("import_batch_id"),
        original_source_text=payload.get("original_source_text"),
        created_by_user_id=actor_id,
        reviewed_by_user_id=None,
        approved_by_user_id=None,
        is_active=True,
    )


def propose_bell_schedule(*, tenant_id: uuid.UUID, actor_id: uuid.UUID, payload: dict) -> BellSchedule:
    return BellSchedule(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        academic_year_id=payload.get("academic_year_id"),
        term_id=payload.get("term_id"),
        school_week_config_id=payload.get("school_week_config_id"),
        name=payload["name"],
        schedule_type=payload.get("schedule_type", "normal"),
        effective_start_date=payload.get("effective_start_date"),
        effective_end_date=payload.get("effective_end_date"),
        is_default=payload.get("is_default", False),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
        created_by_user_id=actor_id,
        approved_by_user_id=None,
    )


def propose_room_mapping(*, tenant_id: uuid.UUID, payload: dict) -> TeachingRoom:
    return TeachingRoom(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload.get("campus_id"),
        room_code=payload["room_code"],
        room_name=payload["room_name"],
        room_type=payload["room_type"],
        capacity=payload.get("capacity", 0),
        floor_or_location=payload.get("floor_or_location"),
        specialist_capabilities=payload.get("specialist_capabilities", []),
        accessibility_notes=payload.get("accessibility_notes"),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
    )


def propose_teaching_requirement(*, tenant_id: uuid.UUID, payload: dict) -> WeeklyTeachingRequirement:
    return WeeklyTeachingRequirement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=payload["campus_id"],
        academic_year_id=payload["academic_year_id"],
        term_id=payload["term_id"],
        class_id=payload["class_id"],
        subject_id=payload["subject_id"],
        teacher_id=payload.get("teacher_id"),
        sessions_per_week=payload["sessions_per_week"],
        periods_per_session=payload.get("periods_per_session", 1),
        min_daily_sessions=payload.get("min_daily_sessions", 0),
        max_daily_sessions=payload.get("max_daily_sessions", 3),
        double_period_mode=payload.get("double_period_mode", "none"),
        specialist_room_type=payload.get("specialist_room_type"),
        preferred_period_numbers=payload.get("preferred_period_numbers", []),
        forbidden_period_numbers=payload.get("forbidden_period_numbers", []),
        has_fixed_sessions=payload.get("has_fixed_sessions", False),
        fixed_session_rules=payload.get("fixed_session_rules", []),
        priority=payload.get("priority", 100),
        source_type=payload.get("source_type", "agent_recommendation"),
        review_status="pending_review",
        is_active=True,
    )


def run_timetable_readiness(*, checked_at: date_type | None = None) -> dict:
    return {
        "action": "run_timetable_readiness",
        "checked_at": checked_at,
        "note": "Invoke services.gateway.timetable_setup.readiness.compute_timetable_input_readiness with tenant-scoped DB session.",
    }


def inspect_workbook(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "inspect_workbook",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Read-only inspection of workbook summary, sheets, mappings and diagnostics.",
    }


def propose_sheet_mappings(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "propose_sheet_mappings",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Produce deterministic mapping suggestions only; does not confirm or persist approvals.",
    }


def propose_column_mappings(*, batch_id: uuid.UUID, sheet_name: str) -> dict:
    return {
        "action": "propose_column_mappings",
        "batch_id": str(batch_id),
        "sheet_name": sheet_name,
        "safe": True,
        "note": "Suggest column mappings and confidence metadata only.",
    }


def explain_workbook_diagnostics(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "explain_workbook_diagnostics",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Summarizes blockers/warnings/information without changing commit state.",
    }


def validate_workbook(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "validate_workbook",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Runs deterministic validation checks only.",
    }


def summarize_commit_plan(*, batch_id: uuid.UUID) -> dict:
    return {
        "action": "summarize_commit_plan",
        "batch_id": str(batch_id),
        "safe": True,
        "note": "Produces expected create/update/unchanged/rejected counts before approval.",
    }
