from __future__ import annotations

from services.gateway.routers.timetable_setup_imports import _detect_entity, _propose_column_mappings


def test_sheet_alias_detection_and_low_confidence_path() -> None:
    entity, confidence, reason = _detect_entity("Teaching Staff", ["Employee ID", "Teacher Name", "Department"])
    assert entity == "teachers"
    assert confidence >= 0.9
    assert "alias" in reason

    unknown_entity, low_confidence, _ = _detect_entity("Random Sheet", ["A", "B", "C"])
    assert unknown_entity is None
    assert low_confidence == 0.0


def test_required_unmapped_fields_block_validation_ready_state() -> None:
    mappings, required_unmapped = _propose_column_mappings(
        "teaching_requirements",
        ["Class", "Subject", "Lessons Per Week"],
        [{"Class": "10A", "Subject": "MATH", "Lessons Per Week": "5"}],
    )
    mapped_targets = {item["target_field"] for item in mappings if item.get("target_field")}
    assert "class_code" in mapped_targets
    assert "subject_code" in mapped_targets
    assert "sessions_per_week" in mapped_targets
    assert "academic_year" in required_unmapped
    assert "term" in required_unmapped


def test_mapping_samples_are_limited_and_explainable() -> None:
    mappings, _ = _propose_column_mappings(
        "teachers",
        ["Teacher Name", "Employee ID", "Email"],
        [
            {"Teacher Name": "Ada", "Employee ID": "T1", "Email": "a@example.test"},
            {"Teacher Name": "Ben", "Employee ID": "T2", "Email": "b@example.test"},
            {"Teacher Name": "Cia", "Employee ID": "T3", "Email": "c@example.test"},
            {"Teacher Name": "Dan", "Employee ID": "T4", "Email": "d@example.test"},
        ],
    )
    employee = [item for item in mappings if item["source_column"] == "Employee ID"][0]
    assert employee["target_field"] == "teacher_id"
    assert employee["reason"]
    assert len(employee["sample_values"]) <= 3
