from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=is_active)


def _config(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        generation_mode="standard",
        stability_mode="balanced",
        lifecycle_status="approved",
        repair_scope_json={"scope_level": "minimum"},
    )


@pytest.mark.asyncio
async def test_candidate_preview_route_returns_summary_mode_without_persistence_flags() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    config = _config(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=config)

    fake_problem = SimpleNamespace(problem_id="p1", source_fingerprint="f1", solver_eligible=True, to_dict=lambda: {"problem_id": "p1"})
    fake_result = SimpleNamespace(problem=fake_problem)

    fake_candidate_result = SimpleNamespace(
        generated_count=1,
        to_dict=lambda: {
            "problem_id": "p1",
            "problem_fingerprint": "f1",
            "requested_count": 1,
            "generated_count": 1,
            "candidates": [
                {
                    "candidate_id": "cand_1",
                    "candidate_profile": "configured",
                    "feasible": True,
                    "optimal": False,
                    "solver_status": "feasible",
                    "quality_score": 0.9,
                    "quality_band": "excellent",
                    "solver_runtime_ms": 10,
                    "assignment_fingerprint": "af1",
                    "preference_summary": {},
                    "fairness_summary": {},
                    "workload_summary": {},
                    "gap_summary": {},
                    "subject_distribution_summary": {},
                    "room_summary": {},
                    "repair_impact_summary": {},
                    "diagnostics": [],
                    "warnings": [],
                    "assignments": [{"x": 1}],
                    "class_facing_assignments": [{"y": 1}],
                    "quality_components": [{"k": 1}],
                    "explanation_facts": [{"r": 1}],
                }
            ],
            "comparison": None,
            "attempts": [],
            "warnings": [],
            "diagnostics": [],
            "duration_ms": 10,
            "deterministic": True,
            "provenance": {},
        },
    )

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(tg, "_run_generation_validation", new=AsyncMock(return_value={"is_valid": True, "policy_generation_allowed": True})),
        patch.object(tg, "build_scheduling_problem", new=AsyncMock(return_value=fake_result)),
        patch.object(tg, "summarize_problem", return_value={"counts": {}, "blockers": [], "warnings": []}),
        patch.object(tg, "generate_timetable_candidates", return_value=fake_candidate_result),
    ):
        payload = await tg.preview_timetable_candidates(
            configuration_id=config.id,
            body=tg.CandidatePreviewRequest(candidate_count=1, response_mode="summary"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["candidate_result"]["generated_count"] == 1
    assert "assignments" not in payload["candidate_result"]["candidates"][0]
    assert payload["explicit_non_actions"]["candidate_persisted"] is False
    assert payload["explicit_non_actions"]["timetable_version_created"] is False
    assert payload["explicit_non_actions"]["notifications_sent"] is False


@pytest.mark.asyncio
async def test_candidate_preview_route_blocks_when_solver_not_eligible() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    config = _config(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=config)

    fake_problem = SimpleNamespace(problem_id="p1", source_fingerprint="f1", solver_eligible=False)
    fake_result = SimpleNamespace(problem=fake_problem)

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(tg, "_run_generation_validation", new=AsyncMock(return_value={"is_valid": False, "policy_generation_allowed": False})),
        patch.object(tg, "build_scheduling_problem", new=AsyncMock(return_value=fake_result)),
        patch.object(tg, "summarize_problem", return_value={"counts": {}, "blockers": [{"code": "x"}], "warnings": []}),
    ):
        payload = await tg.preview_timetable_candidates(
            configuration_id=config.id,
            body=tg.CandidatePreviewRequest(candidate_count=2),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["candidate_result"]["generated_count"] == 0
    assert payload["candidate_result"]["diagnostics"][0]["code"] == "solver_eligibility_blocked"


@pytest.mark.asyncio
async def test_candidate_preview_route_rejects_inactive_actor() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, is_active=False)
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        await tg.preview_timetable_candidates(
            configuration_id=uuid.uuid4(),
            body=tg.CandidatePreviewRequest(candidate_count=1),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_candidate_preview_route_detailed_mode_keeps_assignments() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    config = _config(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=config)

    fake_problem = SimpleNamespace(problem_id="p1", source_fingerprint="f1", solver_eligible=True, to_dict=lambda: {"problem_id": "p1"})
    fake_result = SimpleNamespace(problem=fake_problem)

    fake_candidate_result = SimpleNamespace(
        generated_count=1,
        to_dict=lambda: {
            "problem_id": "p1",
            "problem_fingerprint": "f1",
            "requested_count": 1,
            "generated_count": 1,
            "candidates": [
                {
                    "candidate_id": "cand_1",
                    "candidate_profile": "configured",
                    "feasible": True,
                    "optimal": False,
                    "solver_status": "feasible",
                    "quality_score": 0.9,
                    "quality_band": "excellent",
                    "solver_runtime_ms": 10,
                    "assignment_fingerprint": "af1",
                    "assignments": [{"x": 1}],
                    "class_facing_assignments": [{"y": 1}],
                    "quality_components": [{"k": 1}],
                    "explanation_facts": [{"r": 1}],
                    "preference_summary": {},
                    "fairness_summary": {},
                    "workload_summary": {},
                    "gap_summary": {},
                    "subject_distribution_summary": {},
                    "room_summary": {},
                    "repair_impact_summary": {},
                    "diagnostics": [],
                    "warnings": [],
                }
            ],
            "comparison": None,
            "attempts": [],
            "warnings": [],
            "diagnostics": [],
            "duration_ms": 10,
            "deterministic": True,
            "provenance": {},
        },
    )

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(tg, "_run_generation_validation", new=AsyncMock(return_value={"is_valid": True, "policy_generation_allowed": True})),
        patch.object(tg, "build_scheduling_problem", new=AsyncMock(return_value=fake_result)),
        patch.object(tg, "summarize_problem", return_value={"counts": {}, "blockers": [], "warnings": []}),
        patch.object(tg, "generate_timetable_candidates", return_value=fake_candidate_result),
    ):
        payload = await tg.preview_timetable_candidates(
            configuration_id=config.id,
            body=tg.CandidatePreviewRequest(candidate_count=1, response_mode="detailed"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["candidate_result"]["generated_count"] == 1
    assert "assignments" in payload["candidate_result"]["candidates"][0]


def test_candidate_route_rejects_cross_tenant_actor() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=uuid.uuid4(), is_active=True)

    with pytest.raises(HTTPException) as exc:
        tg._ensure_actor_tenant(actor, tenant)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_repeated_preview_does_not_mutate_problem_payload() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()
    config = _config(tenant_id=tenant.id)
    db.scalar = AsyncMock(return_value=config)

    baseline_problem_payload = {"problem_id": "p1", "fingerprint": "f1"}
    fake_problem = SimpleNamespace(
        problem_id="p1",
        source_fingerprint="f1",
        solver_eligible=True,
        to_dict=lambda: dict(baseline_problem_payload),
    )
    fake_result = SimpleNamespace(problem=fake_problem)

    fake_candidate_result = SimpleNamespace(
        generated_count=1,
        to_dict=lambda: {
            "problem_id": "p1",
            "problem_fingerprint": "f1",
            "requested_count": 1,
            "generated_count": 1,
            "candidates": [],
            "comparison": None,
            "attempts": [],
            "warnings": [],
            "diagnostics": [],
            "duration_ms": 0,
            "deterministic": True,
            "provenance": {},
        },
    )

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(tg, "_run_generation_validation", new=AsyncMock(return_value={"is_valid": True, "policy_generation_allowed": True})),
        patch.object(tg, "build_scheduling_problem", new=AsyncMock(return_value=fake_result)),
        patch.object(tg, "summarize_problem", return_value={"counts": {}, "blockers": [], "warnings": []}),
        patch.object(tg, "generate_timetable_candidates", return_value=fake_candidate_result),
    ):
        _ = await tg.preview_timetable_candidates(
            configuration_id=config.id,
            body=tg.CandidatePreviewRequest(candidate_count=1, response_mode="summary"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        _ = await tg.preview_timetable_candidates(
            configuration_id=config.id,
            body=tg.CandidatePreviewRequest(candidate_count=1, response_mode="summary"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert fake_problem.to_dict() == baseline_problem_payload
