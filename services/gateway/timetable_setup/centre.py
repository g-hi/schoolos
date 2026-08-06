from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.readiness import compute_timetable_input_readiness
from shared.db.models import (
    AuditLog,
    BellSchedule,
    BellSchedulePeriod,
    CalendarEventCandidate,
    CalendarNotificationPlan,
    CalendarSourceDocument,
    Class,
    ImportBatch,
    ImportRowResult,
    OperationalCalendarEvent,
    SchoolWeekConfig,
    Subject,
    Teacher,
    TeachingRoom,
    WeeklyTeachingRequirement,
)


LEADERSHIP_ROLES = ["principal", "school_admin"]

STEP_SOURCE_MODELS = {
    "operational_calendar": OperationalCalendarEvent,
    "school_week": SchoolWeekConfig,
    "bell_schedules": BellSchedule,
    "teaching_rooms": TeachingRoom,
    "weekly_requirements": WeeklyTeachingRequirement,
}

ALLOWED_ISSUE_SEVERITIES = {"blocker", "warning", "information"}
ALLOWED_ISSUE_SOURCES = {
    "readiness_check",
    "approval_queue",
    "import_batch",
    "pdf_import",
    "workbook_import",
    "calendar_event",
    "calendar_candidate",
    "notification_plan",
}
ALLOWED_ACTIVITY_ACTION_TYPES = {
    "timetable_setup.calendar",
    "timetable_setup.imports",
    "timetable_setup.centre",
    "timetable_setup.readiness",
}
ALLOWED_ACTIVITY_ENTITY_TYPES = {
    "OperationalCalendarEvent",
    "CalendarEventCandidate",
    "CalendarNotificationPlan",
    "ImportBatch",
    "ImportRowResult",
    "SchoolWeekConfig",
    "BellSchedule",
    "BellSchedulePeriod",
    "TeachingRoom",
    "WeeklyTeachingRequirement",
    "TimetableSetupCentre",
}
ALLOWED_IMPORT_STATUS_NAMES = {
    "uploaded",
    "parsing",
    "mapping_required",
    "preview_ready",
    "validation_failed",
    "validated",
    "committed",
    "failed",
    "cancelled",
}
ALLOWED_PDF_SUMMARY_STATUSES = {
    "uploaded",
    "preflighting",
    "extracting",
    "extraction_failed",
    "ocr_required",
    "review_ready",
    "partially_reviewed",
    "ready_to_commit",
    "committed",
    "cancelled",
}

AGENT_ALLOWED_ACTIONS = [
    "inspect_setup_state",
    "summarize_readiness",
    "explain_blockers",
    "recommend_corrective_actions",
    "identify_next_step",
    "prepare_navigation_action_plan",
]

AGENT_PROHIBITED_ACTIONS = [
    "approve_import_mappings",
    "approve_calendar_candidates",
    "publish_events",
    "commit_imports",
    "override_blockers",
    "mark_school_ready_without_validation",
]

STEP_DEFINITIONS = [
    {
        "step_key": "operational_calendar",
        "title": "Operational Calendar",
        "weight": 10,
        "route": "/leadership/timetable-setup/calendar",
        "required_minimum": 1,
        "policy_rule": "Approved operational events are required before timetable generation.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "school_week",
        "title": "School Week Configuration",
        "weight": 8,
        "route": "/leadership/timetable-setup/school-week",
        "required_minimum": 1,
        "policy_rule": "At least one approved active school week configuration is required.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "bell_schedules",
        "title": "Bell Schedules",
        "weight": 10,
        "route": "/leadership/timetable-setup/bell-schedules",
        "required_minimum": 1,
        "policy_rule": "At least one approved active bell schedule is required.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": ["school_week"],
    },
    {
        "step_key": "teaching_periods",
        "title": "Teaching Periods",
        "weight": 8,
        "route": "/leadership/timetable-setup/bell-schedules",
        "required_minimum": 1,
        "policy_rule": "Active schedules must expose at least one active teaching period.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": ["bell_schedules"],
    },
    {
        "step_key": "teaching_rooms",
        "title": "Teaching Rooms",
        "weight": 8,
        "route": "/leadership/timetable-setup/rooms",
        "required_minimum": 1,
        "policy_rule": "Specialist requirements must map to available active room types.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "canonical_classes",
        "title": "Canonical Classes",
        "weight": 8,
        "route": "/leadership/academic-structure/classes",
        "required_minimum": 1,
        "policy_rule": "Canonical classes are required to scope weekly teaching requirements.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "subjects",
        "title": "Subjects",
        "weight": 8,
        "route": "/leadership/academic-structure/subject-offerings",
        "required_minimum": 1,
        "policy_rule": "Subjects are required before class-subject requirements can be validated.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "teachers",
        "title": "Teacher Profiles",
        "weight": 8,
        "route": "/leadership/people",
        "required_minimum": 1,
        "policy_rule": "Teacher profiles support requirement assignment and scheduling accountability.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "weekly_requirements",
        "title": "Weekly Teaching Requirements",
        "weight": 14,
        "route": "/leadership/timetable-setup/teaching-requirements",
        "required_minimum": 1,
        "policy_rule": "Approved active weekly requirements are mandatory for generation readiness.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": ["canonical_classes", "subjects"],
    },
    {
        "step_key": "intake_imports",
        "title": "Workbook and PDF Intake",
        "weight": 8,
        "route": "/leadership/timetable-setup/imports/workbooks",
        "required_minimum": 0,
        "policy_rule": "Imported data remains non-operational until deterministic validation and explicit commit.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [],
    },
    {
        "step_key": "approvals_and_readiness",
        "title": "Approvals and Readiness Review",
        "weight": 10,
        "route": "/leadership/timetable-setup/readiness",
        "required_minimum": 0,
        "policy_rule": "Generation can proceed only when deterministic blockers are clear and approval queues are resolved.",
        "authorized_roles": LEADERSHIP_ROLES,
        "prerequisites": [
            "operational_calendar",
            "school_week",
            "bell_schedules",
            "teaching_periods",
            "canonical_classes",
            "subjects",
            "weekly_requirements",
        ],
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _count(db: AsyncSession, stmt) -> int:
    value = await db.scalar(stmt)
    return int(value or 0)


def _status_value(*, approved: int, pending: int, minimum: int, prerequisites_complete: bool) -> str:
    if not prerequisites_complete and approved < minimum:
        return "blocked"
    if approved >= minimum and pending == 0:
        return "completed"
    if approved >= minimum and pending > 0:
        return "in_review"
    if approved > 0 and approved < minimum:
        return "in_progress"
    if pending > 0:
        return "in_review"
    return "not_started"


def _source_breakdown(metrics: dict[str, Any]) -> dict[str, int]:
    return {
        "manual": int(metrics.get("manual_count", 0)),
        "excel_import": int(metrics.get("excel_import_count", 0)),
        "pdf_extraction": int(metrics.get("pdf_extraction_count", 0)),
        "agent_recommendation": int(metrics.get("agent_recommendation_count", 0)),
        "system_generated": int(metrics.get("system_generated_count", 0)),
    }


def _review_breakdown(metrics: dict[str, Any]) -> dict[str, int]:
    return {
        "approved": int(metrics.get("approved_count", 0)),
        "pending_review": int(metrics.get("pending_review_count", 0)),
        "rejected": int(metrics.get("rejected_count", 0)),
    }


def _score_progress(item: dict[str, Any]) -> int:
    if item.get("status") == "completed":
        return 100
    if item.get("status") == "conditional":
        return 70
    if item.get("status") == "blocked":
        return 20
    if item.get("status") == "in_review":
        return 55
    if item.get("status") == "in_progress":
        return 50
    return 5


def _serialize_uuid(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


def _status_counts(rows: list[tuple[str | None, int]]) -> dict[str, int]:
    return {str(key or "unknown"): int(value or 0) for key, value in rows}


async def _group_counts(db: AsyncSession, stmt) -> dict[str, int]:
    rows = (await db.execute(stmt)).all()
    return _status_counts(rows)


async def _latest_batch(db: AsyncSession, tenant_id: uuid.UUID, *, entity_type: str) -> ImportBatch | None:
    result = await db.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == entity_type)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.started_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _latest_pdf_document(db: AsyncSession, tenant_id: uuid.UUID) -> CalendarSourceDocument | None:
    result = await db.execute(
        select(CalendarSourceDocument)
        .where(CalendarSourceDocument.tenant_id == tenant_id)
        .order_by(CalendarSourceDocument.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


def _batch_payload(batch: ImportBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    meta = batch.metadata_json or {}
    return {
        "id": str(batch.id),
        "tenant_id": str(batch.tenant_id),
        "entity_type": batch.entity_type,
        "original_filename": batch.original_filename,
        "file_sha256": batch.file_sha256,
        "status": batch.status,
        "mode": batch.mode,
        "import_format": batch.import_format,
        "created_by_user_id": str(batch.created_by_user_id),
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "created_rows": batch.created_rows,
        "updated_rows": batch.updated_rows,
        "skipped_rows": batch.skipped_rows,
        "conflict_rows": batch.conflict_rows,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "committed_at": batch.committed_at,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "workbook_summary": meta.get("workbook", {}),
    }


def _document_payload(document: CalendarSourceDocument | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        "id": str(document.id),
        "tenant_id": str(document.tenant_id),
        "import_batch_id": str(document.import_batch_id) if document.import_batch_id else None,
        "original_filename": document.original_filename,
        "file_sha256": document.file_sha256,
        "source_type": document.source_type,
        "extraction_status": document.extraction_status,
        "page_count": document.page_count,
        "extracted_char_count": document.extracted_char_count,
        "extraction_error": document.extraction_error,
        "uploaded_by_user_id": _serialize_uuid(document.uploaded_by_user_id),
        "processed_at": document.processed_at,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def _step_applicable(step_key: str, metrics: dict[str, Any]) -> bool:
    if step_key == "intake_imports":
        return any(
            int(metrics.get(name, 0)) > 0
            for name in ("imports_total", "imports_pending_review", "imports_failed", "pending_candidates")
        )
    return True


def build_steps(metrics: dict[str, Any], readiness: dict[str, Any]) -> list[dict[str, Any]]:
    approved_by_step = {
        "operational_calendar": int(metrics.get("calendar_approved", 0)),
        "school_week": int(metrics.get("school_week_approved", 0)),
        "bell_schedules": int(metrics.get("bell_schedule_approved", 0)),
        "teaching_periods": int(metrics.get("teaching_periods_active", 0)),
        "teaching_rooms": int(metrics.get("rooms_approved", 0)),
        "canonical_classes": int(metrics.get("classes_active", 0)),
        "subjects": int(metrics.get("subjects_total", 0)),
        "teachers": int(metrics.get("teachers_active", 0)),
        "weekly_requirements": int(metrics.get("requirements_approved", 0)),
        "intake_imports": int(metrics.get("imports_total", 0)),
        "approvals_and_readiness": 1 if int(readiness.get("blocker_count", 0)) == 0 else 0,
    }

    pending_by_step = {
        "operational_calendar": int(metrics.get("calendar_pending", 0)),
        "school_week": int(metrics.get("school_week_pending", 0)),
        "bell_schedules": int(metrics.get("bell_schedule_pending", 0)),
        "teaching_periods": 0,
        "teaching_rooms": int(metrics.get("rooms_pending", 0)),
        "canonical_classes": 0,
        "subjects": 0,
        "teachers": 0,
        "weekly_requirements": int(metrics.get("requirements_pending", 0)),
        "intake_imports": int(metrics.get("imports_pending_review", 0)),
        "approvals_and_readiness": int(metrics.get("pending_approvals_total", 0)),
    }

    by_key: dict[str, dict[str, Any]] = {}
    for item in STEP_DEFINITIONS:
        applicable = _step_applicable(item["step_key"], metrics)
        prereqs = item["prerequisites"]
        prereqs_complete = all(by_key[key]["status"] == "completed" for key in prereqs) if prereqs else True
        approved_count = approved_by_step[item["step_key"]]
        pending_count = pending_by_step[item["step_key"]]
        status_value = "not_applicable" if not applicable else _status_value(
            approved=approved_count,
            pending=pending_count,
            minimum=item["required_minimum"],
            prerequisites_complete=prereqs_complete,
        )
        by_key[item["step_key"]] = {
            "step_key": item["step_key"],
            "title": item["title"],
            "status": status_value,
            "weight": item["weight"],
            "applicable": applicable,
            "approved_count": approved_count,
            "pending_count": pending_count,
            "required_minimum": item["required_minimum"],
            "prerequisites": prereqs,
            "route": item["route"],
            "policy_rule": item["policy_rule"],
            "authorized_roles": item["authorized_roles"],
            "source_summary": {} if item["step_key"] not in STEP_SOURCE_MODELS else _source_breakdown(metrics) if item["step_key"] == "operational_calendar" else {},
            "review_summary": {} if item["step_key"] not in STEP_SOURCE_MODELS else _review_breakdown(metrics),
            "lifecycle_summary": metrics.get("lifecycle_counts", {}) if item["step_key"] == "operational_calendar" else {},
        }

    return [by_key[item["step_key"]] for item in STEP_DEFINITIONS]


def build_issues(readiness: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for check in readiness.get("checks", []):
        status_value = str(check.get("status") or "")
        if status_value == "pass":
            continue
        severity = str(check.get("severity") or "information")
        issue_status = "blocking" if severity == "blocker" else ("warning" if severity == "warning" else "information")
        issues.append(
            {
                "issue_key": f"readiness:{check.get('check_key')}",
                "source": "readiness_check",
                "step_key": "approvals_and_readiness",
                "severity": severity,
                "status": issue_status,
                "title": check.get("title"),
                "summary": check.get("explanation"),
                "policy_rule": "Deterministic timetable readiness policy",
                "explanation": check.get("explanation"),
                "affected_count": int(check.get("affected_record_count") or 0),
                "recommended_action": check.get("recommended_action"),
                "setup_route": check.get("setup_route"),
                "authorized_roles": LEADERSHIP_ROLES,
                "requires_human_authorization": False,
                "resolved": False,
                "related_entity": {"type": "readiness_check", "id": check.get("check_key")},
                "created_at": check.get("timestamp"),
                "blocker_relationship": "prevents generation" if severity == "blocker" else "warning only",
                "tenant_safe_references": {},
            }
        )

    pending_approvals = int(metrics.get("pending_approvals_total", 0))
    if pending_approvals > 0:
        issues.append(
            {
                "issue_key": "approvals:pending_human_decisions",
                "source": "approval_queue",
                "step_key": "approvals_and_readiness",
                "severity": "warning",
                "status": "pending_review",
                "title": "Human approvals are pending",
                "summary": "Operational state remains restricted until leadership decisions are recorded.",
                "policy_rule": "Agents may recommend but cannot approve operational records.",
                "explanation": "Operational state remains restricted until leadership decisions are recorded.",
                "affected_count": pending_approvals,
                "recommended_action": "Review approval queue and explicitly approve/reject each pending item.",
                "setup_route": "/leadership/timetable-setup/centre/approvals",
                "authorized_roles": LEADERSHIP_ROLES,
                "requires_human_authorization": True,
                "resolved": False,
                "related_entity": {"type": "approval_queue", "id": "pending_human_decisions"},
                "created_at": _now(),
                "blocker_relationship": "blocks generation until approvals are cleared",
                "tenant_safe_references": {},
            }
        )

    failed_imports = int(metrics.get("imports_failed", 0))
    if failed_imports > 0:
        issues.append(
            {
                "issue_key": "imports:failed_batches",
                "source": "import_batch",
                "step_key": "intake_imports",
                "severity": "warning",
                "status": "warning",
                "title": "Import batches failed validation or processing",
                "summary": "One or more workbook/PDF batches are in failed states.",
                "policy_rule": "Failed imports cannot be committed until deterministic diagnostics are resolved.",
                "explanation": "One or more workbook/PDF batches are in failed states.",
                "affected_count": failed_imports,
                "recommended_action": "Inspect diagnostics, fix issues, and rerun validation before commit.",
                "setup_route": "/leadership/timetable-setup/imports/workbooks",
                "authorized_roles": LEADERSHIP_ROLES,
                "requires_human_authorization": False,
                "resolved": False,
                "related_entity": {"type": "import_batch", "id": "failed_batches"},
                "created_at": _now(),
                "blocker_relationship": "prevents commit for failed batches",
                "tenant_safe_references": {},
            }
        )

    return sorted(issues, key=lambda item: (0 if item["severity"] == "blocker" else 1 if item["severity"] == "warning" else 2, item["issue_key"]))


def build_generation_readiness(readiness: dict[str, Any], metrics: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    blocker_count = int(readiness.get("blocker_count", 0))
    warning_count = int(readiness.get("warning_count", 0))
    information_count = int(readiness.get("information_count", 0))
    pending_approvals = int(metrics.get("pending_approvals_total", 0))

    if blocker_count > 0:
        readiness_status = "blocked"
    elif pending_approvals > 0:
        readiness_status = "awaiting_human_approval"
    elif warning_count > 0:
        readiness_status = "conditionally_ready"
    else:
        readiness_status = "ready"

    generation_allowed = blocker_count == 0 and pending_approvals == 0
    required_actions = [
        {
            "issue_key": item["issue_key"],
            "title": item["title"],
            "recommended_action": item["recommended_action"],
            "setup_route": item["setup_route"],
            "requires_human_authorization": item["requires_human_authorization"],
            "authorized_roles": item["authorized_roles"],
        }
        for item in issues
        if item["severity"] == "blocker" or item["status"] == "pending_review"
    ]

    return {
        "generation_allowed": generation_allowed,
        "readiness_status": readiness_status,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "information_count": information_count,
        "pending_approval_count": pending_approvals,
        "conditional_ready": blocker_count == 0 and pending_approvals == 0 and warning_count > 0,
        "required_actions": required_actions,
    }


def build_progress(steps: list[dict[str, Any]]) -> dict[str, Any]:
    applicable_steps = [item for item in steps if item.get("applicable", True)]
    total_weight = sum(int(item["weight"]) for item in applicable_steps)
    completed_weight = sum(int(item["weight"]) for item in applicable_steps if item["status"] == "completed")
    completed_steps = sum(1 for item in applicable_steps if item["status"] == "completed")
    explanations = [
        f"{item['title']}: {item['status']} ({item['weight']} pts)"
        for item in steps
        if item.get("applicable", True)
    ]
    return {
        "completed_steps": completed_steps,
        "total_steps": len(applicable_steps),
        "completed_weight": completed_weight,
        "total_weight": total_weight,
        "applicable_weight": total_weight,
        "excluded_weight": sum(int(item["weight"]) for item in steps if not item.get("applicable", True)),
        "progress_percentage": 0 if total_weight == 0 else int(round((completed_weight / total_weight) * 100)),
        "explanation": "; ".join(explanations),
    }


def build_recommendations(issues: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    for issue in issues:
        base_score = 100 if issue["severity"] == "blocker" else 70 if issue["severity"] == "warning" else 40
        if issue["status"] == "pending_review":
            base_score += 10
        recommendations.append(
            {
                "recommendation_key": f"recommend:{issue['issue_key']}",
                "priority_score": base_score,
                "title": issue["title"],
                "why": issue["explanation"],
                "recommended_action": issue["recommended_action"],
                "setup_route": issue["setup_route"],
                "authorized_roles": issue["authorized_roles"],
                "requires_human_authorization": issue["requires_human_authorization"],
                "agent_can_execute": False,
            }
        )

    for step in steps:
        if step["status"] == "not_started":
            recommendations.append(
                {
                    "recommendation_key": f"recommend:start:{step['step_key']}",
                    "priority_score": 35,
                    "title": f"Start {step['title']}",
                    "why": "This required setup step has not been started.",
                    "recommended_action": f"Open {step['title']} and add approved records.",
                    "setup_route": step["route"],
                    "authorized_roles": step["authorized_roles"],
                    "requires_human_authorization": False,
                    "agent_can_execute": False,
                }
            )

    unique: dict[str, dict[str, Any]] = {}
    for item in sorted(recommendations, key=lambda row: (-row["priority_score"], row["recommendation_key"])):
        if item["recommendation_key"] not in unique:
            unique[item["recommendation_key"]] = item
    return list(unique.values())[:12]


def _summarize_audit_details(details: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in sorted(details.keys()):
        value = details[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        if len(summary) >= 6:
            break
    return summary


async def collect_centre_metrics(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    calendar_approved = await _count(
        db,
        select(func.count(OperationalCalendarEvent.id)).where(
            OperationalCalendarEvent.tenant_id == tenant_id,
            OperationalCalendarEvent.is_active.is_(True),
            OperationalCalendarEvent.review_status == "approved",
        ),
    )
    calendar_pending = await _count(
        db,
        select(func.count(OperationalCalendarEvent.id)).where(
            OperationalCalendarEvent.tenant_id == tenant_id,
            OperationalCalendarEvent.is_active.is_(True),
            OperationalCalendarEvent.review_status == "pending_review",
        ),
    )
    school_week_approved = await _count(
        db,
        select(func.count(SchoolWeekConfig.id)).where(
            SchoolWeekConfig.tenant_id == tenant_id,
            SchoolWeekConfig.is_active.is_(True),
            SchoolWeekConfig.review_status == "approved",
        ),
    )
    school_week_pending = await _count(
        db,
        select(func.count(SchoolWeekConfig.id)).where(
            SchoolWeekConfig.tenant_id == tenant_id,
            SchoolWeekConfig.is_active.is_(True),
            SchoolWeekConfig.review_status == "pending_review",
        ),
    )
    bell_schedule_approved = await _count(
        db,
        select(func.count(BellSchedule.id)).where(
            BellSchedule.tenant_id == tenant_id,
            BellSchedule.is_active.is_(True),
            BellSchedule.review_status == "approved",
        ),
    )
    bell_schedule_pending = await _count(
        db,
        select(func.count(BellSchedule.id)).where(
            BellSchedule.tenant_id == tenant_id,
            BellSchedule.is_active.is_(True),
            BellSchedule.review_status == "pending_review",
        ),
    )
    teaching_periods_active = await _count(
        db,
        select(func.count(BellSchedulePeriod.id))
        .join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id)
        .where(
            BellSchedulePeriod.tenant_id == tenant_id,
            BellSchedule.tenant_id == tenant_id,
            BellSchedulePeriod.is_active.is_(True),
            BellSchedulePeriod.is_teaching_period.is_(True),
            BellSchedule.is_active.is_(True),
        ),
    )
    rooms_approved = await _count(
        db,
        select(func.count(TeachingRoom.id)).where(
            TeachingRoom.tenant_id == tenant_id,
            TeachingRoom.is_active.is_(True),
            TeachingRoom.review_status == "approved",
        ),
    )
    rooms_pending = await _count(
        db,
        select(func.count(TeachingRoom.id)).where(
            TeachingRoom.tenant_id == tenant_id,
            TeachingRoom.is_active.is_(True),
            TeachingRoom.review_status == "pending_review",
        ),
    )
    classes_active = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    subjects_total = await _count(db, select(func.count(Subject.id)).where(Subject.tenant_id == tenant_id))
    teachers_active = await _count(db, select(func.count(Teacher.id)).where(Teacher.tenant_id == tenant_id, Teacher.is_active.is_(True)))
    requirements_approved = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.review_status == "approved",
        ),
    )
    requirements_pending = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.review_status == "pending_review",
        ),
    )

    imports_total = await _count(db, select(func.count(ImportBatch.id)).where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type.in_(["timetable_workbook", "calendar_pdf"])))
    imports_failed = await _count(db, select(func.count(ImportBatch.id)).where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type.in_(["timetable_workbook", "calendar_pdf"]), ImportBatch.status.in_(["failed", "validation_failed"])))
    imports_pending_review = await _count(
        db,
        select(func.count(ImportBatch.id)).where(
            ImportBatch.tenant_id == tenant_id,
            ImportBatch.entity_type.in_(["timetable_workbook", "calendar_pdf"]),
            ImportBatch.status.in_(["mapping_required", "preview_ready", "validated"]),
        ),
    )

    pending_candidates = await _count(
        db,
        select(func.count(CalendarEventCandidate.id)).where(
            CalendarEventCandidate.tenant_id == tenant_id,
            CalendarEventCandidate.candidate_status.in_(["proposed", "edited"]),
        ),
    )
    pending_plans = await _count(
        db,
        select(func.count(CalendarNotificationPlan.id)).where(
            CalendarNotificationPlan.tenant_id == tenant_id,
            CalendarNotificationPlan.approval_status == "pending_approval",
        ),
    )

    source_rows = (
        await db.execute(
            select(OperationalCalendarEvent.source_type, func.count(OperationalCalendarEvent.id))
            .where(OperationalCalendarEvent.tenant_id == tenant_id, OperationalCalendarEvent.is_active.is_(True))
            .group_by(OperationalCalendarEvent.source_type)
        )
    ).all()
    source_counts = {str(key or "unknown"): int(value or 0) for key, value in source_rows}

    review_rows = (
        await db.execute(
            select(OperationalCalendarEvent.review_status, func.count(OperationalCalendarEvent.id))
            .where(OperationalCalendarEvent.tenant_id == tenant_id, OperationalCalendarEvent.is_active.is_(True))
            .group_by(OperationalCalendarEvent.review_status)
        )
    ).all()
    review_counts = {str(key or "unknown"): int(value or 0) for key, value in review_rows}

    lifecycle_rows = (
        await db.execute(
            select(OperationalCalendarEvent.lifecycle_status, func.count(OperationalCalendarEvent.id))
            .where(OperationalCalendarEvent.tenant_id == tenant_id, OperationalCalendarEvent.is_active.is_(True))
            .group_by(OperationalCalendarEvent.lifecycle_status)
        )
    ).all()
    lifecycle_counts = {str(key or "unknown"): int(value or 0) for key, value in lifecycle_rows}

    calendar_source_counts = await _group_counts(
        db,
        select(OperationalCalendarEvent.source_type, func.count(OperationalCalendarEvent.id))
        .where(OperationalCalendarEvent.tenant_id == tenant_id)
        .group_by(OperationalCalendarEvent.source_type),
    )
    school_week_source_counts = await _group_counts(
        db,
        select(SchoolWeekConfig.source_type, func.count(SchoolWeekConfig.id))
        .where(SchoolWeekConfig.tenant_id == tenant_id)
        .group_by(SchoolWeekConfig.source_type),
    )
    bell_schedule_source_counts = await _group_counts(
        db,
        select(BellSchedule.source_type, func.count(BellSchedule.id))
        .where(BellSchedule.tenant_id == tenant_id)
        .group_by(BellSchedule.source_type),
    )
    room_source_counts = await _group_counts(
        db,
        select(TeachingRoom.source_type, func.count(TeachingRoom.id))
        .where(TeachingRoom.tenant_id == tenant_id)
        .group_by(TeachingRoom.source_type),
    )
    requirement_source_counts = await _group_counts(
        db,
        select(WeeklyTeachingRequirement.source_type, func.count(WeeklyTeachingRequirement.id))
        .where(WeeklyTeachingRequirement.tenant_id == tenant_id)
        .group_by(WeeklyTeachingRequirement.source_type),
    )

    calendar_review_counts = await _group_counts(
        db,
        select(OperationalCalendarEvent.review_status, func.count(OperationalCalendarEvent.id))
        .where(OperationalCalendarEvent.tenant_id == tenant_id)
        .group_by(OperationalCalendarEvent.review_status),
    )
    school_week_review_counts = await _group_counts(
        db,
        select(SchoolWeekConfig.review_status, func.count(SchoolWeekConfig.id))
        .where(SchoolWeekConfig.tenant_id == tenant_id)
        .group_by(SchoolWeekConfig.review_status),
    )
    bell_schedule_review_counts = await _group_counts(
        db,
        select(BellSchedule.review_status, func.count(BellSchedule.id))
        .where(BellSchedule.tenant_id == tenant_id)
        .group_by(BellSchedule.review_status),
    )
    room_review_counts = await _group_counts(
        db,
        select(TeachingRoom.review_status, func.count(TeachingRoom.id))
        .where(TeachingRoom.tenant_id == tenant_id)
        .group_by(TeachingRoom.review_status),
    )
    requirement_review_counts = await _group_counts(
        db,
        select(WeeklyTeachingRequirement.review_status, func.count(WeeklyTeachingRequirement.id))
        .where(WeeklyTeachingRequirement.tenant_id == tenant_id)
        .group_by(WeeklyTeachingRequirement.review_status),
    )

    import_source_rows = (
        await db.execute(
            select(ImportBatch.entity_type, ImportBatch.status, func.count(ImportBatch.id))
            .where(ImportBatch.tenant_id == tenant_id)
            .group_by(ImportBatch.entity_type, ImportBatch.status)
        )
    ).all()
    import_status_counts: dict[str, dict[str, int]] = {"timetable_workbook": {}, "calendar_pdf": {}}
    for entity_type, status_value, count in import_source_rows:
        import_status_counts.setdefault(str(entity_type), {})[str(status_value)] = int(count or 0)

    pdf_status_rows = (
        await db.execute(
            select(CalendarSourceDocument.extraction_status, func.count(CalendarSourceDocument.id))
            .where(CalendarSourceDocument.tenant_id == tenant_id)
            .group_by(CalendarSourceDocument.extraction_status)
        )
    ).all()
    pdf_extraction_counts = {str(key or "unknown"): int(value or 0) for key, value in pdf_status_rows}

    workbook_count = import_status_counts.get("timetable_workbook", {})
    pdf_count = import_status_counts.get("calendar_pdf", {})

    workbook_pending = sum(int(workbook_count.get(status, 0)) for status in ("uploaded", "parsing", "mapping_required", "preview_ready", "validation_failed", "validated"))
    pdf_pending = sum(int(pdf_count.get(status, 0)) for status in ("uploaded", "preflighting", "extracting", "ocr_required", "review_ready"))

    return {
        "calendar_approved": calendar_approved,
        "calendar_pending": calendar_pending,
        "school_week_approved": school_week_approved,
        "school_week_pending": school_week_pending,
        "bell_schedule_approved": bell_schedule_approved,
        "bell_schedule_pending": bell_schedule_pending,
        "teaching_periods_active": teaching_periods_active,
        "rooms_approved": rooms_approved,
        "rooms_pending": rooms_pending,
        "classes_active": classes_active,
        "subjects_total": subjects_total,
        "teachers_active": teachers_active,
        "requirements_approved": requirements_approved,
        "requirements_pending": requirements_pending,
        "imports_total": imports_total,
        "imports_failed": imports_failed,
        "imports_pending_review": imports_pending_review,
        "pending_candidates": pending_candidates,
        "pending_plans": pending_plans,
        "pending_approvals_total": calendar_pending + school_week_pending + bell_schedule_pending + rooms_pending + requirements_pending + pending_candidates + pending_plans,
        "lifecycle_counts": lifecycle_counts,
        "calendar_source_counts": calendar_source_counts,
        "school_week_source_counts": school_week_source_counts,
        "bell_schedule_source_counts": bell_schedule_source_counts,
        "room_source_counts": room_source_counts,
        "requirement_source_counts": requirement_source_counts,
        "calendar_review_counts": calendar_review_counts,
        "school_week_review_counts": school_week_review_counts,
        "bell_schedule_review_counts": bell_schedule_review_counts,
        "room_review_counts": room_review_counts,
        "requirement_review_counts": requirement_review_counts,
        "manual_count": source_counts.get("manual", 0),
        "excel_import_count": source_counts.get("excel_import", 0),
        "pdf_extraction_count": source_counts.get("pdf_extraction", 0),
        "agent_recommendation_count": source_counts.get("agent_recommendation", 0),
        "system_generated_count": source_counts.get("system_generated", 0),
        "approved_count": review_counts.get("approved", 0),
        "pending_review_count": review_counts.get("pending_review", 0),
        "rejected_count": review_counts.get("rejected", 0),
        "workbook_status_counts": workbook_count,
        "workbook_pending_count": workbook_pending,
        "pdf_status_counts": pdf_count,
        "pdf_extraction_counts": pdf_extraction_counts,
        "pdf_pending_count": pdf_pending,
    }


def _diagnostic_counts(batch: ImportBatch | None) -> dict[str, int]:
    if batch is None:
        return {"blocker_count": 0, "warning_count": 0, "information_count": 0}
    diagnostics = (batch.metadata_json or {}).get("diagnostics", {})
    return {
        "blocker_count": int(diagnostics.get("blocker_count", 0)),
        "warning_count": int(diagnostics.get("warning_count", 0)),
        "information_count": int(diagnostics.get("information_count", 0)),
    }


async def collect_import_summaries(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    workbook_batches = (
        await db.execute(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "timetable_workbook")
            .order_by(ImportBatch.created_at.desc(), ImportBatch.started_at.desc())
        )
    ).scalars().all()
    pdf_batches = (
        await db.execute(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "calendar_pdf")
            .order_by(ImportBatch.created_at.desc(), ImportBatch.started_at.desc())
        )
    ).scalars().all()

    latest_workbook = workbook_batches[0] if workbook_batches else None
    latest_pdf_batch = pdf_batches[0] if pdf_batches else None
    latest_pdf_document = await _latest_pdf_document(db, tenant_id)

    workbook_status_rows = (
        await db.execute(
            select(ImportBatch.status, func.count(ImportBatch.id))
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "timetable_workbook")
            .group_by(ImportBatch.status)
        )
    ).all()
    pdf_batch_status_rows = (
        await db.execute(
            select(ImportBatch.status, func.count(ImportBatch.id))
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "calendar_pdf")
            .group_by(ImportBatch.status)
        )
    ).all()

    pdf_doc_status_rows = (
        await db.execute(
            select(CalendarSourceDocument.extraction_status, func.count(CalendarSourceDocument.id))
            .where(CalendarSourceDocument.tenant_id == tenant_id)
            .group_by(CalendarSourceDocument.extraction_status)
        )
    ).all()

    latest_workbook_row_counts = {"blocker_count": 0, "warning_count": 0, "information_count": 0}
    if latest_workbook is not None:
        result = await db.execute(
            select(ImportRowResult.severity, func.count(ImportRowResult.id))
            .where(ImportRowResult.tenant_id == tenant_id, ImportRowResult.import_batch_id == latest_workbook.id, ImportRowResult.severity.is_not(None))
            .group_by(ImportRowResult.severity)
        )
        row_counts = _status_counts(result.all())
        latest_workbook_row_counts = {
            "blocker_count": int(row_counts.get("blocker", 0)),
            "warning_count": int(row_counts.get("warning", 0)),
            "information_count": int(row_counts.get("information", 0)),
        }

    latest_workbook_summary = _batch_payload(latest_workbook)
    latest_pdf_summary = _batch_payload(latest_pdf_batch)

    if latest_pdf_document is not None:
        related_candidates = (
            await db.execute(
                select(CalendarEventCandidate)
                .where(CalendarEventCandidate.tenant_id == tenant_id, CalendarEventCandidate.source_document_id == latest_pdf_document.id)
                .order_by(CalendarEventCandidate.created_at.desc())
            )
        ).scalars().all()
        candidate_counts = {
            "pending_review": sum(1 for item in related_candidates if item.candidate_status in {"proposed", "edited"}),
            "approved": sum(1 for item in related_candidates if item.candidate_status == "approved"),
            "rejected": sum(1 for item in related_candidates if item.candidate_status == "rejected"),
            "committed": sum(1 for item in related_candidates if item.candidate_status == "committed"),
        }
    else:
        candidate_counts = {"pending_review": 0, "approved": 0, "rejected": 0, "committed": 0}

    workbook_summary = {
        "direct_route": "/leadership/timetable-setup/imports/workbooks",
        "latest_import": latest_workbook_summary,
        "status_counts": _status_counts(workbook_status_rows),
        "pending_count": sum(int(v) for key, v in _status_counts(workbook_status_rows).items() if key not in {"committed", "failed", "cancelled"}),
        "unresolved_mapping_count": int((latest_workbook_summary or {}).get("workbook_summary", {}).get("sheets", []) and sum(len(sheet.get("required_unmapped_fields", [])) for sheet in (latest_workbook_summary or {}).get("workbook_summary", {}).get("sheets", [])) or 0),
        "blocker_count": latest_workbook_row_counts["blocker_count"],
        "review_count": latest_workbook_row_counts["warning_count"] + latest_workbook_row_counts["information_count"],
        "committed_count": int(_status_counts(workbook_status_rows).get("committed", 0)),
        "failed_count": int(_status_counts(workbook_status_rows).get("failed", 0)) + int(_status_counts(workbook_status_rows).get("validation_failed", 0)),
        "latest_status": (latest_workbook_summary or {}).get("status"),
    }

    pdf_status_counts = _status_counts(pdf_doc_status_rows)
    pdf_total_docs = sum(pdf_status_counts.values())
    latest_pdf_doc_status = (latest_pdf_document.extraction_status if latest_pdf_document else None)
    pdf_summary = {
        "direct_route": "/leadership/timetable-setup/calendar/pdf-intake/imports",
        "latest_import": _document_payload(latest_pdf_document),
        "status_counts": pdf_status_counts,
        "pending_count": sum(int(pdf_status_counts.get(key, 0)) for key in ("uploaded", "processing", "ocr_required", "review_ready")),
        "unresolved_mapping_count": 0,
        "blocker_count": int(pdf_status_counts.get("failed", 0)),
        "review_count": candidate_counts["pending_review"],
        "committed_count": int(pdf_status_counts.get("committed", 0)),
        "failed_count": int(pdf_status_counts.get("failed", 0)),
        "pdf_state_counts": {
            "uploaded": int(pdf_status_counts.get("uploaded", 0)),
            "preflighting": int(pdf_status_counts.get("processing", 0)),
            "extracting": int(pdf_status_counts.get("processing", 0)),
            "extraction_failed": int(pdf_status_counts.get("failed", 0)),
            "ocr_required": int(pdf_status_counts.get("ocr_required", 0)),
            "review_ready": int(pdf_status_counts.get("review_ready", 0)),
            "partially_reviewed": candidate_counts["pending_review"] if candidate_counts["approved"] or candidate_counts["rejected"] else 0,
            "ready_to_commit": int(pdf_status_counts.get("review_ready", 0)) if candidate_counts["pending_review"] == 0 and latest_pdf_doc_status in {"review_ready", "processed"} else 0,
            "committed": int(pdf_status_counts.get("committed", 0)),
            "cancelled": int(pdf_status_counts.get("cancelled", 0)),
        },
        "candidate_review_counts": candidate_counts,
    }

    return {
        "workbook": workbook_summary,
        "pdf": pdf_summary,
        "total_pending": workbook_summary["pending_count"] + pdf_summary["pending_count"],
        "total_failed": workbook_summary["failed_count"] + pdf_summary["failed_count"],
        "total_committed": workbook_summary["committed_count"] + pdf_summary["committed_count"],
        "latest_imports": {
            "workbook": latest_workbook_summary,
            "pdf": _document_payload(latest_pdf_document),
        },
    }


async def get_recent_activity(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    action_type: str | None = None,
    entity_type: str | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
) -> dict[str, Any]:
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.action.like("timetable_setup.%"))
    if action_type:
        stmt = stmt.where(AuditLog.action.like(f"timetable_setup.{action_type}.%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if start_date is not None:
        stmt = stmt.where(func.date(AuditLog.created_at) >= start_date)
    if end_date is not None:
        stmt = stmt.where(func.date(AuditLog.created_at) <= end_date)

    rows = (
        await db.execute(stmt.order_by(AuditLog.created_at.desc()).offset(max(0, (page - 1) * page_size)).limit(page_size))
    ).scalars().all()
    total_stmt = select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id, AuditLog.action.like("timetable_setup.%"))
    if action_type:
        total_stmt = total_stmt.where(AuditLog.action.like(f"timetable_setup.{action_type}.%"))
    if entity_type:
        total_stmt = total_stmt.where(AuditLog.entity_type == entity_type)
    if start_date is not None:
        total_stmt = total_stmt.where(func.date(AuditLog.created_at) >= start_date)
    if end_date is not None:
        total_stmt = total_stmt.where(func.date(AuditLog.created_at) <= end_date)
    total = await _count(db, total_stmt)
    items = [
        {
            "id": str(item.id),
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": str(item.entity_id) if item.entity_id else None,
            "actor_id": str(item.actor_id) if item.actor_id else None,
            "created_at": item.created_at,
            "detail_summary": _summarize_audit_details(item.details or {}),
        }
        for item in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "direct_route": "/leadership/timetable-setup/centre/activity"}


def _queue_route_for_source(source: str) -> str:
    return {
        "calendar_event": "/leadership/timetable-setup/calendar",
        "calendar_candidate": "/leadership/timetable-setup/calendar/pdf-intake/imports",
        "workbook_import": "/leadership/timetable-setup/imports/workbooks",
        "pdf_import": "/leadership/timetable-setup/calendar/pdf-intake/imports",
        "notification_plan": "/leadership/timetable-setup/calendar/notification-plans",
        "approval_queue": "/leadership/timetable-setup/centre/approvals",
    }.get(source, "/leadership/timetable-setup/centre/approvals")


def _queue_item_base(
    *,
    item_type: str,
    title: str,
    summary: str,
    urgency: str,
    setup_step: str,
    source: str,
    created_at: datetime,
    required_approver_roles: list[str],
    recommended_action: str,
    route: str,
    blocker_relationship: str,
    related_entity: dict[str, Any],
    tenant_safe_references: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": item_type,
        "title": title,
        "summary": summary,
        "urgency": urgency,
        "setup_step": setup_step,
        "related_entity": related_entity,
        "source": source,
        "created_at": created_at,
        "required_approver_roles": required_approver_roles,
        "recommended_action": recommended_action,
        "route": route,
        "blocker_relationship": blocker_relationship,
        "tenant_safe_references": tenant_safe_references,
        "requires_human_authorization": True,
    }


async def collect_approval_queue(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    calendar_rows = (
        await db.execute(
            select(OperationalCalendarEvent)
            .where(OperationalCalendarEvent.tenant_id == tenant_id, OperationalCalendarEvent.is_active.is_(True), OperationalCalendarEvent.review_status == "pending_review")
            .order_by(OperationalCalendarEvent.created_at.desc())
        )
    ).scalars().all()
    for event in calendar_rows:
        high_impact = event.event_type in {"examination_period", "public_holiday", "teaching_day_override", "special_schedule"} or (event.impact_scope_json or {}).get("scope_type") == "whole_school"
        items.append(
            _queue_item_base(
                item_type="calendar_event_pending_approval",
                title=event.event_name,
                summary=event.description or f"Pending {event.event_type} change",
                urgency="high" if high_impact else "normal",
                setup_step="operational_calendar",
                source="calendar_event",
                created_at=event.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Approve or reject the calendar change explicitly.",
                route="/leadership/timetable-setup/calendar",
                blocker_relationship="blocks generation when the event is a required calendar input",
                related_entity={"type": "OperationalCalendarEvent", "id": str(event.id)},
                tenant_safe_references={"tenant_id": str(event.tenant_id), "event_id": str(event.id)},
            )
        )

    candidate_rows = (
        await db.execute(
            select(CalendarEventCandidate)
            .where(CalendarEventCandidate.tenant_id == tenant_id, CalendarEventCandidate.candidate_status.in_(["proposed", "edited"]))
            .order_by(CalendarEventCandidate.created_at.desc())
        )
    ).scalars().all()
    for candidate in candidate_rows:
        items.append(
            _queue_item_base(
                item_type="calendar_candidate_pending_review",
                title=candidate.proposed_event_name,
                summary=candidate.uncertainty_note or candidate.proposed_description or "Calendar candidate pending review",
                urgency="normal",
                setup_step="operational_calendar",
                source="calendar_candidate",
                created_at=candidate.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Review and approve or reject the candidate explicitly.",
                route="/leadership/timetable-setup/calendar/pdf-intake/imports",
                blocker_relationship="blocks commit of extracted calendar intake",
                related_entity={"type": "CalendarEventCandidate", "id": str(candidate.id)},
                tenant_safe_references={"tenant_id": str(candidate.tenant_id), "candidate_id": str(candidate.id)},
            )
        )

    workbook_batches = (
        await db.execute(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "timetable_workbook", ImportBatch.status == "mapping_required")
            .order_by(ImportBatch.created_at.desc())
        )
    ).scalars().all()
    for batch in workbook_batches:
        items.append(
            _queue_item_base(
                item_type="workbook_mappings_requiring_confirmation",
                title=batch.original_filename or "Workbook import",
                summary="Workbook mappings need leadership confirmation.",
                urgency="high",
                setup_step="intake_imports",
                source="workbook_import",
                created_at=batch.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Confirm the column mappings before validation or commit.",
                route="/leadership/timetable-setup/imports/workbooks",
                blocker_relationship="blocks validation and commit until mappings are confirmed",
                related_entity={"type": "ImportBatch", "id": str(batch.id)},
                tenant_safe_references={"tenant_id": str(batch.tenant_id), "batch_id": str(batch.id)},
            )
        )

    validated_batches = (
        await db.execute(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.entity_type == "timetable_workbook", ImportBatch.status == "validated")
            .order_by(ImportBatch.created_at.desc())
        )
    ).scalars().all()
    for batch in validated_batches:
        items.append(
            _queue_item_base(
                item_type="validated_workbook_awaiting_commit",
                title=batch.original_filename or "Validated workbook",
                summary="Validated workbook import awaiting authorized execution.",
                urgency="normal",
                setup_step="intake_imports",
                source="workbook_import",
                created_at=batch.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Authorize the controlled workbook commit.",
                route="/leadership/timetable-setup/imports/workbooks",
                blocker_relationship="no longer blocked by validation but still needs human commit authorization",
                related_entity={"type": "ImportBatch", "id": str(batch.id)},
                tenant_safe_references={"tenant_id": str(batch.tenant_id), "batch_id": str(batch.id)},
            )
        )

    pdf_documents = (
        await db.execute(
            select(CalendarSourceDocument)
            .where(CalendarSourceDocument.tenant_id == tenant_id, CalendarSourceDocument.extraction_status.in_(["review_ready", "processed"]))
            .order_by(CalendarSourceDocument.created_at.desc())
        )
    ).scalars().all()
    for document in pdf_documents:
        items.append(
            _queue_item_base(
                item_type="pdf_import_ready_for_controlled_commit",
                title=document.original_filename or "Calendar PDF import",
                summary="PDF import ready for controlled commit.",
                urgency="normal",
                setup_step="intake_imports",
                source="pdf_import",
                created_at=document.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Review extracted candidates and commit only after explicit approval.",
                route="/leadership/timetable-setup/calendar/pdf-intake/imports",
                blocker_relationship="blocks operational calendar changes until leadership review completes",
                related_entity={"type": "CalendarSourceDocument", "id": str(document.id)},
                tenant_safe_references={"tenant_id": str(document.tenant_id), "document_id": str(document.id)},
            )
        )

    plans = (
        await db.execute(
            select(CalendarNotificationPlan)
            .where(CalendarNotificationPlan.tenant_id == tenant_id, CalendarNotificationPlan.approval_status == "pending_approval")
            .order_by(CalendarNotificationPlan.created_at.desc())
        )
    ).scalars().all()
    for plan in plans:
        items.append(
            _queue_item_base(
                item_type="notification_plan_pending_approval",
                title=plan.subject,
                summary=plan.proposed_message[:160],
                urgency=plan.urgency,
                setup_step="approvals_and_readiness",
                source="notification_plan",
                created_at=plan.created_at,
                required_approver_roles=LEADERSHIP_ROLES,
                recommended_action="Approve or cancel the notification plan.",
                route="/leadership/timetable-setup/calendar/notification-plans",
                blocker_relationship="blocks delivery of the associated high-impact communication",
                related_entity={"type": "CalendarNotificationPlan", "id": str(plan.id)},
                tenant_safe_references={"tenant_id": str(plan.tenant_id), "plan_id": str(plan.id)},
            )
        )

    items = [item for item in items if item["type"] not in {"validated_workbook_awaiting_commit"} or item["related_entity"]]
    items.sort(key=lambda item: (0 if item["urgency"] == "critical" else 1 if item["urgency"] == "high" else 2, item["created_at"], item["title"]))
    return {"items": items, "pending_total": len(items), "direct_route": "/leadership/timetable-setup/centre/approvals"}


async def build_setup_centre_payload(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    readiness = await compute_timetable_input_readiness(db, tenant_id)
    metrics = await collect_centre_metrics(db, tenant_id)
    import_summaries = await collect_import_summaries(db, tenant_id)
    approval_queue = await collect_approval_queue(db, tenant_id)
    steps = build_steps(metrics, readiness)
    issues = build_issues(readiness, metrics)
    generation = build_generation_readiness(readiness, metrics, issues)
    progress = build_progress(steps)
    recommendations = build_recommendations(issues, steps)
    provenance = {
        "source_breakdown": _source_breakdown(metrics),
        "review_breakdown": _review_breakdown(metrics),
        "lifecycle_counts": metrics.get("lifecycle_counts", {}),
        "manual_count": metrics.get("manual_count", 0),
        "excel_import_count": metrics.get("excel_import_count", 0),
        "pdf_extraction_count": metrics.get("pdf_extraction_count", 0),
        "agent_recommendation_count": metrics.get("agent_recommendation_count", 0),
        "system_generated_count": metrics.get("system_generated_count", 0),
        "inactive_count": int(metrics.get("lifecycle_counts", {}).get("archived", 0)) + int(metrics.get("lifecycle_counts", {}).get("cancelled", 0)),
    }

    return {
        "generated_at": _now(),
        "metrics": metrics,
        "steps": steps,
        "issues": issues,
        "generation": generation,
        "progress": progress,
        "recommendations": recommendations,
        "provenance": provenance,
        "source_breakdown": provenance["source_breakdown"],
        "review_breakdown": provenance["review_breakdown"],
        "import_summaries": import_summaries,
        "approval_queue": approval_queue,
        "policy": {
            "authorized_roles": LEADERSHIP_ROLES,
            "agent_allowed_actions": AGENT_ALLOWED_ACTIONS,
            "agent_prohibited_actions": AGENT_PROHIBITED_ACTIONS,
            "human_approval_required_for": [
                "import_mapping_confirmation",
                "calendar_candidate_approval",
                "event_publication",
                "import_commit",
                "readiness_override",
            ],
        },
        "progress_explanation": progress.get("explanation"),
    }


async def get_approvals_queue(metrics: dict[str, Any]) -> dict[str, Any]:
    items = [
        {
            "approval_key": "calendar_entries_pending_review",
            "title": "Calendar entries pending review",
            "pending_count": int(metrics.get("calendar_pending", 0)),
            "policy_rule": "Only leadership can approve or reject pending operational events.",
            "authorized_roles": LEADERSHIP_ROLES,
            "next_action": "Review and decide each pending calendar entry.",
            "setup_route": "/leadership/timetable-setup/calendar",
            "blocks_generation": int(metrics.get("calendar_pending", 0)) > 0,
            "requires_human_authorization": True,
        },
        {
            "approval_key": "calendar_candidates_pending_decision",
            "title": "PDF calendar candidates pending decision",
            "pending_count": int(metrics.get("pending_candidates", 0)),
            "policy_rule": "Candidates remain non-operational until approved by leadership.",
            "authorized_roles": LEADERSHIP_ROLES,
            "next_action": "Approve or reject each candidate before commit.",
            "setup_route": "/leadership/timetable-setup/calendar/pdf-intake/imports",
            "blocks_generation": False,
            "requires_human_authorization": True,
        },
        {
            "approval_key": "notification_plans_pending_approval",
            "title": "Notification plans awaiting approval",
            "pending_count": int(metrics.get("pending_plans", 0)),
            "policy_rule": "High-impact notifications require explicit approval.",
            "authorized_roles": LEADERSHIP_ROLES,
            "next_action": "Approve or cancel pending notification plans.",
            "setup_route": "/leadership/timetable-setup/calendar/notification-plans",
            "blocks_generation": False,
            "requires_human_authorization": True,
        },
    ]
    items = [item for item in items if item["pending_count"] > 0]
    return {"pending_total": sum(item["pending_count"] for item in items), "items": items}
