from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    BellSchedule,
    BellSchedulePeriod,
    Class,
    OperationalCalendarEvent,
    SchoolWeekConfig,
    Subject,
    Teacher,
    TeachingRoom,
    User,
    WeeklyTeachingRequirement,
)

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFORMATION = "information"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_ATTENTION = "attention"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check(
    *,
    key: str,
    title: str,
    severity: str,
    status: str,
    explanation: str,
    affected_count: int,
    entity_refs: list[dict[str, Any]],
    recommended_action: str,
    route: str,
) -> dict[str, Any]:
    return {
        "check_key": key,
        "title": title,
        "severity": severity,
        "status": status,
        "explanation": explanation,
        "affected_record_count": affected_count,
        "entity_references": entity_refs,
        "recommended_action": recommended_action,
        "setup_route": route,
        "timestamp": _now(),
    }


async def _count(db: AsyncSession, stmt) -> int:
    value = await db.scalar(stmt)
    return int(value or 0)


async def compute_timetable_input_readiness(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    approved_calendar_events = await _count(
        db,
        select(func.count(OperationalCalendarEvent.id)).where(
            OperationalCalendarEvent.tenant_id == tenant_id,
            OperationalCalendarEvent.is_active.is_(True),
            OperationalCalendarEvent.review_status == "approved",
        ),
    )
    checks.append(
        _check(
            key="calendar_approved_entries",
            title="Approved operational calendar exists",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if approved_calendar_events > 0 else STATUS_FAIL,
            explanation="At least one approved operational calendar event must exist before timetable generation inputs are trusted.",
            affected_count=approved_calendar_events,
            entity_refs=[],
            recommended_action="Create and approve operational calendar records.",
            route="/leadership/timetable-setup/calendar",
        )
    )

    pending_calendar_events = await _count(
        db,
        select(func.count(OperationalCalendarEvent.id)).where(
            OperationalCalendarEvent.tenant_id == tenant_id,
            OperationalCalendarEvent.is_active.is_(True),
            OperationalCalendarEvent.review_status == "pending_review",
        ),
    )
    checks.append(
        _check(
            key="calendar_pending_review",
            title="Calendar entries pending review",
            severity=SEVERITY_WARNING,
            status=STATUS_ATTENTION if pending_calendar_events > 0 else STATUS_PASS,
            explanation="Pending extracted calendar entries are non-operational until a leadership approval action is recorded.",
            affected_count=pending_calendar_events,
            entity_refs=[],
            recommended_action="Review and approve/reject pending calendar entries.",
            route="/leadership/timetable-setup/calendar",
        )
    )

    active_week_configs = await _count(
        db,
        select(func.count(SchoolWeekConfig.id)).where(
            SchoolWeekConfig.tenant_id == tenant_id,
            SchoolWeekConfig.is_active.is_(True),
            SchoolWeekConfig.review_status == "approved",
        ),
    )
    checks.append(
        _check(
            key="school_week_config",
            title="Operational weekdays configured",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if active_week_configs > 0 else STATUS_FAIL,
            explanation="A tenant must define approved operational weekdays before timetable setup can proceed.",
            affected_count=active_week_configs,
            entity_refs=[],
            recommended_action="Create an approved school week configuration.",
            route="/leadership/timetable-setup/bell-schedules",
        )
    )

    active_bell_schedules = await _count(
        db,
        select(func.count(BellSchedule.id)).where(
            BellSchedule.tenant_id == tenant_id,
            BellSchedule.is_active.is_(True),
            BellSchedule.review_status == "approved",
        ),
    )
    checks.append(
        _check(
            key="bell_schedule_active",
            title="Active bell schedule exists",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if active_bell_schedules > 0 else STATUS_FAIL,
            explanation="At least one approved active bell schedule is required.",
            affected_count=active_bell_schedules,
            entity_refs=[],
            recommended_action="Create and activate an approved bell schedule.",
            route="/leadership/timetable-setup/bell-schedules",
        )
    )

    active_teaching_periods = await _count(
        db,
        select(func.count(BellSchedulePeriod.id))
        .join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id)
        .where(
            BellSchedulePeriod.tenant_id == tenant_id,
            BellSchedule.tenant_id == tenant_id,
            BellSchedule.is_active.is_(True),
            BellSchedule.review_status == "approved",
            BellSchedulePeriod.is_active.is_(True),
            BellSchedulePeriod.is_teaching_period.is_(True),
        ),
    )
    checks.append(
        _check(
            key="teaching_periods_available",
            title="Active teaching periods available",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if active_teaching_periods > 0 else STATUS_FAIL,
            explanation="Break/lunch periods remain visible but at least one teaching period is required.",
            affected_count=active_teaching_periods,
            entity_refs=[],
            recommended_action="Add active teaching periods to an approved bell schedule.",
            route="/leadership/timetable-setup/bell-schedules",
        )
    )

    overlap_rows = (
        await db.execute(
            select(BellSchedulePeriod.id)
            .join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id)
            .where(
                BellSchedulePeriod.tenant_id == tenant_id,
                BellSchedule.tenant_id == tenant_id,
                BellSchedulePeriod.is_active.is_(True),
                BellSchedule.is_active.is_(True),
            )
        )
    ).scalars().all()
    overlap_count = 0
    if overlap_rows:
        # Deterministic lightweight overlap guard for tests and setup checks.
        periods = (
            await db.execute(
                select(
                    BellSchedulePeriod.bell_schedule_id,
                    BellSchedulePeriod.start_time,
                    BellSchedulePeriod.end_time,
                )
                .join(BellSchedule, BellSchedule.id == BellSchedulePeriod.bell_schedule_id)
                .where(
                    BellSchedulePeriod.tenant_id == tenant_id,
                    BellSchedule.tenant_id == tenant_id,
                    BellSchedulePeriod.is_active.is_(True),
                    BellSchedule.is_active.is_(True),
                )
                .order_by(BellSchedulePeriod.bell_schedule_id, BellSchedulePeriod.start_time)
            )
        ).all()
        by_schedule: dict[uuid.UUID, list[tuple[str, str]]] = {}
        for schedule_id, start_time, end_time in periods:
            by_schedule.setdefault(schedule_id, []).append((start_time, end_time))
        for schedule_periods in by_schedule.values():
            for i in range(1, len(schedule_periods)):
                prev_end = schedule_periods[i - 1][1]
                curr_start = schedule_periods[i][0]
                if curr_start < prev_end:
                    overlap_count += 1

    checks.append(
        _check(
            key="bell_schedule_period_overlap",
            title="No overlapping active periods",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if overlap_count > 0 else STATUS_PASS,
            explanation="Active periods in the same bell schedule must not overlap.",
            affected_count=overlap_count,
            entity_refs=[],
            recommended_action="Adjust period ranges so each active period is non-overlapping.",
            route="/leadership/timetable-setup/bell-schedules",
        )
    )

    active_classes = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            Class.grade_level_id.is_not(None),
        ),
    )
    checks.append(
        _check(
            key="canonical_classes_present",
            title="Canonical classes exist",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if active_classes > 0 else STATUS_FAIL,
            explanation="At least one active canonical class is required.",
            affected_count=active_classes,
            entity_refs=[],
            recommended_action="Create canonical classes in Academic Structure.",
            route="/leadership/academic-structure/classes",
        )
    )

    subjects_count = await _count(
        db,
        select(func.count(Subject.id)).where(Subject.tenant_id == tenant_id),
    )
    checks.append(
        _check(
            key="subjects_present",
            title="Subjects exist",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if subjects_count > 0 else STATUS_FAIL,
            explanation="At least one subject must exist before teaching requirements can be complete.",
            affected_count=subjects_count,
            entity_refs=[],
            recommended_action="Create subject records.",
            route="/leadership/academic-structure/subject-offerings",
        )
    )

    active_requirements = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.review_status == "approved",
        ),
    )
    checks.append(
        _check(
            key="weekly_requirements_present",
            title="Active weekly teaching requirements exist",
            severity=SEVERITY_BLOCKER,
            status=STATUS_PASS if active_requirements > 0 else STATUS_FAIL,
            explanation="Each class-subject scope needs approved active weekly requirements.",
            affected_count=active_requirements,
            entity_refs=[],
            recommended_action="Create approved weekly teaching requirements.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    classes_without_requirements = await _count(
        db,
        select(func.count(Class.id)).where(
            Class.tenant_id == tenant_id,
            Class.is_active.is_(True),
            Class.campus_id.is_not(None),
            Class.academic_year_id.is_not(None),
            ~Class.id.in_(
                select(WeeklyTeachingRequirement.class_id).where(
                    WeeklyTeachingRequirement.tenant_id == tenant_id,
                    WeeklyTeachingRequirement.is_active.is_(True),
                    WeeklyTeachingRequirement.review_status == "approved",
                )
            ),
        ),
    )
    checks.append(
        _check(
            key="classes_missing_requirements",
            title="No class is missing active weekly requirements",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if classes_without_requirements > 0 else STATUS_PASS,
            explanation="All active canonical classes should have at least one approved requirement.",
            affected_count=classes_without_requirements,
            entity_refs=[],
            recommended_action="Add requirements for uncovered classes.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    invalid_session_requirements = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.sessions_per_week <= 0,
        ),
    )
    checks.append(
        _check(
            key="requirement_session_count_valid",
            title="Session counts are valid",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if invalid_session_requirements > 0 else STATUS_PASS,
            explanation="Sessions per week must be positive.",
            affected_count=invalid_session_requirements,
            entity_refs=[],
            recommended_action="Correct non-positive session counts.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    inactive_teacher_assignments = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id))
        .join(Teacher, Teacher.id == WeeklyTeachingRequirement.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.teacher_id.is_not(None),
            User.is_active.is_(False),
        ),
    )
    checks.append(
        _check(
            key="inactive_assigned_teachers",
            title="Assigned teachers are active",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if inactive_teacher_assignments > 0 else STATUS_PASS,
            explanation="Inactive teacher users cannot satisfy active weekly requirements.",
            affected_count=inactive_teacher_assignments,
            entity_refs=[],
            recommended_action="Reassign or reactivate affected teacher users.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    required_specialist_without_room = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.specialist_room_type.is_not(None),
            ~WeeklyTeachingRequirement.specialist_room_type.in_(
                select(TeachingRoom.room_type).where(
                    TeachingRoom.tenant_id == tenant_id,
                    TeachingRoom.is_active.is_(True),
                )
            ),
        ),
    )
    checks.append(
        _check(
            key="specialist_room_coverage",
            title="Required specialist room types are available",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if required_specialist_without_room > 0 else STATUS_PASS,
            explanation="Requirements that request specialist rooms must match at least one active room type.",
            affected_count=required_specialist_without_room,
            entity_refs=[],
            recommended_action="Create/activate matching specialist rooms or adjust requirements.",
            route="/leadership/timetable-setup/rooms",
        )
    )

    duplicate_active_requirements = await _count(
        db,
        select(func.count())
        .select_from(
            select(
                WeeklyTeachingRequirement.class_id,
                WeeklyTeachingRequirement.subject_id,
                WeeklyTeachingRequirement.term_id,
                func.count(WeeklyTeachingRequirement.id).label("duplicate_count"),
            )
            .where(
                WeeklyTeachingRequirement.tenant_id == tenant_id,
                WeeklyTeachingRequirement.is_active.is_(True),
            )
            .group_by(
                WeeklyTeachingRequirement.class_id,
                WeeklyTeachingRequirement.subject_id,
                WeeklyTeachingRequirement.term_id,
            )
            .having(func.count(WeeklyTeachingRequirement.id) > 1)
            .subquery()
        ),
    )
    checks.append(
        _check(
            key="duplicate_active_requirements",
            title="No duplicate active requirement scopes",
            severity=SEVERITY_BLOCKER,
            status=STATUS_FAIL if duplicate_active_requirements > 0 else STATUS_PASS,
            explanation="Duplicate active class-subject-term requirements must be avoided or versioned explicitly.",
            affected_count=duplicate_active_requirements,
            entity_refs=[],
            recommended_action="Deactivate duplicates and retain one approved active requirement per scope.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    teacher_missing_assignment = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.teacher_id.is_(None),
        ),
    )
    checks.append(
        _check(
            key="unassigned_requirement_teachers",
            title="Requirements without assigned teacher",
            severity=SEVERITY_WARNING,
            status=STATUS_ATTENTION if teacher_missing_assignment > 0 else STATUS_PASS,
            explanation="Teacher assignment is optional at this stage but should be completed before generation.",
            affected_count=teacher_missing_assignment,
            entity_refs=[],
            recommended_action="Assign teachers where possible.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    no_fixed_sessions = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.has_fixed_sessions.is_(True),
        ),
    )
    checks.append(
        _check(
            key="fixed_sessions_configured",
            title="Fixed sessions configured",
            severity=SEVERITY_INFORMATION,
            status=STATUS_PASS if no_fixed_sessions > 0 else STATUS_ATTENTION,
            explanation="Fixed sessions are optional and may be left empty for manual-first setup.",
            affected_count=no_fixed_sessions,
            entity_refs=[],
            recommended_action="Add fixed sessions only if policy requires explicit slot locks.",
            route="/leadership/timetable-setup/teaching-requirements",
        )
    )

    manual_only_records = await _count(
        db,
        select(func.count(WeeklyTeachingRequirement.id)).where(
            WeeklyTeachingRequirement.tenant_id == tenant_id,
            WeeklyTeachingRequirement.is_active.is_(True),
            WeeklyTeachingRequirement.source_type == "manual",
        ),
    )
    checks.append(
        _check(
            key="manual_first_configuration",
            title="All configuration entered manually",
            severity=SEVERITY_INFORMATION,
            status=STATUS_PASS if manual_only_records == active_requirements and active_requirements > 0 else STATUS_ATTENTION,
            explanation="Manual-first setup is expected in this batch. Import and extraction flows are deferred.",
            affected_count=manual_only_records,
            entity_refs=[],
            recommended_action="No action required unless planning import-based setup.",
            route="/leadership/timetable-setup/readiness",
        )
    )

    blocker_count = sum(1 for item in checks if item["severity"] == SEVERITY_BLOCKER and item["status"] != STATUS_PASS)
    warning_count = sum(1 for item in checks if item["severity"] == SEVERITY_WARNING and item["status"] != STATUS_PASS)
    information_count = sum(1 for item in checks if item["severity"] == SEVERITY_INFORMATION and item["status"] != STATUS_PASS)

    return {
        "checked_at": _now(),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "information_count": information_count,
        "is_generation_ready": blocker_count == 0,
        "checks": checks,
    }
