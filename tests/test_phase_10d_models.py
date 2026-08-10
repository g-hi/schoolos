from __future__ import annotations

from shared.db.models import DailySession, OperationalSchoolDay


def test_operational_school_day_model_is_declared() -> None:
    assert OperationalSchoolDay.__tablename__ == "operational_school_days"


def test_daily_session_model_is_declared() -> None:
    assert DailySession.__tablename__ == "daily_sessions"


def test_operational_school_day_unique_version_date_constraint_present() -> None:
    names = {item.name for item in OperationalSchoolDay.__table__.constraints}
    assert any("timetable_date" in (n or "") for n in names), "Expected uq on (timetable_id, school_date)"


def test_daily_session_unique_osd_session_key_constraint_present() -> None:
    names = {item.name for item in DailySession.__table__.constraints}
    assert "uq_daily_sessions_osd_session_key" in names


def test_operational_school_day_has_expected_columns() -> None:
    cols = {c.name for c in OperationalSchoolDay.__table__.columns}
    for expected in (
        "id",
        "tenant_id",
        "timetable_id",
        "timetable_version_id",
        "campus_id",
        "school_date",
        "day_of_week",
        "timetable_day_key",
        "bell_schedule_id",
        "is_teaching_day",
        "non_teaching_reason",
        "calendar_override_event_id",
        "calendar_event_version_id",
        "materialization_status",
        "materialized_at",
        "source_fingerprint",
        "is_active",
        "created_at",
        "updated_at",
    ):
        assert expected in cols, f"Missing column: {expected}"


def test_daily_session_has_expected_columns() -> None:
    cols = {c.name for c in DailySession.__table__.columns}
    for expected in (
        "id",
        "tenant_id",
        "operational_school_day_id",
        "timetable_version_assignment_id",
        "school_date",
        "class_id",
        "subject_id",
        "teacher_id",
        "room_id",
        "bell_period_id",
        "period_number",
        "period_start_time",
        "period_end_time",
        "periods_span",
        "parallel_block_id",
        "parallel_child_id",
        "session_key",
        "class_facing_session_key",
        "session_status",
        "override_reason",
        "is_active",
        "created_at",
    ):
        assert expected in cols, f"Missing column: {expected}"


def test_daily_session_period_number_positive_constraint_present() -> None:
    names = {item.name for item in DailySession.__table__.constraints}
    assert any("period_number_positive" in (n or "") for n in names)


def test_operational_school_day_materialization_status_check_constraint_present() -> None:
    names = {item.name for item in OperationalSchoolDay.__table__.constraints}
    assert any("mat_status" in (n or "") for n in names)
