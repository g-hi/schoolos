from __future__ import annotations

import uuid
from types import SimpleNamespace

from services.gateway.timetable_setup.problem_builder import _build_from_sources

from tests.test_phase_10c_problem_builder import _base_configuration, _base_rows, _policy_payload


def test_problem_builder_policy_gate_blocker_disables_solver_eligibility() -> None:
    result = _build_from_sources(
        configuration=_base_configuration(),
        rows=_base_rows(),
        policy_payload=_policy_payload(generation_allowed=False),
    )

    assert result.validation.valid is False
    assert result.problem.solver_eligible is False
    assert any(item.code == "phase_10b_generation_blocked" for item in result.validation.blockers)


def test_problem_builder_repair_baseline_is_controlled_unsupported_state() -> None:
    result = _build_from_sources(
        configuration=_base_configuration(mode="repair"),
        rows=_base_rows(),
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert result.problem.baseline.supported is False
    assert result.problem.baseline.assignments == tuple()
    assert any(item.code == "repair_baseline_not_found" for item in result.validation.blockers)


def test_problem_builder_rejects_invalid_lock_target() -> None:
    rows = _base_rows()
    rows["locks"] = [
        SimpleNamespace(
            id=rows["locks"][0].id,
            configuration_id=rows["locks"][0].configuration_id,
            lock_state="locked",
            target_type="department",
            target_reference_id=None,
            target_reference_code="science",
            day_of_week=0,
            period_number=1,
            period_end_number=1,
            is_manual_hard_lock=True,
            source_type="manual",
            provenance_json={},
        )
    ]

    result = _build_from_sources(
        configuration=_base_configuration(),
        rows=rows,
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert result.problem.solver_eligible is False
    assert any(item.code == "invalid_lock_target" for item in result.validation.blockers)


def test_problem_builder_blocks_invalid_hard_preference_period() -> None:
    rows = _base_rows()
    rows["preferences"][0].strength = "hard"
    rows["preferences"][0].period_numbers_json = [99]

    result = _build_from_sources(
        configuration=_base_configuration(),
        rows=rows,
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert any(item.code == "hard_preference_invalid_period" for item in result.validation.blockers)


def test_problem_builder_repair_baseline_supported_when_canonical_version_present() -> None:
    configuration = _base_configuration(mode="repair")
    configuration.baseline_timetable_version_id = uuid.uuid4()

    rows = _base_rows()
    rows["baseline_version"] = SimpleNamespace(
        id=configuration.baseline_timetable_version_id,
        tenant_id=configuration.tenant_id,
        generation_mode="repair",
        lifecycle_status="published",
        timetable_id=uuid.uuid4(),
    )
    rows["baseline_assignments"] = [
        SimpleNamespace(
            assignment_key="req_math_8a#occ1|",
            occurrence_id="req_math_8a#occ1",
            requirement_id="req_math_8a",
            class_id=str(rows["classes"][0].id),
            subject_id=str(rows["subjects"][0].id),
            teacher_id=str(rows["teachers"][0].id),
            room_id=str(rows["rooms"][0].id),
            day_key="d0",
            period_key="d0:p1",
            periods_per_session=1,
            occupied_period_keys_json=["d0:p1"],
            parallel_block_id=str(rows["parallel_blocks"][0].id),
            parallel_child_id=str(rows["parallel_children"][0].id),
            fixed=True,
            lock_state="locked",
            timetable_version_id=configuration.baseline_timetable_version_id,
        )
    ]

    result = _build_from_sources(
        configuration=configuration,
        rows=rows,
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert result.problem.baseline.supported is True
    assert len(result.problem.baseline.assignments) == 1
    assert result.problem.solver_eligible is True
    assert not any(item.code.startswith("repair_baseline_") for item in result.validation.blockers)


def test_problem_builder_repair_baseline_rejects_cross_tenant_version() -> None:
    configuration = _base_configuration(mode="repair")
    configuration.baseline_timetable_version_id = uuid.uuid4()

    rows = _base_rows()
    rows["baseline_version"] = SimpleNamespace(
        id=configuration.baseline_timetable_version_id,
        tenant_id=uuid.uuid4(),
        generation_mode="repair",
        lifecycle_status="published",
        timetable_id=uuid.uuid4(),
    )
    rows["baseline_assignments"] = []

    result = _build_from_sources(
        configuration=configuration,
        rows=rows,
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert any(item.code == "repair_baseline_cross_tenant" for item in result.validation.blockers)


def test_problem_builder_repair_baseline_rejects_invalid_version_status() -> None:
    configuration = _base_configuration(mode="repair")
    configuration.baseline_timetable_version_id = uuid.uuid4()

    rows = _base_rows()
    rows["baseline_version"] = SimpleNamespace(
        id=configuration.baseline_timetable_version_id,
        tenant_id=configuration.tenant_id,
        generation_mode="repair",
        lifecycle_status="candidate",
        timetable_id=uuid.uuid4(),
    )
    rows["baseline_assignments"] = []

    result = _build_from_sources(
        configuration=configuration,
        rows=rows,
        policy_payload=_policy_payload(generation_allowed=True),
    )

    assert any(item.code == "repair_baseline_invalid_status" for item in result.validation.blockers)
