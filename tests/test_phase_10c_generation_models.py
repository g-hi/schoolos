from __future__ import annotations

from shared.db.models import (
    TimetableGenerationConfiguration,
    TimetableGenerationLock,
    TimetableGenerationObjective,
    TimetableGenerationOverride,
    TimetableParallelLessonBlock,
    TimetableParallelLessonChild,
    TimetableTeacherSchedulingPreference,
)


def test_phase_10c_models_have_expected_table_names() -> None:
    assert TimetableGenerationConfiguration.__tablename__ == "timetable_generation_configurations"
    assert TimetableGenerationObjective.__tablename__ == "timetable_generation_objectives"
    assert TimetableTeacherSchedulingPreference.__tablename__ == "timetable_teacher_scheduling_preferences"
    assert TimetableGenerationOverride.__tablename__ == "timetable_generation_overrides"
    assert TimetableGenerationLock.__tablename__ == "timetable_generation_locks"
    assert TimetableParallelLessonBlock.__tablename__ == "timetable_parallel_lesson_blocks"
    assert TimetableParallelLessonChild.__tablename__ == "timetable_parallel_lesson_children"


def test_phase_10c_configuration_has_expected_columns() -> None:
    cols = TimetableGenerationConfiguration.__table__.columns
    assert "generation_mode" in cols
    assert "stability_mode" in cols
    assert "lifecycle_status" in cols
    assert "baseline_reference_id" in cols
    assert "bell_schedule_id" in cols
    assert "objective_priorities_json" in cols
    assert "repair_scope_json" in cols


def test_phase_10c_preferences_locks_parallel_columns() -> None:
    pref_cols = TimetableTeacherSchedulingPreference.__table__.columns
    assert "preference_type" in pref_cols
    assert "strength" in pref_cols
    assert "weekdays_json" in pref_cols
    assert "period_numbers_json" in pref_cols

    lock_cols = TimetableGenerationLock.__table__.columns
    assert "lock_state" in lock_cols
    assert "target_type" in lock_cols
    assert "is_manual_hard_lock" in lock_cols

    block_cols = TimetableParallelLessonBlock.__table__.columns
    assert "display_label" in block_cols
    assert "block_type" in block_cols

    child_cols = TimetableParallelLessonChild.__table__.columns
    assert "subject_id" in child_cols
    assert "teacher_id" in child_cols
    assert "requirement_id" in child_cols


def test_phase_10c_no_student_membership_in_parallel_block_scope() -> None:
    child_cols = TimetableParallelLessonChild.__table__.columns
    assert "student_id" not in child_cols


def test_phase_10c_department_lock_target_is_not_supported() -> None:
    sqltexts = [str(getattr(constraint, "sqltext", "")) for constraint in TimetableGenerationLock.__table__.constraints]
    target_checks = [text for text in sqltexts if "target_type" in text]
    assert target_checks
    assert all("department" not in text for text in target_checks)
