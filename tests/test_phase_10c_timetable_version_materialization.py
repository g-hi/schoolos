from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_generation as tg
from services.gateway.timetable_setup import timetable_versions as tv
from services.gateway.timetable_setup.timetable_versions import TimetableVersionError


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_materialization_rejects_stale_candidate_preview() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(
            tg,
            "materialize_candidate_version",
            new=AsyncMock(
                side_effect=TimetableVersionError(
                    code="stale_candidate_preview",
                    message="Scheduling problem changed since candidate preview.",
                    status_code=409,
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await tg.materialize_timetable_version_from_candidate(
                configuration_id=uuid.uuid4(),
                body=tg.MaterializeCandidateVersionRequest(
                    candidate_id="cand_1",
                    expected_problem_fingerprint="fp_old",
                ),
                tenant=tenant,
                actor=actor,
                db=db,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "stale_candidate_preview"


@pytest.mark.asyncio
async def test_materialization_rejects_preview_after_canonical_input_changes() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    preview_problem = SimpleNamespace(source_fingerprint="fp_preview")
    current_problem = SimpleNamespace(source_fingerprint="fp_current")
    preview_build = SimpleNamespace(problem=preview_problem)
    current_build = SimpleNamespace(problem=current_problem)

    config = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        baseline_timetable_version_id=None,
        baseline_reference_id=None,
        baseline_reference_type=None,
    )

    candidate = SimpleNamespace(
        candidate_id="cand_1",
        problem_id="problem_1",
        problem_fingerprint=current_problem.source_fingerprint,
        generation_configuration_id=str(config.id),
        generation_mode="standard",
        candidate_profile="configured",
        assignment_fingerprint="af1",
        solver_status="feasible",
        feasible=True,
        optimal=False,
        assignments=(),
        class_facing_assignments=(),
        metrics={},
        quality_score=0.9,
        quality_band="good",
        quality_components=(),
        preference_summary={},
        fairness_summary={},
        workload_summary={},
        gap_summary={},
        subject_distribution_summary={},
        room_summary={},
        repair_impact_summary={},
        hard_constraint_summary={},
        diagnostics=(),
        explanation_facts=(),
        warnings=(),
        solver_runtime_ms=0,
        solver_statistics={},
        provenance={},
    )
    generated = SimpleNamespace(candidates=(candidate,))

    with (
        patch.object(tv, "_get_configuration", new=AsyncMock(return_value=config)),
        patch.object(tv, "build_scheduling_problem", new=AsyncMock(return_value=current_build)),
        patch.object(tv, "generate_timetable_candidates", new=AsyncMock(return_value=generated)),
    ):
        with pytest.raises(TimetableVersionError) as exc:
            await tv.materialize_candidate_version(
                db,
                tenant_id=tenant.id,
                actor=actor,
                configuration_id=config.id,
                candidate_id="cand_1",
                expected_problem_fingerprint=preview_build.problem.source_fingerprint,
            )

    assert exc.value.code == "stale_candidate_preview"
    assert exc.value.details["expected_problem_fingerprint"] == "fp_preview"
    assert exc.value.details["actual_problem_fingerprint"] == "fp_current"


@pytest.mark.asyncio
async def test_materialization_response_has_no_publication_side_effect() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    timetable = SimpleNamespace(
        id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=None,
        name="Term 1 timetable",
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        timetable_id=timetable.id,
        tenant_id=tenant.id,
        version_number=1,
        generation_configuration_id=uuid.uuid4(),
        source_candidate_id="cand_1",
        source_problem_id="problem_1",
        source_problem_fingerprint="fp1",
        source_assignment_fingerprint="af1",
        generation_mode="standard",
        baseline_version_id=None,
        lifecycle_status="candidate",
        effective_from=None,
        effective_until=None,
        submitted_at=None,
        approved_at=None,
        published_at=None,
        superseded_at=None,
        superseded_by_version_id=None,
        candidate_profile="configured",
        quality_snapshot_json={},
        repair_impact_snapshot_json={},
        diff_summary_snapshot_json={},
        solver_provenance_json={},
        created_at=None,
        created_by_user_id=actor.id,
    )
    materialized = SimpleNamespace(timetable=timetable, version=version, assignment_count=4)

    with (
        patch.object(tg, "set_tenant_context", new=AsyncMock()),
        patch.object(tg, "materialize_candidate_version", new=AsyncMock(return_value=materialized)),
        patch.object(tg, "log_action", new=AsyncMock()),
    ):
        payload = await tg.materialize_timetable_version_from_candidate(
            configuration_id=uuid.uuid4(),
            body=tg.MaterializeCandidateVersionRequest(
                candidate_id="cand_1",
                expected_problem_fingerprint="fp1",
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert payload["version"]["assignment_count"] == 4
    assert payload["explicit_non_actions"]["published"] is False
    assert payload["explicit_non_actions"]["notifications_sent"] is False
