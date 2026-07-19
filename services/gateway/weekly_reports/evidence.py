from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shared.db.models import Class, Student, Tenant, User
from services.gateway.weekly_reports.schemas import StaffEvidenceInput


@dataclass(frozen=True)
class ReportingPeriod:
    week_start: date
    week_end: date
    timezone_used: str


def normalize_week_start(value: date) -> date:
    # Use Monday as the deterministic reporting week start.
    return value - timedelta(days=value.weekday())


def resolve_reporting_period(*, requested_week_start: date, tenant: Tenant, timezone_override: str | None) -> ReportingPeriod:
    week_start = normalize_week_start(requested_week_start)
    week_end = week_start + timedelta(days=6)

    timezone_candidate = (timezone_override or "").strip()
    if not timezone_candidate:
        settings = tenant.settings or {}
        timezone_candidate = str(settings.get("timezone") or settings.get("school_timezone") or "").strip()

    if timezone_candidate:
        try:
            ZoneInfo(timezone_candidate)
            timezone_used = timezone_candidate
        except ZoneInfoNotFoundError:
            timezone_used = "UTC"
    else:
        timezone_used = "UTC"

    return ReportingPeriod(week_start=week_start, week_end=week_end, timezone_used=timezone_used)


def build_evidence_snapshot(
    *,
    student: Student,
    klass: Class,
    period: ReportingPeriod,
    actor: User,
    staff_evidence: StaffEvidenceInput | None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    staff_notes = {
        "weekly_teacher_summary": staff_evidence.weekly_teacher_summary if staff_evidence else None,
        "strengths_observed": staff_evidence.strengths_observed if staff_evidence else None,
        "achievements": staff_evidence.achievements if staff_evidence else None,
        "areas_needing_support": staff_evidence.areas_needing_support if staff_evidence else None,
        "suggested_parent_support": staff_evidence.suggested_parent_support if staff_evidence else None,
        "additional_factual_note": staff_evidence.additional_factual_note if staff_evidence else None,
    }

    return {
        "reporting_context": {
            "student_id": str(student.id),
            "student_display_name": student.name,
            "class_name": f"{klass.grade}-{klass.section}",
            "academic_year": klass.academic_year,
            "week_start": period.week_start.isoformat(),
            "week_end": period.week_end.isoformat(),
            "timezone_used": period.timezone_used,
        },
        "evidence_items": [
            {
                "evidence_id": "student_profile_1",
                "source_type": "student_profile",
                "available": True,
                "facts": {
                    "student_display_name": student.name,
                    "class_name": f"{klass.grade}-{klass.section}",
                    "academic_year": klass.academic_year,
                },
                "collected_at": now,
            },
            {
                "evidence_id": "attendance_1",
                "source_type": "attendance",
                "available": False,
                "unavailable_reason": "Attendance information was not available for this reporting week.",
                "facts": {},
                "collected_at": now,
            },
            {
                "evidence_id": "homework_1",
                "source_type": "homework",
                "available": False,
                "unavailable_reason": "Homework information is not currently connected to this student profile.",
                "facts": {},
                "collected_at": now,
            },
            {
                "evidence_id": "behaviour_1",
                "source_type": "behaviour",
                "available": False,
                "unavailable_reason": "Behaviour information was not available for this reporting week.",
                "facts": {},
                "collected_at": now,
            },
            {
                "evidence_id": "academic_1",
                "source_type": "academic",
                "available": False,
                "unavailable_reason": "No academic results were available for this period.",
                "facts": {},
                "collected_at": now,
            },
            {
                "evidence_id": "staff_input_1",
                "source_type": "staff_input",
                "available": True,
                "facts": {
                    "entered_by_user_id": str(actor.id),
                    "entered_at": now,
                    "notes": staff_notes,
                },
                "collected_at": now,
            },
        ],
    }
