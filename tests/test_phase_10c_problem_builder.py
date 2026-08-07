from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from services.gateway.timetable_setup.problem_builder import _build_from_sources


def _uid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"phase10c:{name}")


def _base_configuration(*, mode: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=_uid("config"),
        tenant_id=_uid("tenant"),
        academic_year_id=_uid("year"),
        term_id=_uid("term"),
        campus_id=_uid("campus"),
        generation_mode=mode,
        stability_mode="balanced",
        baseline_reference_type="timetable_version" if mode == "repair" else None,
        baseline_reference_id=_uid("baseline") if mode == "repair" else None,
        lifecycle_status="approved",
        repair_scope_json={"scope_level": "minimum"},
        validation_summary_json={"is_valid": True},
    )


def _base_rows() -> dict[str, object]:
    teacher_id = _uid("teacher")
    user_id = _uid("user")
    class_id = _uid("class")
    subject_id = _uid("subject")
    room_id = _uid("room")
    requirement_id = _uid("requirement")
    block_id = _uid("block")

    return {
        "school_week": SimpleNamespace(id=_uid("week"), name="Week", operational_weekdays=[0, 1, 2, 3, 4]),
        "bell_schedule": SimpleNamespace(id=_uid("bell"), name="Main", schedule_type="normal"),
        "bell_periods": [
            SimpleNamespace(id=_uid("period1"), period_number=1, label="P1", start_time="08:00", end_time="08:40", is_teaching_period=True),
            SimpleNamespace(id=_uid("period2"), period_number=2, label="P2", start_time="08:45", end_time="09:25", is_teaching_period=True),
        ],
        "teachers": [SimpleNamespace(id=teacher_id, user_id=user_id, max_weekly_hours=20)],
        "users": [SimpleNamespace(id=user_id, is_active=True)],
        "teacher_subjects": [SimpleNamespace(teacher_id=teacher_id, subject_id=subject_id)],
        "classes": [
            SimpleNamespace(
                id=class_id,
                is_active=True,
                code="8A",
                grade_level_id=_uid("grade"),
                grade="Grade 8",
                campus_id=_uid("campus"),
            )
        ],
        "subjects": [SimpleNamespace(id=subject_id, code="FR", name="French")],
        "rooms": [
            SimpleNamespace(
                id=room_id,
                room_code="R101",
                room_name="Room 101",
                room_type="standard_classroom",
                capacity=30,
                campus_id=_uid("campus"),
                specialist_capabilities=["audio"],
            )
        ],
        "requirements": [
            SimpleNamespace(
                id=requirement_id,
                class_id=class_id,
                subject_id=subject_id,
                teacher_id=teacher_id,
                sessions_per_week=3,
                periods_per_session=1,
                min_daily_sessions=0,
                max_daily_sessions=2,
                specialist_room_type=None,
                preferred_period_numbers=[1],
                forbidden_period_numbers=[],
                has_fixed_sessions=True,
                fixed_session_rules=[{"day_of_week": 0, "period_number": 1, "room_id": str(room_id)}],
                source_type="manual",
            )
        ],
        "assignments": [SimpleNamespace(id=_uid("assignment"), teacher_id=teacher_id)],
        "preferences": [
            SimpleNamespace(
                id=_uid("preference"),
                teacher_id=teacher_id,
                preference_type="avoid_selected_periods",
                strength="strong",
                weekdays_json=[0],
                period_numbers_json=[2],
                effective_start_date=None,
                effective_end_date=None,
                source_type="manual",
                provenance_json={"source": "principal"},
            )
        ],
        "overrides": [
            SimpleNamespace(
                id=_uid("override"),
                configuration_id=_uid("config"),
                override_type="teacher_free_period",
                strength="normal",
                scope_type="teacher",
                scope_reference_id=teacher_id,
                scope_reference_code=None,
                payload_json={"period_number": 2},
                source_type="manual",
                provenance_json={},
            )
        ],
        "locks": [
            SimpleNamespace(
                id=_uid("lock"),
                configuration_id=_uid("config"),
                lock_state="locked",
                target_type="teacher",
                target_reference_id=teacher_id,
                target_reference_code=None,
                day_of_week=0,
                period_number=1,
                period_end_number=1,
                is_manual_hard_lock=True,
                source_type="manual",
                provenance_json={"origin": "principal"},
            )
        ],
        "objectives": [],
        "parallel_blocks": [
            SimpleNamespace(
                id=block_id,
                class_id=class_id,
                display_label="Foreign Language",
                block_type="foreign_language",
                synchronization_requirement="same_period",
                is_active=True,
                source_type="manual",
                provenance_json={"example": True},
            )
        ],
        "parallel_children": [
            SimpleNamespace(
                id=_uid("child-french"),
                parallel_block_id=block_id,
                requirement_id=requirement_id,
                subject_id=subject_id,
                teacher_id=teacher_id,
                room_id=room_id,
                sequence_order=1,
                requirement_json={"language": "French"},
            ),
            SimpleNamespace(
                id=_uid("child-german"),
                parallel_block_id=block_id,
                requirement_id=None,
                subject_id=subject_id,
                teacher_id=teacher_id,
                room_id=room_id,
                sequence_order=2,
                requirement_json={"language": "German"},
            ),
            SimpleNamespace(
                id=_uid("child-spanish"),
                parallel_block_id=block_id,
                requirement_id=None,
                subject_id=subject_id,
                teacher_id=teacher_id,
                room_id=room_id,
                sequence_order=3,
                requirement_json={"language": "Spanish"},
            ),
        ],
        "policy_constraints": [],
    }


def _policy_payload(*, generation_allowed: bool = True) -> dict[str, object]:
    return {
        "generation_allowed": generation_allowed,
        "effective_constraints": [
            {
                "id": str(_uid("constraint-1")),
                "policy_set_id": str(_uid("policy-set")),
                "type": "teacher_max_daily_sessions",
                "category": "workload",
                "enforcement_level": "hard",
                "scope_type": "teacher",
                "scope_reference_id": str(_uid("teacher")),
                "scope_reference_code": None,
                "parameters": {"max_sessions": 4},
                "priority": 20,
                "weight": 1.0,
                "lifecycle_status": "approved",
                "selected": True,
            }
        ],
    }


def test_problem_builder_deterministic_and_immutable() -> None:
    configuration = _base_configuration()
    rows = _base_rows()
    policy_payload = _policy_payload(generation_allowed=True)

    one = _build_from_sources(configuration=configuration, rows=rows, policy_payload=policy_payload)
    two = _build_from_sources(configuration=configuration, rows=rows, policy_payload=policy_payload)

    assert one.problem.source_fingerprint == two.problem.source_fingerprint
    assert one.problem.problem_id == two.problem.problem_id
    assert one.problem.solver_eligible is True
    assert one.problem.parallel_lesson_blocks[0].display_label == "Foreign Language"

    with pytest.raises(FrozenInstanceError):
        one.problem.generation_mode = "repair"


def test_problem_builder_excludes_students_and_keeps_logical_identity() -> None:
    configuration = _base_configuration()
    rows = _base_rows()
    policy_payload = _policy_payload(generation_allowed=True)

    baseline = _build_from_sources(configuration=configuration, rows=rows, policy_payload=policy_payload)
    keys = tuple(item.key for item in baseline.problem.logical_periods)

    rows_changed_times = _base_rows()
    rows_changed_times["bell_periods"] = [
        SimpleNamespace(id=_uid("period1"), period_number=1, label="P1", start_time="09:00", end_time="09:40", is_teaching_period=True),
        SimpleNamespace(id=_uid("period2"), period_number=2, label="P2", start_time="09:45", end_time="10:25", is_teaching_period=True),
    ]
    changed = _build_from_sources(configuration=configuration, rows=rows_changed_times, policy_payload=policy_payload)

    assert keys == tuple(item.key for item in changed.problem.logical_periods)
    problem_dict = baseline.problem.to_dict()
    assert "students" not in problem_dict
