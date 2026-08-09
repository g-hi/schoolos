from __future__ import annotations

from shared.db.models import Timetable, TimetableGenerationConfiguration, TimetableVersion, TimetableVersionAssignment


def test_timetable_models_are_declared() -> None:
    assert Timetable.__tablename__ == "timetables"
    assert TimetableVersion.__tablename__ == "timetable_versions"
    assert TimetableVersionAssignment.__tablename__ == "timetable_version_assignments"


def test_generation_configuration_has_canonical_baseline_fk_field() -> None:
    columns = TimetableGenerationConfiguration.__table__.c
    assert "baseline_timetable_version_id" in columns


def test_timetable_version_unique_number_per_timetable_constraint_present() -> None:
    names = {item.name for item in TimetableVersion.__table__.constraints}
    assert "uq_timetable_versions_timetable_version_number" in names


def test_timetable_version_assignment_identity_constraint_present() -> None:
    names = {item.name for item in TimetableVersionAssignment.__table__.constraints}
    assert "uq_timetable_version_assignments_version_assignment_key" in names
