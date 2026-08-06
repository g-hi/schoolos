from __future__ import annotations

import json
import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.readiness import compute_timetable_input_readiness
from shared.db.models import (
    BellSchedule,
    BellSchedulePeriod,
    SchoolWeekConfig,
    TeachingRoom,
    TimetablePolicyConstraint,
    TimetablePolicyException,
    TimetablePolicySet,
    WeeklyTeachingRequirement,
)


LEADERSHIP_ROLES = ["principal", "school_admin"]
REVIEWABLE_POLICY_SET_STATUSES = {"draft", "pending_review", "approved", "active", "suspended"}
REVIEWABLE_CONSTRAINT_STATUSES = {"draft", "pending_review", "approved", "active", "suspended"}
OPERATIONAL_CONSTRAINT_STATUSES = {"approved", "active"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_uuid(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _json_text(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)


def _period_numbers_from_rule(rule: Any) -> set[int]:
    period_numbers: set[int] = set()
    if isinstance(rule, dict):
        for key in ("period_number", "period", "slot"):
            value = rule.get(key)
            if isinstance(value, int):
                period_numbers.add(int(value))
        for key in ("period_numbers", "periods"):
            value = rule.get(key)
            if isinstance(value, list):
                for number in value:
                    if isinstance(number, int):
                        period_numbers.add(int(number))
    elif isinstance(rule, list):
        for value in rule:
            if isinstance(value, int):
                period_numbers.add(int(value))
    return period_numbers


def _policy_set_row(item: TimetablePolicySet) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "academic_year_id": str(item.academic_year_id),
        "term_id": str(item.term_id),
        "campus_id": _serialize_uuid(item.campus_id),
        "name": item.name,
        "lifecycle_status": item.lifecycle_status,
        "is_active": item.is_active,
        "created_at": item.created_at,
    }


def _constraint_row(item: TimetablePolicyConstraint, policy_set: TimetablePolicySet) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "policy_set_id": str(item.policy_set_id),
        "policy_set_name": policy_set.name,
        "academic_year_id": str(policy_set.academic_year_id),
        "term_id": str(policy_set.term_id),
        "campus_id": _serialize_uuid(policy_set.campus_id),
        "constraint_type": item.constraint_type,
        "category": item.category,
        "enforcement_level": item.enforcement_level,
        "lifecycle_status": item.lifecycle_status,
        "scope_type": item.scope_type,
        "scope_reference_id": _serialize_uuid(item.scope_reference_id),
        "scope_reference_code": item.scope_reference_code,
        "parameters": item.parameters_json,
        "weight": item.weight,
        "priority": item.priority,
        "is_active": item.is_active,
        "explanation": item.explanation,
        "requires_approval": item.requires_approval,
    }


def _exception_row(item: TimetablePolicyException) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "policy_set_id": _serialize_uuid(item.policy_set_id),
        "constraint_id": _serialize_uuid(item.constraint_id),
        "scope_type": item.scope_type,
        "scope_reference_id": _serialize_uuid(item.scope_reference_id),
        "scope_reference_code": item.scope_reference_code,
        "approval_state": item.approval_state,
        "reason": item.reason,
        "is_active": item.is_active,
    }


def _requirement_row(item: WeeklyTeachingRequirement) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "campus_id": _serialize_uuid(item.campus_id),
        "academic_year_id": _serialize_uuid(item.academic_year_id),
        "term_id": _serialize_uuid(item.term_id),
        "class_id": _serialize_uuid(item.class_id),
        "subject_id": _serialize_uuid(item.subject_id),
        "teacher_id": _serialize_uuid(item.teacher_id),
        "sessions_per_week": item.sessions_per_week,
        "periods_per_session": item.periods_per_session,
        "min_daily_sessions": item.min_daily_sessions,
        "max_daily_sessions": item.max_daily_sessions,
        "specialist_room_type": item.specialist_room_type,
        "preferred_period_numbers": list(item.preferred_period_numbers or []),
        "forbidden_period_numbers": list(item.forbidden_period_numbers or []),
        "has_fixed_sessions": item.has_fixed_sessions,
        "fixed_session_rules": list(item.fixed_session_rules or []),
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _room_row(item: TeachingRoom) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "room_code": item.room_code,
        "room_name": item.room_name,
        "room_type": item.room_type,
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _school_week_row(item: SchoolWeekConfig) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "operational_weekdays": list(item.operational_weekdays or []),
        "review_status": item.review_status,
        "is_active": item.is_active,
    }


def _bell_period_row(item: BellSchedulePeriod) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "period_number": item.period_number,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "is_teaching_period": item.is_teaching_period,
        "is_active": item.is_active,
    }


def _constraint_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["policy_set_id"],
        item["constraint_type"],
        item["scope_type"],
        item.get("scope_reference_id"),
        item.get("scope_reference_code"),
        item["enforcement_level"],
        _json_text(item.get("parameters", {})),
    )


def _policy_scope_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["academic_year_id"], item["term_id"], item.get("campus_id"))


def _constraint_guidance(constraint_type: str) -> str:
    mapping = {
        "teacher_unavailable": "Move the sessions off the blocked window or soften the rule.",
        "class_unavailable": "Shift the class sessions or relax the unavailable window.",
        "room_required_type": "Activate or create the required room type, or reduce the rule to soft.",
        "room_capacity": "Use a larger room or lower the capacity threshold.",
        "subject_required_weekly_sessions": "Add available teaching periods or reduce the required weekly sessions.",
        "subject_required_weekly_minutes": "Increase teaching time or lower the required minutes.",
        "fixed_session": "Keep the locked slot and adjust surrounding constraints, or remove the fixed slot.",
        "avoid_period": "Move the affected sessions or relax the avoidance rule.",
        "preferred_period": "Treat the rule as a preference when strict placement is not possible.",
        "lunch_protection": "Protect lunch and move the conflicting sessions elsewhere.",
        "campus_travel_buffer": "Add spacing between campus moves or reduce travel-dependent assignments.",
        "teacher_max_daily_sessions": "Reduce the daily load or add more teaching periods.",
        "teacher_min_break": "Insert breaks or lower the minimum break requirement.",
        "teacher_max_consecutive_sessions": "Split the load or reduce the consecutive-session cap.",
        "subject_spread_across_days": "Spread the subject across more days or lower the spread requirement.",
        "subject_preferred_period": "Use the preferred periods when feasible or soften the rule.",
        "balanced_teacher_load": "Treat this as an optimization hint rather than a blocker.",
        "minimize_teacher_gaps": "Treat this as an optimization hint rather than a blocker.",
        "minimize_room_changes": "Treat this as an optimization hint rather than a blocker.",
    }
    return mapping.get(constraint_type, "Review the policy scope, adjust the constraint, or approve a targeted exception.")


def _constraint_route(constraint_type: str) -> str:
    if constraint_type in {"room_required_type", "room_capacity", "room_unavailable"}:
        return "/leadership/timetable-setup/rooms"
    if constraint_type.startswith("teacher_") or constraint_type in {"campus_travel_buffer", "balanced_teacher_load", "minimize_teacher_gaps"}:
        return "/leadership/people"
    return "/leadership/timetable-setup/teaching-requirements"


def analyze_policy_state(
    *,
    readiness: dict[str, Any],
    policy_sets: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    school_weeks: list[dict[str, Any]],
    bell_periods: list[dict[str, Any]],
) -> dict[str, Any]:
    policy_set_counts = dict(sorted(Counter(item["lifecycle_status"] for item in policy_sets).items()))
    constraint_counts = dict(sorted(Counter(item["lifecycle_status"] for item in constraints).items()))
    exception_counts = dict(sorted(Counter(item["approval_state"] for item in exceptions).items()))

    active_policy_sets = [item for item in policy_sets if item["lifecycle_status"] == "active" and item["is_active"]]
    active_constraints = [item for item in constraints if item["lifecycle_status"] in OPERATIONAL_CONSTRAINT_STATUSES and item["is_active"]]
    reviewable_constraints = [item for item in constraints if item["lifecycle_status"] in REVIEWABLE_CONSTRAINT_STATUSES]

    teaching_period_numbers = sorted({item["period_number"] for item in bell_periods if item["is_active"] and item["is_teaching_period"]})
    teaching_period_count = len(teaching_period_numbers)
    active_weekday_counts = [len(item["operational_weekdays"]) for item in school_weeks if item["is_active"] and item["review_status"] == "approved"]
    max_weekday_count = max(active_weekday_counts) if active_weekday_counts else 0
    max_daily_capacity = teaching_period_count if max_weekday_count == 0 else int(math.ceil(teaching_period_count / max_weekday_count))
    active_room_types = {item["room_type"] for item in rooms if item["is_active"] and item["review_status"] == "approved"}

    diagnostics: list[dict[str, Any]] = []

    policy_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in policy_sets:
        if item["lifecycle_status"] in REVIEWABLE_POLICY_SET_STATUSES:
            policy_groups[_policy_scope_key(item)].append(item)
    for scope_key, items in sorted(policy_groups.items(), key=lambda row: row[0]):
        active_count = sum(1 for item in items if item["lifecycle_status"] == "active" and item["is_active"])
        if active_count > 1:
            diagnostics.append(
                {
                    "diagnostic_key": f"policy-set-conflict:{scope_key}",
                    "kind": "conflict",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Multiple active policy sets share the same scope",
                    "summary": "Only one active policy set may govern a year/term/campus scope at a time.",
                    "explanation": f"{active_count} active policy sets were found for the same academic year, term, and campus scope.",
                    "affected_count": active_count,
                    "policy_set_ids": [item["id"] for item in items if item["lifecycle_status"] == "active" and item["is_active"]],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-policies/policy-sets",
                    "recommended_action": "Retire or suspend redundant active policy sets until only one remains in scope.",
                    "requires_human_authorization": True,
                    "resolved": False,
                }
            )
        elif len(items) > 1:
            diagnostics.append(
                {
                    "diagnostic_key": f"policy-set-reviewable:{scope_key}",
                    "kind": "conflict",
                    "severity": "warning",
                    "status": "attention",
                    "title": "Multiple reviewable policy sets share the same scope",
                    "summary": "Parallel drafts increase approval ambiguity.",
                    "explanation": f"{len(items)} reviewable policy sets were found for the same academic year, term, and campus scope.",
                    "affected_count": len(items),
                    "policy_set_ids": [item["id"] for item in items],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-policies/policy-sets",
                    "recommended_action": "Consolidate drafts before approval so one scope has one candidate policy set.",
                    "requires_human_authorization": True,
                    "resolved": False,
                }
            )

    constraint_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in constraints:
        if item["lifecycle_status"] in REVIEWABLE_CONSTRAINT_STATUSES:
            constraint_groups[_constraint_key(item)].append(item)
    for key, items in sorted(constraint_groups.items(), key=lambda row: row[0]):
        if len(items) > 1:
            active_count = sum(1 for item in items if item["lifecycle_status"] in OPERATIONAL_CONSTRAINT_STATUSES and item["is_active"])
            severity = "blocker" if active_count > 1 else "warning"
            diagnostics.append(
                {
                    "diagnostic_key": f"constraint-duplicate:{key}",
                    "kind": "conflict",
                    "severity": severity,
                    "status": "fail" if severity == "blocker" else "attention",
                    "title": "Duplicate exact policy constraints were found",
                    "summary": "Exact duplicates should be merged or retired to keep diagnostics deterministic.",
                    "explanation": f"{len(items)} constraints share the same policy set, scope, enforcement level, and parameters.",
                    "affected_count": len(items),
                    "policy_set_ids": [item["policy_set_id"] for item in items],
                    "constraint_ids": [item["id"] for item in items],
                    "setup_route": "/leadership/timetable-policies/policy-sets",
                    "recommended_action": "Retire redundant copies or merge them into one approved version.",
                    "requires_human_authorization": True,
                    "resolved": False,
                }
            )

    approved_exceptions = [item for item in exceptions if item["approval_state"] == "approved" and item["is_active"]]
    if approved_exceptions:
        exception_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for item in approved_exceptions:
            exception_groups[(item.get("policy_set_id"), item.get("constraint_id"), item["scope_type"], item.get("scope_reference_id"), item.get("scope_reference_code"))].append(item)
        for key, items in sorted(exception_groups.items(), key=lambda row: row[0]):
            if len(items) > 1:
                diagnostics.append(
                    {
                        "diagnostic_key": f"exception-duplicate:{key}",
                        "kind": "conflict",
                        "severity": "warning",
                        "status": "attention",
                        "title": "Multiple approved exceptions overlap",
                        "summary": "Overlapping exceptions reduce the clarity of the policy baseline.",
                        "explanation": f"{len(items)} approved exceptions target the same scope and should be consolidated.",
                        "affected_count": len(items),
                        "policy_set_ids": [item.get("policy_set_id") for item in items if item.get("policy_set_id")],
                        "constraint_ids": [item.get("constraint_id") for item in items if item.get("constraint_id")],
                        "setup_route": "/leadership/timetable-policies/exceptions",
                        "recommended_action": "Consolidate overlapping exceptions into one scoped approval.",
                        "requires_human_authorization": True,
                        "resolved": False,
                    }
                )

    for item in requirements:
        if not (item["is_active"] and item["review_status"] == "approved"):
            continue
        if item["sessions_per_week"] > teaching_period_count:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:sessions-per-week:{item['id']}",
                    "kind": "feasibility",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Weekly requirement exceeds available teaching periods",
                    "summary": "The requirement cannot be scheduled without additional teaching periods.",
                    "explanation": f"Requirement {item['sessions_per_week']} sessions/week exceeds the {teaching_period_count} active teaching periods currently available.",
                    "affected_count": 1,
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/bell-schedules",
                    "recommended_action": "Add active teaching periods or reduce the weekly session count.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        if item["min_daily_sessions"] > max_daily_capacity:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:min-daily:{item['id']}",
                    "kind": "feasibility",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Minimum daily sessions exceed daily capacity",
                    "summary": "The minimum daily load cannot fit into the configured school week.",
                    "explanation": f"Minimum daily sessions {item['min_daily_sessions']} exceeds the estimated daily capacity of {max_daily_capacity}.",
                    "affected_count": 1,
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/teaching-requirements",
                    "recommended_action": "Lower the minimum daily session requirement or expand the school week.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        if item["max_daily_sessions"] > max_daily_capacity:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:max-daily:{item['id']}",
                    "kind": "feasibility",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Maximum daily sessions exceed daily capacity",
                    "summary": "The requirement cannot fit within the current timetable envelope.",
                    "explanation": f"Maximum daily sessions {item['max_daily_sessions']} exceeds the estimated daily capacity of {max_daily_capacity}.",
                    "affected_count": 1,
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/teaching-requirements",
                    "recommended_action": "Lower the maximum daily session limit or add more operational weekdays.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        if item["specialist_room_type"] and item["specialist_room_type"] not in active_room_types:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:room-type:{item['id']}",
                    "kind": "feasibility",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Required specialist room type is unavailable",
                    "summary": "At least one active room must match the specialist room type.",
                    "explanation": f"No active approved room matches specialist_room_type='{item['specialist_room_type']}'.",
                    "affected_count": 1,
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/rooms",
                    "recommended_action": "Create or activate a matching room type, or relax the specialist requirement.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        fixed_periods: set[int] = set()
        for rule in item["fixed_session_rules"]:
            fixed_periods.update(_period_numbers_from_rule(rule))
        if item["has_fixed_sessions"] and not item["fixed_session_rules"]:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:fixed-session-rules:{item['id']}",
                    "kind": "feasibility",
                    "severity": "warning",
                    "status": "attention",
                    "title": "Fixed sessions are enabled without explicit slot rules",
                    "summary": "The timetable can still be produced, but the lock points are underspecified.",
                    "explanation": "has_fixed_sessions is true, but fixed_session_rules is empty.",
                    "affected_count": 1,
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/teaching-requirements",
                    "recommended_action": "Add explicit fixed session rules or disable the fixed-session flag.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        invalid_fixed_periods = sorted(p for p in fixed_periods if p not in set(teaching_period_numbers))
        if invalid_fixed_periods:
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:fixed-session-periods:{item['id']}",
                    "kind": "feasibility",
                    "severity": "blocker",
                    "status": "fail",
                    "title": "Fixed session rules reference unavailable periods",
                    "summary": "Locked slots must refer to active teaching periods.",
                    "explanation": f"Fixed session rules reference unavailable period numbers: {invalid_fixed_periods}.",
                    "affected_count": len(invalid_fixed_periods),
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/bell-schedules",
                    "recommended_action": "Update the fixed session rules to match the active bell schedule.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )
        preferred_periods = {int(value) for value in item["preferred_period_numbers"] if isinstance(value, int)}
        forbidden_periods = {int(value) for value in item["forbidden_period_numbers"] if isinstance(value, int)}
        if preferred_periods and preferred_periods.issubset(forbidden_periods):
            diagnostics.append(
                {
                    "diagnostic_key": f"feasibility:preference-tension:{item['id']}",
                    "kind": "impact",
                    "severity": "warning",
                    "status": "attention",
                    "title": "Preferred periods are fully blocked by forbidden periods",
                    "summary": "The requirement has a soft conflict that reduces timetable flexibility.",
                    "explanation": "All preferred periods are also marked forbidden for this requirement.",
                    "affected_count": len(preferred_periods),
                    "policy_set_ids": [],
                    "constraint_ids": [],
                    "setup_route": "/leadership/timetable-setup/teaching-requirements",
                    "recommended_action": "Relax either the preferred or forbidden period list to restore flexible placement options.",
                    "requires_human_authorization": False,
                    "resolved": False,
                    "related_requirement_id": item["id"],
                }
            )

    impact_items: list[dict[str, Any]] = []
    for item in reviewable_constraints:
        matching_requirements = []
        if item["scope_type"] == "teacher" and item.get("scope_reference_id"):
            matching_requirements = [row for row in requirements if row["teacher_id"] == item["scope_reference_id"] and row["is_active"]]
        elif item["scope_type"] == "class" and item.get("scope_reference_id"):
            matching_requirements = [row for row in requirements if row["class_id"] == item["scope_reference_id"] and row["is_active"]]
        elif item["scope_type"] == "subject" and item.get("scope_reference_id"):
            matching_requirements = [row for row in requirements if row["subject_id"] == item["scope_reference_id"] and row["is_active"]]
        elif item["scope_type"] == "room" and item.get("scope_reference_code"):
            matching_requirements = [row for row in requirements if row["specialist_room_type"] == item["scope_reference_code"] and row["is_active"]]
        else:
            matching_requirements = [row for row in requirements if row["is_active"]]

        matching_rooms = []
        if item["constraint_type"] in {"room_required_type", "room_unavailable", "room_capacity"}:
            room_type = (item.get("parameters") or {}).get("required_room_type") or item.get("scope_reference_code")
            if room_type:
                matching_rooms = [row for row in rooms if row["is_active"] and row["room_type"] == room_type]

        approved_exception_count = sum(
            1
            for exc in exceptions
            if exc["approval_state"] == "approved" and exc["is_active"] and (exc.get("constraint_id") == item["id"] or exc.get("policy_set_id") == item["policy_set_id"])
        )

        impact_items.append(
            {
                "impact_key": f"impact:{item['constraint_type']}:{item['id']}",
                "constraint_id": item["id"],
                "policy_set_id": item["policy_set_id"],
                "constraint_type": item["constraint_type"],
                "category": item["category"],
                "lifecycle_status": item["lifecycle_status"],
                "enforcement_level": item["enforcement_level"],
                "scope_type": item["scope_type"],
                "scope_reference_id": item.get("scope_reference_id"),
                "scope_reference_code": item.get("scope_reference_code"),
                "severity": "blocker" if item["lifecycle_status"] in OPERATIONAL_CONSTRAINT_STATUSES and item["enforcement_level"] == "hard" else "warning" if item["enforcement_level"] in {"soft", "preference"} else "information",
                "affected_requirement_count": len(matching_requirements),
                "affected_room_count": len(matching_rooms),
                "affected_teacher_count": len({row["teacher_id"] for row in matching_requirements if row["teacher_id"] is not None}),
                "affected_class_count": len({row["class_id"] for row in matching_requirements if row["class_id"] is not None}),
                "affected_subject_count": len({row["subject_id"] for row in matching_requirements if row["subject_id"] is not None}),
                "summary": item.get("explanation") or f"{item['constraint_type']} affects the current timetable scope.",
                "recommended_action": _constraint_guidance(item["constraint_type"]),
                "setup_route": _constraint_route(item["constraint_type"]),
                "requires_human_authorization": bool(item["requires_approval"] or item["enforcement_level"] == "hard"),
                "resolved": False,
                "approved_exception_count": approved_exception_count,
            }
        )
        if approved_exception_count > 0:
            impact_items[-1]["summary"] = f"{impact_items[-1]['summary']} One or more approved exceptions already target this scope."

    blocker_count = sum(1 for item in diagnostics if item["severity"] == "blocker")
    warning_count = sum(1 for item in diagnostics if item["severity"] == "warning")
    information_count = sum(1 for item in diagnostics if item["severity"] == "information")
    pending_policy_items = sum(1 for item in policy_sets if item["lifecycle_status"] in {"draft", "pending_review"})
    pending_constraint_items = sum(1 for item in constraints if item["lifecycle_status"] in {"draft", "pending_review"})
    pending_exception_items = sum(1 for item in exceptions if item["approval_state"] == "pending_review")
    pending_approval_count = pending_policy_items + pending_constraint_items + pending_exception_items

    if blocker_count > 0:
        readiness_status = "blocked"
    elif pending_approval_count > 0:
        readiness_status = "awaiting_human_approval"
    elif warning_count > 0:
        readiness_status = "conditionally_ready"
    else:
        readiness_status = "ready"

    generation_allowed = blocker_count == 0 and pending_approval_count == 0
    guidance = sorted(
        [
            {
                "guidance_key": f"resolve:{item.get('diagnostic_key', item.get('impact_key', 'item'))}",
                "priority_score": 100 if item["severity"] == "blocker" else 70 if item["severity"] == "warning" else 40,
                "title": item.get("title", item.get("constraint_type", "Policy impact")),
                "why": item.get("explanation", item.get("summary", "")),
                "recommended_action": item.get("recommended_action", item.get("summary", "Review the policy scope and resolve the conflict.")),
                "setup_route": item.get("setup_route", "/leadership/timetable-policies"),
                "authorized_roles": LEADERSHIP_ROLES,
                "requires_human_authorization": item["requires_human_authorization"],
                "agent_can_execute": False,
            }
            for item in diagnostics + impact_items
        ],
        key=lambda row: (-row["priority_score"], row["guidance_key"]),
    )[:20]

    return {
        "generated_at": _now(),
        "policy_set_counts": policy_set_counts,
        "constraint_counts": constraint_counts,
        "exception_counts": exception_counts,
        "summary": {
            "policy_set_count": len(policy_sets),
            "reviewable_policy_set_count": len(policy_sets),
            "active_policy_set_count": len(active_policy_sets),
            "constraint_count": len(constraints),
            "reviewable_constraint_count": len(reviewable_constraints),
            "active_constraint_count": len(active_constraints),
            "exception_count": len(exceptions),
            "conflict_count": sum(1 for item in diagnostics if item["kind"] == "conflict"),
            "feasibility_count": sum(1 for item in diagnostics if item["kind"] == "feasibility"),
            "impact_count": len(impact_items),
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "information_count": information_count,
            "pending_approval_count": pending_approval_count,
            "teaching_period_count": teaching_period_count,
            "max_daily_capacity": max_daily_capacity,
        },
        "generation": {
            "generation_allowed": generation_allowed,
            "policy_generation_allowed": generation_allowed,
            "readiness_status": readiness_status,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "information_count": information_count,
            "pending_approval_count": pending_approval_count,
            "conditional_ready": blocker_count == 0 and pending_approval_count == 0 and warning_count > 0,
            "required_actions": [
                {
                    "diagnostic_key": item["diagnostic_key"],
                    "title": item["title"],
                    "recommended_action": item["recommended_action"],
                    "setup_route": item["setup_route"],
                    "requires_human_authorization": item["requires_human_authorization"],
                    "authorized_roles": LEADERSHIP_ROLES,
                }
                for item in diagnostics
                if item["severity"] == "blocker" or item["status"] == "pending_review"
            ],
        },
        "conflicts": diagnostics,
        "feasibility": [item for item in diagnostics if item["kind"] == "feasibility"],
        "impact": impact_items,
        "resolution_guidance": guidance,
        "readiness": readiness,
    }


async def _load_rows(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    readiness = await compute_timetable_input_readiness(db, tenant_id)
    policy_sets = (await db.execute(select(TimetablePolicySet).where(TimetablePolicySet.tenant_id == tenant_id).order_by(TimetablePolicySet.created_at.asc()))).scalars().all()
    constraint_rows = (await db.execute(select(TimetablePolicyConstraint, TimetablePolicySet).join(TimetablePolicySet, TimetablePolicySet.id == TimetablePolicyConstraint.policy_set_id).where(TimetablePolicyConstraint.tenant_id == tenant_id).order_by(TimetablePolicyConstraint.created_at.asc()))).all()
    exceptions = (await db.execute(select(TimetablePolicyException).where(TimetablePolicyException.tenant_id == tenant_id).order_by(TimetablePolicyException.created_at.asc()))).scalars().all()
    requirements = (await db.execute(select(WeeklyTeachingRequirement).where(WeeklyTeachingRequirement.tenant_id == tenant_id).order_by(WeeklyTeachingRequirement.created_at.asc()))).scalars().all()
    rooms = (await db.execute(select(TeachingRoom).where(TeachingRoom.tenant_id == tenant_id).order_by(TeachingRoom.created_at.asc()))).scalars().all()
    school_weeks = (await db.execute(select(SchoolWeekConfig).where(SchoolWeekConfig.tenant_id == tenant_id).order_by(SchoolWeekConfig.created_at.asc()))).scalars().all()
    bell_periods = (await db.execute(select(BellSchedulePeriod).join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id).where(BellSchedulePeriod.tenant_id == tenant_id, BellSchedule.tenant_id == tenant_id).order_by(BellSchedulePeriod.period_number.asc()))).scalars().all()
    return {
        "readiness": readiness,
        "policy_sets": [_policy_set_row(item) for item in policy_sets],
        "constraints": [_constraint_row(item, policy_set) for item, policy_set in constraint_rows],
        "exceptions": [_exception_row(item) for item in exceptions],
        "requirements": [_requirement_row(item) for item in requirements],
        "rooms": [_room_row(item) for item in rooms],
        "school_weeks": [_school_week_row(item) for item in school_weeks],
        "bell_periods": [_bell_period_row(item) for item in bell_periods],
    }


async def build_policy_diagnostics_payload(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    rows = await _load_rows(db, tenant_id)
    payload = analyze_policy_state(**rows)
    payload["policy_counts"] = {
        "policy_sets": len(rows["policy_sets"]),
        "constraints": len(rows["constraints"]),
        "exceptions": len(rows["exceptions"]),
        "requirements": len(rows["requirements"]),
        "rooms": len(rows["rooms"]),
        "school_weeks": len(rows["school_weeks"]),
        "bell_periods": len(rows["bell_periods"]),
    }
    return payload