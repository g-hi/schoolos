from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.policy_readiness import build_policy_readiness_payload
from services.gateway.timetable_setup.scheduling_problem import (
    BaselineSummary,
    ClassProblemRecord,
    FixedSessionRecord,
    GenerationOverrideRecord,
    LockRecord,
    LogicalPeriod,
    ObjectiveRecord,
    ParallelBlockRecord,
    ParallelChildRecord,
    PolicyConstraintRecord,
    ProblemIssue,
    RoomProblemRecord,
    SchedulingProblem,
    SchedulingProblemBuildResult,
    SubjectProblemRecord,
    TeacherPreferenceRecord,
    TeacherProblemRecord,
    TeachingRequirementRecord,
    ValidationSummary,
)
from shared.db.models import (
    BellSchedule,
    BellSchedulePeriod,
    Class,
    SchoolWeekConfig,
    Subject,
    Teacher,
    TeacherAssignment,
    TeacherSubject,
    TeachingRoom,
    TimetableGenerationConfiguration,
    TimetableGenerationLock,
    TimetableGenerationObjective,
    TimetableGenerationOverride,
    TimetableParallelLessonBlock,
    TimetableParallelLessonChild,
    TimetableTeacherSchedulingPreference,
    TimetablePolicyConstraint,
    TimetableVersion,
    TimetableVersionAssignment,
    User,
    WeeklyTeachingRequirement,
)

DEFAULT_STANDARD_OBJECTIVES: tuple[tuple[str, str], ...] = (
    ("satisfy_hard_constraints", "critical"),
    ("teacher_preferences", "high"),
    ("workload_balance", "high"),
    ("subject_distribution", "normal"),
    ("minimize_teacher_gaps", "normal"),
    ("minimize_room_changes", "normal"),
)

REPAIR_DEFAULT_OBJECTIVES: tuple[tuple[str, str], ...] = (
    ("satisfy_hard_constraints", "critical"),
    ("preserve_existing_assignments", "critical"),
    ("minimize_timetable_disruption", "high"),
    ("teacher_preferences", "normal"),
)

ALLOWED_LOCK_STATES = {"locked", "prefer_to_keep", "flexible"}
ALLOWED_LOCK_TARGET_TYPES = {"session_reference", "teacher", "class", "subject", "grade", "room", "day", "period", "period_range"}


class BaselineAssignmentRow(dict):
    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


class SchedulingProblemBuildError(Exception):
    pass


def _serialize_uuid(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _stable_hash(payload: dict[str, Any]) -> str:
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _sorted_period_keys(periods: tuple[LogicalPeriod, ...]) -> tuple[str, ...]:
    return tuple(item.key for item in sorted(periods, key=lambda p: (p.day_of_week, p.period_number)))


def _to_minutes(start_time: str | None, end_time: str | None) -> int | None:
    if not start_time or not end_time:
        return None
    try:
        sh, sm = [int(x) for x in start_time.split(":")]
        eh, em = [int(x) for x in end_time.split(":")]
    except ValueError:
        return None
    return max(0, (eh * 60 + em) - (sh * 60 + sm))


def _objective_records(configuration: TimetableGenerationConfiguration, rows: list[TimetableGenerationObjective]) -> tuple[ObjectiveRecord, ...]:
    if rows:
        ordered = sorted(rows, key=lambda item: (item.priority_level, item.objective_key))
        return tuple(ObjectiveRecord(objective_key=item.objective_key, priority_level=item.priority_level) for item in ordered)

    defaults = REPAIR_DEFAULT_OBJECTIVES if configuration.generation_mode == "repair" else DEFAULT_STANDARD_OBJECTIVES
    if configuration.generation_mode == "customized":
        defaults = DEFAULT_STANDARD_OBJECTIVES
    return tuple(ObjectiveRecord(objective_key=key, priority_level=priority) for key, priority in defaults)


def _fixed_session_period(rule: dict[str, Any]) -> tuple[int | None, int | None]:
    day = rule.get("day_of_week")
    if not isinstance(day, int):
        day = rule.get("weekday")
    period = rule.get("period_number")
    if not isinstance(period, int):
        period = rule.get("period")
    return day if isinstance(day, int) else None, period if isinstance(period, int) else None


async def _load_configuration(db: AsyncSession, tenant_id: uuid.UUID, configuration_id: uuid.UUID) -> TimetableGenerationConfiguration:
    configuration = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant_id,
        )
    )
    if configuration is None:
        raise SchedulingProblemBuildError("Generation configuration not found in tenant scope.")
    return configuration


async def _load_generation_rows(db: AsyncSession, tenant_id: uuid.UUID, configuration: TimetableGenerationConfiguration) -> dict[str, Any]:
    rows: dict[str, Any] = {}

    schedule_stmt = select(BellSchedule).where(BellSchedule.tenant_id == tenant_id, BellSchedule.is_active.is_(True))
    if configuration.bell_schedule_id is not None:
        schedule_stmt = schedule_stmt.where(BellSchedule.id == configuration.bell_schedule_id)
    else:
        schedule_stmt = schedule_stmt.where(
            or_(BellSchedule.academic_year_id.is_(None), BellSchedule.academic_year_id == configuration.academic_year_id),
            or_(BellSchedule.term_id.is_(None), BellSchedule.term_id == configuration.term_id),
            or_(BellSchedule.campus_id.is_(None), BellSchedule.campus_id == configuration.campus_id),
        ).order_by(BellSchedule.is_default.desc(), BellSchedule.created_at.asc())
    bell_schedule = (await db.execute(schedule_stmt)).scalars().first()
    rows["bell_schedule"] = bell_schedule

    if bell_schedule is not None:
        rows["bell_periods"] = (
            await db.execute(
                select(BellSchedulePeriod)
                .where(
                    BellSchedulePeriod.tenant_id == tenant_id,
                    BellSchedulePeriod.bell_schedule_id == bell_schedule.id,
                    BellSchedulePeriod.is_active.is_(True),
                )
                .order_by(BellSchedulePeriod.period_number.asc(), BellSchedulePeriod.id.asc())
            )
        ).scalars().all()

        school_week = await db.scalar(
            select(SchoolWeekConfig).where(
                SchoolWeekConfig.tenant_id == tenant_id,
                SchoolWeekConfig.id == bell_schedule.school_week_config_id,
                SchoolWeekConfig.is_active.is_(True),
            )
        )
        rows["school_week"] = school_week
    else:
        rows["bell_periods"] = []
        rows["school_week"] = None

    rows["teachers"] = (
        await db.execute(select(Teacher).where(Teacher.tenant_id == tenant_id).order_by(Teacher.id.asc()))
    ).scalars().all()

    teacher_ids = [item.id for item in rows["teachers"]]
    rows["users"] = (
        await db.execute(select(User).where(User.tenant_id == tenant_id, User.id.in_([item.user_id for item in rows["teachers"]])) if teacher_ids else select(User).where(User.id == uuid.UUID(int=0)))
    ).scalars().all()

    rows["teacher_subjects"] = (
        await db.execute(select(TeacherSubject).where(TeacherSubject.teacher_id.in_(teacher_ids)) if teacher_ids else select(TeacherSubject).where(TeacherSubject.teacher_id == uuid.UUID(int=0)))
    ).scalars().all()

    class_stmt = select(Class).where(Class.tenant_id == tenant_id, Class.is_active.is_(True), Class.academic_year_id == configuration.academic_year_id)
    if configuration.campus_id is not None:
        class_stmt = class_stmt.where(Class.campus_id == configuration.campus_id)
    rows["classes"] = (await db.execute(class_stmt.order_by(Class.id.asc()))).scalars().all()

    rows["subjects"] = (await db.execute(select(Subject).where(Subject.tenant_id == tenant_id).order_by(Subject.id.asc()))).scalars().all()

    room_stmt = select(TeachingRoom).where(TeachingRoom.tenant_id == tenant_id, TeachingRoom.is_active.is_(True))
    if configuration.campus_id is not None:
        room_stmt = room_stmt.where(or_(TeachingRoom.campus_id.is_(None), TeachingRoom.campus_id == configuration.campus_id))
    rows["rooms"] = (await db.execute(room_stmt.order_by(TeachingRoom.id.asc()))).scalars().all()

    requirement_stmt = select(WeeklyTeachingRequirement).where(
        WeeklyTeachingRequirement.tenant_id == tenant_id,
        WeeklyTeachingRequirement.academic_year_id == configuration.academic_year_id,
        WeeklyTeachingRequirement.term_id == configuration.term_id,
        WeeklyTeachingRequirement.is_active.is_(True),
    )
    if configuration.campus_id is not None:
        requirement_stmt = requirement_stmt.where(WeeklyTeachingRequirement.campus_id == configuration.campus_id)
    rows["requirements"] = (await db.execute(requirement_stmt.order_by(WeeklyTeachingRequirement.id.asc()))).scalars().all()

    rows["assignments"] = (
        await db.execute(
            select(TeacherAssignment).where(
                TeacherAssignment.tenant_id == tenant_id,
                TeacherAssignment.academic_year_id == configuration.academic_year_id,
                TeacherAssignment.is_active.is_(True),
            )
        )
    ).scalars().all()

    rows["preferences"] = (
        await db.execute(
            select(TimetableTeacherSchedulingPreference)
            .where(
                TimetableTeacherSchedulingPreference.tenant_id == tenant_id,
                TimetableTeacherSchedulingPreference.academic_year_id == configuration.academic_year_id,
                TimetableTeacherSchedulingPreference.term_id == configuration.term_id,
                TimetableTeacherSchedulingPreference.is_active.is_(True),
            )
            .order_by(TimetableTeacherSchedulingPreference.id.asc())
        )
    ).scalars().all()

    rows["overrides"] = (
        await db.execute(
            select(TimetableGenerationOverride)
            .where(
                TimetableGenerationOverride.tenant_id == tenant_id,
                TimetableGenerationOverride.configuration_id == configuration.id,
                TimetableGenerationOverride.is_active.is_(True),
            )
            .order_by(TimetableGenerationOverride.id.asc())
        )
    ).scalars().all()

    rows["locks"] = (
        await db.execute(
            select(TimetableGenerationLock)
            .where(
                TimetableGenerationLock.tenant_id == tenant_id,
                TimetableGenerationLock.configuration_id == configuration.id,
                TimetableGenerationLock.is_active.is_(True),
            )
            .order_by(TimetableGenerationLock.id.asc())
        )
    ).scalars().all()

    rows["objectives"] = (
        await db.execute(
            select(TimetableGenerationObjective)
            .where(
                TimetableGenerationObjective.tenant_id == tenant_id,
                TimetableGenerationObjective.configuration_id == configuration.id,
            )
            .order_by(TimetableGenerationObjective.id.asc())
        )
    ).scalars().all()

    rows["parallel_blocks"] = (
        await db.execute(
            select(TimetableParallelLessonBlock)
            .where(
                TimetableParallelLessonBlock.tenant_id == tenant_id,
                TimetableParallelLessonBlock.academic_year_id == configuration.academic_year_id,
                TimetableParallelLessonBlock.term_id == configuration.term_id,
                TimetableParallelLessonBlock.is_active.is_(True),
            )
            .order_by(TimetableParallelLessonBlock.id.asc())
        )
    ).scalars().all()

    block_ids = [item.id for item in rows["parallel_blocks"]]
    rows["parallel_children"] = (
        await db.execute(
            select(TimetableParallelLessonChild)
            .where(
                TimetableParallelLessonChild.tenant_id == tenant_id,
                TimetableParallelLessonChild.parallel_block_id.in_(block_ids),
                TimetableParallelLessonChild.is_active.is_(True),
            )
            .order_by(TimetableParallelLessonChild.parallel_block_id.asc(), TimetableParallelLessonChild.sequence_order.asc().nulls_last(), TimetableParallelLessonChild.id.asc())
        )
        if block_ids
        else await db.execute(select(TimetableParallelLessonChild).where(TimetableParallelLessonChild.id == uuid.UUID(int=0)))
    ).scalars().all()

    rows["policy_constraints"] = (
        await db.execute(
            select(TimetablePolicyConstraint).where(
                TimetablePolicyConstraint.tenant_id == tenant_id,
                TimetablePolicyConstraint.is_active.is_(True),
            )
        )
    ).scalars().all()

    baseline_version_id = getattr(configuration, "baseline_timetable_version_id", None)
    if baseline_version_id is None and configuration.baseline_reference_type == "timetable_version" and configuration.baseline_reference_id is not None:
        baseline_version_id = configuration.baseline_reference_id

    baseline_version = None
    baseline_assignments: list[TimetableVersionAssignment] = []
    if baseline_version_id is not None:
        baseline_version = await db.scalar(
            select(TimetableVersion).where(
                TimetableVersion.id == baseline_version_id,
                TimetableVersion.tenant_id == tenant_id,
            )
        )
        if baseline_version is not None:
            baseline_assignments = (
                await db.execute(
                    select(TimetableVersionAssignment)
                    .where(
                        TimetableVersionAssignment.tenant_id == tenant_id,
                        TimetableVersionAssignment.timetable_version_id == baseline_version.id,
                    )
                    .order_by(TimetableVersionAssignment.assignment_key.asc())
                )
            ).scalars().all()

    rows["baseline_version"] = baseline_version
    rows["baseline_assignments"] = baseline_assignments

    return rows


def _build_from_sources(
    *,
    configuration: TimetableGenerationConfiguration,
    rows: dict[str, Any],
    policy_payload: dict[str, Any],
) -> SchedulingProblemBuildResult:
    blockers: list[ProblemIssue] = []
    warnings: list[ProblemIssue] = []
    exclusions: list[ProblemIssue] = []

    school_week = rows["school_week"]
    bell_schedule = rows["bell_schedule"]
    bell_periods: list[BellSchedulePeriod] = rows["bell_periods"]

    if school_week is None:
        blockers.append(ProblemIssue(code="missing_school_week", message="No active school week config available for this configuration.", severity="blocker"))
    if bell_schedule is None:
        blockers.append(ProblemIssue(code="missing_bell_schedule", message="No active bell schedule available for this configuration.", severity="blocker"))

    operational_days = tuple(sorted(int(day) for day in (school_week.operational_weekdays if school_week else [])))
    logical_periods: list[LogicalPeriod] = []
    for day in operational_days:
        for period in sorted(bell_periods, key=lambda item: (item.period_number, item.id)):
            key = f"d{day}:p{period.period_number}"
            logical_periods.append(
                LogicalPeriod(
                    key=key,
                    day_of_week=day,
                    period_number=int(period.period_number),
                    is_teaching_period=bool(period.is_teaching_period),
                    label=period.label,
                    starts_at=period.start_time,
                    ends_at=period.end_time,
                    duration_minutes=_to_minutes(period.start_time, period.end_time),
                )
            )

    if not logical_periods:
        blockers.append(ProblemIssue(code="missing_logical_periods", message="No logical periods could be derived from school week and bell schedule periods.", severity="blocker"))

    logical_period_tuple = tuple(sorted(logical_periods, key=lambda item: (item.day_of_week, item.period_number, item.key)))
    teaching_period_keys = tuple(item.key for item in logical_period_tuple if item.is_teaching_period)

    teacher_rows: list[Teacher] = rows["teachers"]
    user_map = {item.id: item for item in rows["users"]}
    teacher_subject_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for item in rows["teacher_subjects"]:
        teacher_subject_map.setdefault(item.teacher_id, []).append(item.subject_id)

    assignment_rows: list[TeacherAssignment] = rows["assignments"]
    fixed_assignment_map: dict[uuid.UUID, list[str]] = {}
    for item in assignment_rows:
        fixed_assignment_map.setdefault(item.teacher_id, []).append(str(item.id))

    teacher_unavailability: dict[str, set[str]] = {}
    for item in policy_payload.get("effective_constraints", []):
        if item.get("selected") and item.get("type") == "teacher_unavailable":
            teacher_id = item.get("scope_reference_id")
            parameters = item.get("parameters", {})
            weekdays = [value for value in (parameters.get("weekdays") or []) if isinstance(value, int)]
            periods = [value for value in (parameters.get("period_numbers") or []) if isinstance(value, int)]
            for day in weekdays:
                for period_number in periods:
                    teacher_unavailability.setdefault(str(teacher_id), set()).add(f"d{day}:p{period_number}")

    teachers: list[TeacherProblemRecord] = []
    for teacher in sorted(teacher_rows, key=lambda item: str(item.id)):
        user = user_map.get(teacher.user_id)
        if user is None:
            blockers.append(ProblemIssue(code="teacher_user_missing", message="Teacher user profile is missing.", severity="blocker", entity_type="teacher", entity_id=str(teacher.id)))
            continue
        subject_ids = tuple(sorted(str(subject_id) for subject_id in teacher_subject_map.get(teacher.id, [])))
        unavailable_periods = tuple(sorted(teacher_unavailability.get(str(teacher.id), set())))
        available_periods = tuple(item for item in teaching_period_keys if item not in unavailable_periods)
        teachers.append(
            TeacherProblemRecord(
                teacher_id=str(teacher.id),
                user_id=str(user.id),
                active=bool(user.is_active),
                max_weekly_hours=int(teacher.max_weekly_hours or 0),
                eligible_subject_ids=subject_ids,
                weekly_load_limit_sessions=int(teacher.max_weekly_hours or 0),
                daily_load_limit_sessions=None,
                consecutive_session_limit=None,
                available_period_keys=available_periods,
                unavailable_period_keys=unavailable_periods,
                campus_id=None,
                fixed_assignment_requirement_ids=tuple(sorted(fixed_assignment_map.get(teacher.id, []))),
            )
        )

    class_rows: list[Class] = rows["classes"]
    requirement_rows: list[WeeklyTeachingRequirement] = rows["requirements"]
    requirements_by_class: dict[uuid.UUID, list[str]] = {}
    for item in requirement_rows:
        requirements_by_class.setdefault(item.class_id, []).append(str(item.id))

    classes: list[ClassProblemRecord] = []
    for klass in sorted(class_rows, key=lambda item: str(item.id)):
        fixed_ids = tuple(
            sorted(
                f"{req.id}:{index}"
                for req in requirement_rows
                if req.class_id == klass.id and req.has_fixed_sessions
                for index, _ in enumerate(req.fixed_session_rules or [])
            )
        )
        classes.append(
            ClassProblemRecord(
                class_id=str(klass.id),
                code=klass.code,
                grade_reference=str(klass.grade_level_id) if klass.grade_level_id else klass.grade,
                active=bool(klass.is_active),
                campus_id=_serialize_uuid(klass.campus_id),
                schedulable_period_keys=teaching_period_keys,
                unavailable_period_keys=tuple(),
                requirement_ids=tuple(sorted(requirements_by_class.get(klass.id, []))),
                fixed_session_ids=fixed_ids,
                parallel_block_ids=tuple(),
            )
        )

    subject_rows: list[Subject] = rows["subjects"]
    subjects_by_id = {item.id: item for item in subject_rows}
    subject_requirements: dict[uuid.UUID, list[WeeklyTeachingRequirement]] = {}
    for requirement in requirement_rows:
        subject_requirements.setdefault(requirement.subject_id, []).append(requirement)

    teacher_eligibility: dict[str, tuple[str, ...]] = {}
    for teacher in teachers:
        for subject_id in teacher.eligible_subject_ids:
            teacher_eligibility.setdefault(subject_id, tuple())

    eligibility_map: dict[str, set[str]] = {}
    for teacher in teachers:
        for subject_id in teacher.eligible_subject_ids:
            eligibility_map.setdefault(subject_id, set()).add(teacher.teacher_id)

    subjects: list[SubjectProblemRecord] = []
    for subject in sorted(subject_rows, key=lambda item: str(item.id)):
        reqs = subject_requirements.get(subject.id, [])
        sessions_per_week = sum(int(item.sessions_per_week) for item in reqs)
        minutes = sum(int(item.sessions_per_week) * int(item.periods_per_session) for item in reqs)
        room_requirements = tuple(sorted({str(item.specialist_room_type) for item in reqs if item.specialist_room_type}))
        subjects.append(
            SubjectProblemRecord(
                subject_id=str(subject.id),
                code=subject.code,
                name=subject.name,
                required_weekly_sessions=sessions_per_week if reqs else None,
                required_weekly_minutes=minutes if reqs else None,
                min_daily_sessions=min((int(item.min_daily_sessions) for item in reqs), default=None),
                max_daily_sessions=max((int(item.max_daily_sessions) for item in reqs), default=None),
                room_requirements=room_requirements,
                teacher_eligibility_ids=tuple(sorted(eligibility_map.get(str(subject.id), set()))),
            )
        )

    room_rows: list[TeachingRoom] = rows["rooms"]
    room_unavailability: dict[str, set[str]] = {}
    for item in policy_payload.get("effective_constraints", []):
        if item.get("selected") and item.get("type") == "room_unavailable":
            room_id = item.get("scope_reference_id")
            parameters = item.get("parameters", {})
            weekdays = [value for value in (parameters.get("weekdays") or []) if isinstance(value, int)]
            periods = [value for value in (parameters.get("period_numbers") or []) if isinstance(value, int)]
            for day in weekdays:
                for period_number in periods:
                    room_unavailability.setdefault(str(room_id), set()).add(f"d{day}:p{period_number}")

    rooms: list[RoomProblemRecord] = []
    for room in sorted(room_rows, key=lambda item: str(item.id)):
        unavailable = tuple(sorted(room_unavailability.get(str(room.id), set())))
        available = tuple(item for item in teaching_period_keys if item not in unavailable)
        rooms.append(
            RoomProblemRecord(
                room_id=str(room.id),
                room_code=room.room_code,
                room_name=room.room_name,
                room_type=room.room_type,
                capacity=int(room.capacity),
                campus_id=_serialize_uuid(room.campus_id),
                specialist_capabilities=tuple(sorted(str(item) for item in (room.specialist_capabilities or []))),
                available_period_keys=available,
                unavailable_period_keys=unavailable,
            )
        )

    class_ids = {item.class_id for item in classes}
    subject_ids = {item.subject_id for item in subjects}
    teacher_ids = {item.teacher_id for item in teachers}

    teaching_requirements: list[TeachingRequirementRecord] = []
    fixed_sessions: list[FixedSessionRecord] = []

    for requirement in sorted(requirement_rows, key=lambda item: str(item.id)):
        requirement_id = str(requirement.id)
        class_id = str(requirement.class_id)
        subject_id = str(requirement.subject_id)
        teacher_id = str(requirement.teacher_id) if requirement.teacher_id else None

        if class_id not in class_ids:
            blockers.append(ProblemIssue(code="requirement_class_missing", message="Requirement class is missing or inactive.", severity="blocker", entity_type="weekly_teaching_requirement", entity_id=requirement_id))
            continue
        if subject_id not in subject_ids:
            blockers.append(ProblemIssue(code="requirement_subject_missing", message="Requirement subject is missing.", severity="blocker", entity_type="weekly_teaching_requirement", entity_id=requirement_id))
            continue
        if teacher_id is not None and teacher_id not in teacher_ids:
            blockers.append(ProblemIssue(code="requirement_teacher_missing", message="Requirement teacher is missing or inactive.", severity="blocker", entity_type="weekly_teaching_requirement", entity_id=requirement_id))
            continue

        eligible_teacher_ids = tuple(sorted(eligibility_map.get(subject_id, set())))
        weekly_minutes = int(requirement.sessions_per_week) * int(requirement.periods_per_session)
        teaching_requirements.append(
            TeachingRequirementRecord(
                requirement_id=requirement_id,
                class_id=class_id,
                subject_id=subject_id,
                teacher_id=teacher_id,
                eligible_teacher_ids=eligible_teacher_ids,
                weekly_sessions=int(requirement.sessions_per_week),
                weekly_minutes=weekly_minutes,
                periods_per_session=int(requirement.periods_per_session),
                min_daily_sessions=int(requirement.min_daily_sessions),
                max_daily_sessions=int(requirement.max_daily_sessions),
                specialist_room_type=requirement.specialist_room_type,
                preferred_period_numbers=tuple(sorted(int(value) for value in (requirement.preferred_period_numbers or []))),
                forbidden_period_numbers=tuple(sorted(int(value) for value in (requirement.forbidden_period_numbers or []))),
                fixed_session_rule_indexes=tuple(range(len(requirement.fixed_session_rules or []))),
                source_type=requirement.source_type,
            )
        )

        if requirement.has_fixed_sessions:
            for index, rule in enumerate(requirement.fixed_session_rules or []):
                day_of_week, period_number = _fixed_session_period(rule if isinstance(rule, dict) else {})
                if day_of_week is None or period_number is None:
                    blockers.append(ProblemIssue(code="fixed_session_malformed", message="Fixed session rule is missing day/period identity.", severity="blocker", entity_type="weekly_teaching_requirement", entity_id=requirement_id))
                    continue
                period_key = f"d{day_of_week}:p{period_number}"
                if period_key not in set(_sorted_period_keys(logical_period_tuple)):
                    blockers.append(ProblemIssue(code="fixed_session_invalid_period", message="Fixed session period is outside the logical period domain.", severity="blocker", entity_type="weekly_teaching_requirement", entity_id=requirement_id))
                    continue
                fixed_sessions.append(
                    FixedSessionRecord(
                        fixed_session_id=f"{requirement_id}:{index}",
                        requirement_id=requirement_id,
                        class_id=class_id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        room_id=str(rule.get("room_id")) if isinstance(rule, dict) and rule.get("room_id") else None,
                        day_of_week=day_of_week,
                        period_number=period_number,
                        period_key=period_key,
                        enforcement_source="weekly_requirement_fixed_session_rule",
                        provenance={"rule_index": index, "rule": rule},
                    )
                )

    if not teaching_requirements:
        blockers.append(ProblemIssue(code="missing_teaching_requirements", message="No active weekly teaching requirements available.", severity="blocker"))

    preference_rows: list[TimetableTeacherSchedulingPreference] = rows["preferences"]
    teacher_preferences: list[TeacherPreferenceRecord] = []
    valid_period_numbers = {item.period_number for item in logical_period_tuple}

    for preference in sorted(preference_rows, key=lambda item: str(item.id)):
        pref_teacher_id = str(preference.teacher_id)
        if pref_teacher_id not in teacher_ids:
            blockers.append(ProblemIssue(code="preference_teacher_missing", message="Teacher preference references missing or inactive teacher.", severity="blocker", entity_type="teacher_preference", entity_id=str(preference.id)))
            continue

        weekdays = tuple(sorted(int(value) for value in (preference.weekdays_json or []) if isinstance(value, int)))
        period_numbers = tuple(sorted(int(value) for value in (preference.period_numbers_json or []) if isinstance(value, int)))

        if preference.strength == "hard":
            for period_number in period_numbers:
                if period_number not in valid_period_numbers:
                    blockers.append(ProblemIssue(code="hard_preference_invalid_period", message="Hard teacher preference references unknown logical period.", severity="blocker", entity_type="teacher_preference", entity_id=str(preference.id)))

        teacher_preferences.append(
            TeacherPreferenceRecord(
                preference_id=str(preference.id),
                teacher_id=pref_teacher_id,
                preference_type=preference.preference_type,
                strength=preference.strength,
                weekday_values=weekdays,
                period_numbers=period_numbers,
                effective_start_date=preference.effective_start_date.isoformat() if preference.effective_start_date else None,
                effective_end_date=preference.effective_end_date.isoformat() if preference.effective_end_date else None,
                source_type=preference.source_type,
                provenance=preference.provenance_json or {},
            )
        )

    override_rows: list[TimetableGenerationOverride] = rows["overrides"]
    overrides = tuple(
        GenerationOverrideRecord(
            override_id=str(item.id),
            configuration_id=str(item.configuration_id),
            override_type=item.override_type,
            strength=item.strength,
            scope_type=item.scope_type,
            scope_reference_id=_serialize_uuid(item.scope_reference_id),
            scope_reference_code=item.scope_reference_code,
            payload=item.payload_json or {},
            source_type=item.source_type,
            provenance=item.provenance_json or {},
        )
        for item in sorted(override_rows, key=lambda row: str(row.id))
    )

    lock_rows: list[TimetableGenerationLock] = rows["locks"]
    locks_list: list[LockRecord] = []
    for item in sorted(lock_rows, key=lambda row: str(row.id)):
        if item.lock_state not in ALLOWED_LOCK_STATES:
            blockers.append(ProblemIssue(code="invalid_lock_state", message="Lock state is not supported.", severity="blocker", entity_type="generation_lock", entity_id=str(item.id)))
            continue
        if item.target_type not in ALLOWED_LOCK_TARGET_TYPES:
            blockers.append(ProblemIssue(code="invalid_lock_target", message="Lock target type is not supported.", severity="blocker", entity_type="generation_lock", entity_id=str(item.id)))
            continue
        locks_list.append(
            LockRecord(
                lock_id=str(item.id),
                configuration_id=str(item.configuration_id),
                lock_state=item.lock_state,
                target_type=item.target_type,
                target_reference_id=_serialize_uuid(item.target_reference_id),
                target_reference_code=item.target_reference_code,
                day_of_week=item.day_of_week,
                period_number=item.period_number,
                period_end_number=item.period_end_number,
                is_manual_hard_lock=bool(item.is_manual_hard_lock),
                source_type=item.source_type,
                provenance=item.provenance_json or {},
            )
        )

    block_rows: list[TimetableParallelLessonBlock] = rows["parallel_blocks"]
    child_rows: list[TimetableParallelLessonChild] = rows["parallel_children"]
    children_by_block: dict[uuid.UUID, list[TimetableParallelLessonChild]] = {}
    for child in child_rows:
        children_by_block.setdefault(child.parallel_block_id, []).append(child)

    parallel_blocks: list[ParallelBlockRecord] = []
    for block in sorted(block_rows, key=lambda row: str(row.id)):
        child_payload: list[ParallelChildRecord] = []
        for child in children_by_block.get(block.id, []):
            child_payload.append(
                ParallelChildRecord(
                    child_id=str(child.id),
                    requirement_id=_serialize_uuid(child.requirement_id),
                    subject_id=_serialize_uuid(child.subject_id),
                    teacher_id=_serialize_uuid(child.teacher_id),
                    room_id=_serialize_uuid(child.room_id),
                    sequence_order=child.sequence_order,
                    requirement=child.requirement_json or {},
                )
            )

        if not child_payload:
            blockers.append(ProblemIssue(code="parallel_block_empty", message="Parallel block has no active children.", severity="blocker", entity_type="parallel_block", entity_id=str(block.id)))

        parallel_blocks.append(
            ParallelBlockRecord(
                block_id=str(block.id),
                class_id=str(block.class_id),
                display_label=block.display_label,
                block_type=block.block_type,
                synchronization_requirement=block.synchronization_requirement,
                active=bool(block.is_active),
                source_type=block.source_type,
                provenance=block.provenance_json or {},
                children=tuple(sorted(child_payload, key=lambda item: (item.sequence_order or 999999, item.child_id))),
            )
        )

    operational_constraints = []
    for item in policy_payload.get("effective_constraints", []):
        if not item.get("selected"):
            continue
        operational_constraints.append(
            PolicyConstraintRecord(
                constraint_id=str(item.get("id")),
                policy_set_id=str(item.get("policy_set_id")) if item.get("policy_set_id") else None,
                constraint_type=item.get("type"),
                category=item.get("category"),
                enforcement=item.get("enforcement_level"),
                scope_type=item.get("scope_type"),
                scope_reference_id=str(item.get("scope_reference_id")) if item.get("scope_reference_id") else None,
                scope_reference_code=item.get("scope_reference_code"),
                parameters=item.get("parameters", {}) or {},
                priority=int(item.get("priority") or 0),
                weight=float(item.get("weight") or 0.0),
                lifecycle_status=item.get("lifecycle_status", "unknown"),
                exception_applied=bool(item.get("exception_applied", False)),
            )
        )

    generation_allowed = bool(policy_payload.get("generation_allowed", False))
    if not generation_allowed:
        blockers.append(ProblemIssue(code="phase_10b_generation_blocked", message="Phase 10B readiness gate does not allow scheduling generation.", severity="blocker"))

    baseline_reference_id = getattr(configuration, "baseline_timetable_version_id", None) or configuration.baseline_reference_id
    baseline_reference_type = configuration.baseline_reference_type or ("timetable_version" if baseline_reference_id else None)
    baseline_version: TimetableVersion | None = rows.get("baseline_version")
    baseline_assignments: list[TimetableVersionAssignment] = rows.get("baseline_assignments", [])

    baseline_supported = bool(
        baseline_reference_id is not None
        and baseline_version is not None
        and baseline_version.tenant_id == configuration.tenant_id
        and baseline_version.lifecycle_status in {"published", "superseded"}
        and baseline_version.generation_mode in {"standard", "customized", "repair"}
        and baseline_version.timetable_id is not None
        and baseline_assignments
    )

    baseline_rows: list[dict[str, Any]] = []
    if baseline_supported:
        for item in baseline_assignments:
            baseline_rows.append(
                BaselineAssignmentRow(
                    {
                        "assignment_key": item.assignment_key,
                        "occurrence_id": item.occurrence_id,
                        "requirement_id": item.requirement_id,
                        "class_id": item.class_id,
                        "subject_id": item.subject_id,
                        "teacher_id": item.teacher_id,
                        "room_id": item.room_id,
                        "day_key": item.day_key,
                        "period_key": item.period_key,
                        "periods_per_session": int(item.periods_per_session),
                        "occupied_period_keys": list(item.occupied_period_keys_json or []),
                        "parallel_block_id": item.parallel_block_id,
                        "parallel_child_id": item.parallel_child_id,
                        "fixed": bool(item.fixed),
                        "lock_state": item.lock_state,
                        "provenance": {
                            "baseline_version_id": str(item.timetable_version_id),
                            "source": "phase_10c_batch5_canonical_baseline",
                        },
                    }
                )
            )

    baseline = BaselineSummary(
        supported=baseline_supported,
        reason="canonical_timetable_version" if baseline_supported else "baseline_not_available",
        baseline_reference_type=baseline_reference_type,
        baseline_reference_id=_serialize_uuid(baseline_reference_id),
        assignments=tuple(baseline_rows),
    )
    if configuration.generation_mode == "repair":
        if baseline_reference_id is None:
            blockers.append(ProblemIssue(code="repair_requires_baseline", message="Repair mode requires baseline_reference_id.", severity="blocker"))
        elif baseline_version is None:
            blockers.append(ProblemIssue(code="repair_baseline_not_found", message="Configured canonical repair baseline version was not found in tenant scope.", severity="blocker"))
        elif baseline_version.lifecycle_status not in {"published", "superseded"}:
            blockers.append(ProblemIssue(code="repair_baseline_invalid_status", message="Repair baseline must be an immutable published or superseded timetable version.", severity="blocker"))
        if baseline_version is not None:
            if baseline_version.tenant_id != configuration.tenant_id:
                blockers.append(ProblemIssue(code="repair_baseline_cross_tenant", message="Repair baseline version is outside tenant scope.", severity="blocker"))
            if baseline_version.generation_mode not in {"standard", "customized", "repair"}:
                blockers.append(ProblemIssue(code="repair_baseline_invalid_mode", message="Repair baseline version has unsupported generation mode.", severity="blocker"))
            if baseline_version.timetable_id is None:
                blockers.append(ProblemIssue(code="repair_baseline_invalid_scope", message="Repair baseline version has no timetable scope.", severity="blocker"))
        if baseline_version is not None and not baseline_rows:
            blockers.append(ProblemIssue(code="repair_baseline_assignments_missing", message="Repair baseline version has no canonical assignments.", severity="blocker"))

    objectives = _objective_records(configuration, rows["objectives"])
    if configuration.generation_mode == "repair" and not any(item.objective_key in {"minimize_timetable_disruption", "preserve_existing_assignments"} for item in objectives):
        warnings.append(ProblemIssue(code="repair_disruption_objective_missing", message="Repair mode is active without explicit disruption objectives; defaults were applied.", severity="warning"))

    source_summary = {
        "teacher_count": len(teachers),
        "class_count": len(classes),
        "subject_count": len(subjects),
        "room_count": len(rooms),
        "teaching_requirement_count": len(teaching_requirements),
        "fixed_session_count": len(fixed_sessions),
        "policy_constraint_count": len(operational_constraints),
        "teacher_preference_count": len(teacher_preferences),
        "override_count": len(overrides),
        "lock_count": len(locks_list),
        "parallel_block_count": len(parallel_blocks),
    }

    coverage = {
        "logical_period_count": len(logical_period_tuple),
        "teaching_period_count": len(teaching_period_keys),
        "school_week_present": school_week is not None,
        "bell_schedule_present": bell_schedule is not None,
    }

    validation = ValidationSummary(
        valid=not blockers,
        blocker_count=len(blockers),
        warning_count=len(warnings),
        excluded_record_count=len(exclusions),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        exclusions=tuple(exclusions),
        source_summary=source_summary,
        build_coverage=coverage,
    )

    canonical_fingerprint_payload = {
        "tenant_id": str(configuration.tenant_id),
        "configuration_id": str(configuration.id),
        "generation_mode": configuration.generation_mode,
        "stability_mode": configuration.stability_mode,
        "school_week": {
            "id": _serialize_uuid(school_week.id) if school_week else None,
            "operational_weekdays": list(operational_days),
        },
        "logical_periods": [asdict(item) for item in logical_period_tuple],
        "teachers": [asdict(item) for item in sorted(teachers, key=lambda item: item.teacher_id)],
        "classes": [asdict(item) for item in sorted(classes, key=lambda item: item.class_id)],
        "subjects": [asdict(item) for item in sorted(subjects, key=lambda item: item.subject_id)],
        "rooms": [asdict(item) for item in sorted(rooms, key=lambda item: item.room_id)],
        "requirements": [asdict(item) for item in sorted(teaching_requirements, key=lambda item: item.requirement_id)],
        "fixed_sessions": [asdict(item) for item in sorted(fixed_sessions, key=lambda item: item.fixed_session_id)],
        "preferences": [asdict(item) for item in sorted(teacher_preferences, key=lambda item: item.preference_id)],
        "overrides": [asdict(item) for item in sorted(overrides, key=lambda item: item.override_id)],
        "locks": [asdict(item) for item in sorted(locks_list, key=lambda item: item.lock_id)],
        "parallel_blocks": [asdict(item) for item in sorted(parallel_blocks, key=lambda item: item.block_id)],
        "policy_constraints": [asdict(item) for item in sorted(operational_constraints, key=lambda item: item.constraint_id)],
        "objectives": [asdict(item) for item in objectives],
        "repair_scope": configuration.repair_scope_json or {},
    }
    source_fingerprint = _stable_hash(canonical_fingerprint_payload)
    source_revision = f"phase10c-b2:{source_fingerprint[:12]}"
    problem_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{configuration.id}:{source_fingerprint}"))

    teacher_availability = {item.teacher_id: item.available_period_keys for item in teachers}
    room_availability = {item.room_id: item.available_period_keys for item in rooms}
    teacher_eligibility_map = {item.subject_id: item.teacher_eligibility_ids for item in subjects}
    room_requirements_map = {item.requirement_id: tuple([item.specialist_room_type] if item.specialist_room_type else []) for item in teaching_requirements}

    solver_eligible = bool(
        generation_allowed
        and validation.valid
        and configuration.lifecycle_status == "approved"
    )

    problem = SchedulingProblem(
        problem_id=problem_id,
        schema_version="phase_10c_batch2_v1",
        tenant_id=str(configuration.tenant_id),
        academic_year_id=str(configuration.academic_year_id),
        term_id=str(configuration.term_id),
        campus_id=_serialize_uuid(configuration.campus_id),
        generation_configuration_id=str(configuration.id),
        generation_mode=configuration.generation_mode,
        built_at=datetime.now(UTC),
        source_fingerprint=source_fingerprint,
        source_revision=source_revision,
        school_week={
            "id": _serialize_uuid(school_week.id) if school_week else None,
            "name": school_week.name if school_week else None,
            "operational_weekdays": list(operational_days),
        },
        logical_periods=logical_period_tuple,
        bell_schedule_reference={
            "id": _serialize_uuid(bell_schedule.id) if bell_schedule else None,
            "name": bell_schedule.name if bell_schedule else None,
            "schedule_type": bell_schedule.schedule_type if bell_schedule else None,
        },
        teachers=tuple(sorted(teachers, key=lambda item: item.teacher_id)),
        classes=tuple(sorted(classes, key=lambda item: item.class_id)),
        subjects=tuple(sorted(subjects, key=lambda item: item.subject_id)),
        rooms=tuple(sorted(rooms, key=lambda item: item.room_id)),
        teaching_requirements=tuple(sorted(teaching_requirements, key=lambda item: item.requirement_id)),
        fixed_sessions=tuple(sorted(fixed_sessions, key=lambda item: item.fixed_session_id)),
        teacher_availability=teacher_availability,
        room_availability=room_availability,
        teacher_eligibility=teacher_eligibility_map,
        room_requirements=room_requirements_map,
        policy_constraints=tuple(sorted(operational_constraints, key=lambda item: item.constraint_id)),
        teacher_preferences=tuple(sorted(teacher_preferences, key=lambda item: item.preference_id)),
        generation_overrides=tuple(sorted(overrides, key=lambda item: item.override_id)),
        locks=tuple(sorted(locks_list, key=lambda item: item.lock_id)),
        parallel_lesson_blocks=tuple(sorted(parallel_blocks, key=lambda item: item.block_id)),
        baseline=baseline,
        repair_scope=configuration.repair_scope_json or {},
        stability_mode=configuration.stability_mode,
        optimization_objectives=objectives,
        warnings=tuple(warnings),
        exclusions=tuple(exclusions),
        provenance={
            "builder": "phase_10c_batch2",
            "policy_readiness_generation_allowed": generation_allowed,
            "configuration_validation_summary": configuration.validation_summary_json or {},
            "explicit_non_actions": {
                "solver_started": False,
                "candidate_generated": False,
                "timetable_published": False,
            },
        },
        validation_summary=validation,
        solver_eligible=solver_eligible,
    )

    return SchedulingProblemBuildResult(problem=problem, validation=validation)


async def build_scheduling_problem(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    configuration_id: uuid.UUID,
) -> SchedulingProblemBuildResult:
    configuration = await _load_configuration(db=db, tenant_id=tenant_id, configuration_id=configuration_id)

    rows = await _load_generation_rows(db=db, tenant_id=tenant_id, configuration=configuration)

    policy_payload = await build_policy_readiness_payload(
        db,
        tenant_id,
        academic_year_id=configuration.academic_year_id,
        term_id=configuration.term_id,
        campus_id=configuration.campus_id,
    )

    return _build_from_sources(
        configuration=configuration,
        rows=rows,
        policy_payload=policy_payload,
    )


def summarize_problem(result: SchedulingProblemBuildResult) -> dict[str, Any]:
    summary = {
        "problem_id": result.problem.problem_id,
        "schema_version": result.problem.schema_version,
        "generation_configuration_id": result.problem.generation_configuration_id,
        "generation_mode": result.problem.generation_mode,
        "stability_mode": result.problem.stability_mode,
        "solver_eligible": result.problem.solver_eligible,
        "source_fingerprint": result.problem.source_fingerprint,
        "source_revision": result.problem.source_revision,
        "counts": result.validation.source_summary,
        "blocker_count": result.validation.blocker_count,
        "warning_count": result.validation.warning_count,
        "excluded_record_count": result.validation.excluded_record_count,
        "blockers": [asdict(item) for item in result.validation.blockers],
        "warnings": [asdict(item) for item in result.validation.warnings],
        "exclusions": [asdict(item) for item in result.validation.exclusions],
        "repair": {
            "scope": result.problem.repair_scope,
            "baseline_supported": result.problem.baseline.supported,
            "baseline_reason": result.problem.baseline.reason,
            "baseline_reference_type": result.problem.baseline.baseline_reference_type,
            "baseline_reference_id": result.problem.baseline.baseline_reference_id,
        },
        "policy_readiness_generation_allowed": bool(result.problem.provenance.get("policy_readiness_generation_allowed", False)),
        "explicit_non_actions": result.problem.provenance.get("explicit_non_actions", {}),
    }
    return summary
