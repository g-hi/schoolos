from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

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
    SubjectProblemRecord,
    TeacherPreferenceRecord,
    TeacherProblemRecord,
    TeachingRequirementRecord,
    ValidationSummary,
)


def _periods() -> tuple[LogicalPeriod, ...]:
    rows: list[LogicalPeriod] = []
    for day in range(0, 5):
        for period in range(1, 5):
            rows.append(
                LogicalPeriod(
                    key=f"d{day}:p{period}",
                    day_of_week=day,
                    period_number=period,
                    is_teaching_period=True,
                    label=f"P{period}",
                    starts_at=f"0{7 + period}:00",
                    ends_at=f"0{7 + period}:40",
                    duration_minutes=40,
                )
            )
    return tuple(rows)


def make_problem(*, solver_eligible: bool = True, include_parallel: bool = False, with_baseline: bool = False, stability_mode: str = "balanced") -> SchedulingProblem:
    periods = _periods()

    teachers = (
        TeacherProblemRecord(
            teacher_id="t1",
            user_id="u1",
            active=True,
            max_weekly_hours=20,
            eligible_subject_ids=("s_math", "s_lang"),
            weekly_load_limit_sessions=20,
            daily_load_limit_sessions=3,
            consecutive_session_limit=3,
            available_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
            campus_id="c1",
            fixed_assignment_requirement_ids=tuple(),
        ),
        TeacherProblemRecord(
            teacher_id="t2",
            user_id="u2",
            active=True,
            max_weekly_hours=20,
            eligible_subject_ids=("s_math",),
            weekly_load_limit_sessions=20,
            daily_load_limit_sessions=3,
            consecutive_session_limit=3,
            available_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
            campus_id="c1",
            fixed_assignment_requirement_ids=tuple(),
        ),
        TeacherProblemRecord(
            teacher_id="t3",
            user_id="u3",
            active=True,
            max_weekly_hours=20,
            eligible_subject_ids=("s_lang",),
            weekly_load_limit_sessions=20,
            daily_load_limit_sessions=3,
            consecutive_session_limit=3,
            available_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
            campus_id="c1",
            fixed_assignment_requirement_ids=tuple(),
        ),
    )

    classes = (
        ClassProblemRecord(
            class_id="class_8a",
            code="8A",
            grade_reference="g8",
            active=True,
            campus_id="c1",
            schedulable_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
            requirement_ids=("req_math_8a", "req_lang_8a"),
            fixed_session_ids=("fx_1",),
            parallel_block_ids=("pb_lang",) if include_parallel else tuple(),
        ),
        ClassProblemRecord(
            class_id="class_8b",
            code="8B",
            grade_reference="g8",
            active=True,
            campus_id="c1",
            schedulable_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
            requirement_ids=("req_math_8b",),
            fixed_session_ids=tuple(),
            parallel_block_ids=tuple(),
        ),
    )

    subjects = (
        SubjectProblemRecord(
            subject_id="s_math",
            code="MATH",
            name="Mathematics",
            required_weekly_sessions=4,
            required_weekly_minutes=160,
            min_daily_sessions=0,
            max_daily_sessions=2,
            room_requirements=tuple(),
            teacher_eligibility_ids=("t1", "t2"),
        ),
        SubjectProblemRecord(
            subject_id="s_lang",
            code="LANG",
            name="Foreign Language",
            required_weekly_sessions=3,
            required_weekly_minutes=120,
            min_daily_sessions=0,
            max_daily_sessions=2,
            room_requirements=tuple(),
            teacher_eligibility_ids=("t1", "t3"),
        ),
    )

    rooms = (
        RoomProblemRecord(
            room_id="r101",
            room_code="R101",
            room_name="Room 101",
            room_type="standard_classroom",
            capacity=30,
            campus_id="c1",
            specialist_capabilities=tuple(),
            available_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
        ),
        RoomProblemRecord(
            room_id="r102",
            room_code="R102",
            room_name="Room 102",
            room_type="standard_classroom",
            capacity=30,
            campus_id="c1",
            specialist_capabilities=tuple(),
            available_period_keys=tuple(item.key for item in periods),
            unavailable_period_keys=tuple(),
        ),
    )

    requirements = (
        TeachingRequirementRecord(
            requirement_id="req_math_8a",
            class_id="class_8a",
            subject_id="s_math",
            teacher_id=None,
            eligible_teacher_ids=("t1", "t2"),
            weekly_sessions=2,
            weekly_minutes=80,
            periods_per_session=1,
            min_daily_sessions=0,
            max_daily_sessions=2,
            specialist_room_type=None,
            preferred_period_numbers=(2, 3),
            forbidden_period_numbers=tuple(),
            fixed_session_rule_indexes=(0,),
            source_type="manual",
        ),
        TeachingRequirementRecord(
            requirement_id="req_lang_8a",
            class_id="class_8a",
            subject_id="s_lang",
            teacher_id="t3",
            eligible_teacher_ids=("t3",),
            weekly_sessions=1,
            weekly_minutes=40,
            periods_per_session=1,
            min_daily_sessions=0,
            max_daily_sessions=1,
            specialist_room_type=None,
            preferred_period_numbers=(3,),
            forbidden_period_numbers=tuple(),
            fixed_session_rule_indexes=tuple(),
            source_type="manual",
        ),
        TeachingRequirementRecord(
            requirement_id="req_math_8b",
            class_id="class_8b",
            subject_id="s_math",
            teacher_id="t1",
            eligible_teacher_ids=("t1",),
            weekly_sessions=1,
            weekly_minutes=40,
            periods_per_session=1,
            min_daily_sessions=0,
            max_daily_sessions=1,
            specialist_room_type=None,
            preferred_period_numbers=(1,),
            forbidden_period_numbers=tuple(),
            fixed_session_rule_indexes=tuple(),
            source_type="manual",
        ),
    )

    fixed_sessions = (
        FixedSessionRecord(
            fixed_session_id="fx_1",
            requirement_id="req_math_8a",
            class_id="class_8a",
            subject_id="s_math",
            teacher_id="t1",
            room_id="r101",
            day_of_week=0,
            period_number=1,
            period_key="d0:p1",
            enforcement_source="weekly_requirement_fixed_session_rule",
            provenance={"rule": "fixed"},
        ),
    )

    policy_constraints = (
        PolicyConstraintRecord(
            constraint_id="pc_teacher_daily",
            policy_set_id="ps1",
            constraint_type="teacher_max_daily_sessions",
            category="workload",
            enforcement="hard",
            scope_type="teacher",
            scope_reference_id="t1",
            scope_reference_code=None,
            parameters={"max_sessions": 3},
            priority=20,
            weight=1.0,
            lifecycle_status="approved",
            exception_applied=False,
        ),
        PolicyConstraintRecord(
            constraint_id="pc_pref_period",
            policy_set_id="ps1",
            constraint_type="teacher_preferred_period",
            category="teacher",
            enforcement="soft",
            scope_type="teacher",
            scope_reference_id="t1",
            scope_reference_code=None,
            parameters={"weekdays": [1], "period_numbers": [2]},
            priority=100,
            weight=0.5,
            lifecycle_status="approved",
            exception_applied=False,
        ),
    )

    teacher_preferences = (
        TeacherPreferenceRecord(
            preference_id="pref1",
            teacher_id="t1",
            preference_type="avoid_first_period",
            strength="strong",
            weekday_values=tuple(),
            period_numbers=tuple(),
            effective_start_date=None,
            effective_end_date=None,
            source_type="manual",
            provenance={},
        ),
        TeacherPreferenceRecord(
            preference_id="pref2",
            teacher_id="t3",
            preference_type="avoid_selected_periods",
            strength="hard",
            weekday_values=(2,),
            period_numbers=(4,),
            effective_start_date=None,
            effective_end_date=None,
            source_type="manual",
            provenance={},
        ),
    )

    overrides = (
        GenerationOverrideRecord(
            override_id="ov1",
            configuration_id="cfg1",
            override_type="teacher_free_period",
            strength="normal",
            scope_type="teacher",
            scope_reference_id="t1",
            scope_reference_code=None,
            payload={"weekday": 3, "period_number": 4},
            source_type="manual",
            provenance={},
        ),
    )

    locks = (
        LockRecord(
            lock_id="l1",
            configuration_id="cfg1",
            lock_state="flexible",
            target_type="session_reference",
            target_reference_id=None,
            target_reference_code="req_math_8a#occ1",
            day_of_week=0,
            period_number=1,
            period_end_number=1,
            is_manual_hard_lock=False,
            source_type="manual",
            provenance={},
        ),
    )

    parallel_blocks: tuple[ParallelBlockRecord, ...] = tuple()
    if include_parallel:
        parallel_blocks = (
            ParallelBlockRecord(
                block_id="pb_lang",
                class_id="class_8a",
                display_label="Foreign Language",
                block_type="foreign_language",
                synchronization_requirement="same_period",
                active=True,
                source_type="manual",
                provenance={},
                children=(
                    ParallelChildRecord(
                        child_id="pb_child_french",
                        requirement_id="req_lang_8a",
                        subject_id="s_lang",
                        teacher_id="t3",
                        room_id="r101",
                        sequence_order=1,
                        requirement={"track": "French"},
                    ),
                    ParallelChildRecord(
                        child_id="pb_child_german",
                        requirement_id=None,
                        subject_id="s_lang",
                        teacher_id="t1",
                        room_id="r102",
                        sequence_order=2,
                        requirement={"track": "German"},
                    ),
                ),
            ),
        )

    baseline = BaselineSummary(
        supported=with_baseline,
        reason="baseline disabled" if not with_baseline else "synthetic",
        baseline_reference_type="timetable_version" if with_baseline else None,
        baseline_reference_id="base1" if with_baseline else None,
        assignments=(
            {
                "occurrence_id": "req_math_8a#occ1",
                "period_key": "d0:p1",
                "teacher_id": "t1",
                "room_id": "r101",
            },
        )
        if with_baseline
        else tuple(),
    )

    objectives = (
        ObjectiveRecord("teacher_preferences", "high"),
        ObjectiveRecord("subject_distribution", "normal"),
        ObjectiveRecord("workload_balance", "normal"),
        ObjectiveRecord("minimize_teacher_gaps", "normal"),
        ObjectiveRecord("preference_fairness", "low"),
        ObjectiveRecord("minimize_timetable_disruption", "high"),
        ObjectiveRecord("preserve_existing_assignments", "high"),
    )

    validation = ValidationSummary(
        valid=True,
        blocker_count=0,
        warning_count=0,
        excluded_record_count=0,
        blockers=tuple(),
        warnings=tuple(),
        exclusions=tuple(),
        source_summary={"requirements": len(requirements)},
        build_coverage={"logical_periods": len(periods)},
    )

    return SchedulingProblem(
        problem_id="problem_1",
        schema_version="phase_10c_batch2_v1",
        tenant_id="tenant1",
        academic_year_id="y1",
        term_id="t1",
        campus_id="c1",
        generation_configuration_id="cfg1",
        generation_mode="repair" if with_baseline else "standard",
        built_at=datetime.now(UTC),
        source_fingerprint="fingerprint-1",
        source_revision="r1",
        school_week={"id": "sw1", "operational_weekdays": [0, 1, 2, 3, 4]},
        logical_periods=periods,
        bell_schedule_reference={"id": "bell1", "name": "Main"},
        teachers=teachers,
        classes=classes,
        subjects=subjects,
        rooms=rooms,
        teaching_requirements=requirements,
        fixed_sessions=fixed_sessions,
        teacher_availability={item.teacher_id: item.available_period_keys for item in teachers},
        room_availability={item.room_id: item.available_period_keys for item in rooms},
        teacher_eligibility={"s_math": ("t1", "t2"), "s_lang": ("t1", "t3")},
        room_requirements={"req_math_8a": tuple(), "req_lang_8a": tuple(), "req_math_8b": tuple()},
        policy_constraints=policy_constraints,
        teacher_preferences=teacher_preferences,
        generation_overrides=overrides,
        locks=locks,
        parallel_lesson_blocks=parallel_blocks,
        baseline=baseline,
        repair_scope={"scope_level": "minimum"},
        stability_mode=stability_mode,
        optimization_objectives=objectives,
        warnings=tuple(),
        exclusions=tuple(),
        provenance={"policy_readiness_generation_allowed": True},
        validation_summary=validation,
        solver_eligible=solver_eligible,
    )


def with_issue(problem: SchedulingProblem, issue_code: str) -> SchedulingProblem:
    issue = ProblemIssue(code=issue_code, message=issue_code, severity="blocker")
    validation = ValidationSummary(
        valid=False,
        blocker_count=1,
        warning_count=0,
        excluded_record_count=0,
        blockers=(issue,),
        warnings=tuple(),
        exclusions=tuple(),
        source_summary=problem.validation_summary.source_summary,
        build_coverage=problem.validation_summary.build_coverage,
    )
    return replace(problem, validation_summary=validation, solver_eligible=False)
