from __future__ import annotations

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
    assert any(item.code == "repair_baseline_not_supported" for item in result.validation.blockers)


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
