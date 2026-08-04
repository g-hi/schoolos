from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from services.gateway.main import app
from services.gateway.routers import onboarding
from shared.auth.jwt import create_access_token, get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import SchoolOnboardingRun, SchoolOnboardingStep


REQUIRED_ONBOARDING_ROUTES = {
    ("GET", "/leadership/onboarding/status"),
    ("GET", "/leadership/onboarding/readiness"),
    ("GET", "/leadership/onboarding/history"),
    ("POST", "/leadership/onboarding/start"),
    ("PATCH", "/leadership/onboarding/current-step"),
    ("POST", "/leadership/onboarding/steps/{step_key}/acknowledge"),
    ("POST", "/leadership/onboarding/steps/{step_key}/skip"),
    ("POST", "/leadership/onboarding/pause"),
    ("POST", "/leadership/onboarding/resume"),
    ("POST", "/leadership/onboarding/complete"),
    ("POST", "/leadership/onboarding/cancel"),
}

EXPECTED_STEP_CATALOGUE = [
    "campus",
    "academic_year",
    "terms",
    "grade_levels",
    "subjects",
    "classes",
    "subject_offerings",
    "people",
    "family_relationships",
    "teacher_assignments",
    "student_enrolments",
    "timetable",
    "data_imports",
    "readiness_review",
]


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _StatefulDb(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.execute = AsyncMock(return_value=_Result(rows=[]))
        self.scalar = AsyncMock(return_value=None)


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _user(*, tenant_id: uuid.UUID, role: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True, name=role, email=f"{role}@example.test")


def _headers(user: SimpleNamespace, tenant_slug: str) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=user.role, tenant_slug=tenant_slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": tenant_slug}


def _client(db: AsyncMock, tenant: SimpleNamespace, user: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.asyncio
async def test_start_creates_fixed_step_catalogue() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=None)
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"ok": True})
    ):
        result = await onboarding.start_onboarding(tenant=tenant, actor=actor, db=db)

    assert result == {"ok": True}
    added = [call.args[0] for call in db.add.call_args_list]
    runs = [item for item in added if isinstance(item, SchoolOnboardingRun)]
    steps = [item for item in added if isinstance(item, SchoolOnboardingStep)]
    assert len(runs) == 1
    assert len(steps) == len(onboarding.STEP_CATALOGUE)
    assert [step.step_key for step in steps] == onboarding.STEP_CATALOGUE


@pytest.mark.asyncio
async def test_duplicate_active_run_rejected() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="school_admin")
    db = _StatefulDb()
    active = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="campus",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=active)
    ):
        with pytest.raises(HTTPException) as exc:
            await onboarding.start_onboarding(tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_completed_historical_run_does_not_block_new_start() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=None)
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"run_status": "in_progress"})
    ):
        result = await onboarding.start_onboarding(tenant=tenant, actor=actor, db=db)

    assert result["run_status"] == "in_progress"


@pytest.mark.asyncio
async def test_current_step_update_and_invalid_step_rejected() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="campus",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"current_step": "people"})
    ):
        payload = await onboarding.update_current_step(
            body=onboarding.CurrentStepUpdateRequest(step_key="people"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert payload["current_step"] == "people"
    assert run.current_step_key == "people"

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await onboarding.update_current_step(
                body=onboarding.CurrentStepUpdateRequest(step_key="unknown_step"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_completed_and_cancelled_runs_are_immutable() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="completed",
        current_step_key="readiness_review",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        completed_by_user_id=actor.id,
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ):
        with pytest.raises(HTTPException) as completed_exc:
            await onboarding.update_current_step(
                body=onboarding.CurrentStepUpdateRequest(step_key="people"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert completed_exc.value.status_code == 409

    run.status = "cancelled"
    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ):
        with pytest.raises(HTTPException) as cancelled_exc:
            await onboarding.pause_onboarding(tenant=tenant, actor=actor, db=db)
    assert cancelled_exc.value.status_code == 409


@pytest.mark.asyncio
async def test_pause_resume_and_cancel_preserve_history() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="school_admin")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="classes",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"run_status": "paused"})
    ):
        await onboarding.pause_onboarding(tenant=tenant, actor=actor, db=db)
    assert run.status == "paused"

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"blocker_count": 0, "warning_count": 1})), patch(
        "services.gateway.routers.onboarding.log_action", new=AsyncMock()
    ), patch("services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"run_status": "ready"})):
        await onboarding.resume_onboarding(tenant=tenant, actor=actor, db=db)
    assert run.status == "ready"

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"blocker_count": 0, "warning_count": 0})), patch(
        "services.gateway.routers.onboarding.log_action", new=AsyncMock()
    ):
        result = await onboarding.cancel_onboarding(tenant=tenant, actor=actor, db=db)
    assert result["status"] == "cancelled"
    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_acknowledge_and_skip_rules_and_safe_metadata() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="data_imports",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )
    step = SchoolOnboardingStep(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        onboarding_run_id=run.id,
        step_key="data_imports",
        status="in_progress",
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(return_value=step)), patch(
        "services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"step_statuses": {"data_imports": "in_progress"}, "blocker_count": 0, "warning_count": 0})
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"ok": True})
    ):
        await onboarding.skip_step(
            step_key="data_imports",
            body=onboarding.StepSkipRequest(reason="Manual setup path"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert step.status == "skipped"
    assert step.metadata_json == {"reason": "Manual setup path"}

    step.status = "in_progress"
    step.completion_source = None
    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(return_value=step)), patch(
        "services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"step_statuses": {"data_imports": "in_progress"}, "blocker_count": 0, "warning_count": 0})
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"ok": True})
    ):
        await onboarding.acknowledge_step(
            step_key="data_imports",
            body=onboarding.StepAcknowledgeRequest(note="  keep this note  "),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert step.status == "completed"
    assert step.completion_source == "manual"
    assert step.acknowledged_by_user_id == actor.id
    assert step.acknowledged_at is not None
    assert step.metadata_json == {"note": "keep this note"}

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as skip_disallowed:
            await onboarding.skip_step(
                step_key="campus",
                body=onboarding.StepSkipRequest(reason="not applicable"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert skip_disallowed.value.status_code == 409

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as missing_reason:
            await onboarding.skip_step(
                step_key="data_imports",
                body=onboarding.StepSkipRequest(reason="   "),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert missing_reason.value.status_code == 422

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(return_value=step)), patch(
        "services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"step_statuses": {"data_imports": "blocked"}, "blocker_count": 1, "warning_count": 0})
    ):
        with pytest.raises(HTTPException) as exc:
            await onboarding.acknowledge_step(
                step_key="data_imports",
                body=onboarding.StepAcknowledgeRequest(note="force"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_complete_requires_no_blockers_and_sets_review_step() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="ready",
        current_step_key="readiness_review",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )
    review_step = SchoolOnboardingStep(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        onboarding_run_id=run.id,
        step_key="readiness_review",
        status="in_progress",
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"blocker_count": 2, "warning_count": 0})):
        with pytest.raises(HTTPException) as exc:
            await onboarding.complete_onboarding(tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 409

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(return_value=review_step)), patch(
        "services.gateway.routers.onboarding.compute_readiness", new=AsyncMock(return_value={"blocker_count": 0, "warning_count": 3})
    ), patch("services.gateway.routers.onboarding.log_action", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"run_status": "completed"})
    ):
        payload = await onboarding.complete_onboarding(tenant=tenant, actor=actor, db=db)

    assert payload["run_status"] == "completed"
    assert run.status == "completed"
    assert run.completed_by_user_id == actor.id
    assert run.completed_at is not None
    assert review_step.status == "completed"


def test_authorization_and_tenant_isolation_for_onboarding_routes() -> None:
    tenant = _tenant()
    db = _StatefulDb()

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding.compute_readiness",
        new=AsyncMock(return_value={"readiness_percentage": 0, "warning_count": 0, "step_statuses": {}, "recommended_next_actions": []}),
    ), patch("services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=None)):
        principal = _user(tenant_id=tenant.id, role="principal")
        with _client(db, tenant, principal) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(principal, tenant.slug)).status_code == 200

        admin = _user(tenant_id=tenant.id, role="school_admin")
        with _client(db, tenant, admin) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(admin, tenant.slug)).status_code == 200

        teacher = _user(tenant_id=tenant.id, role="teacher")
        with _client(db, tenant, teacher) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(teacher, tenant.slug)).status_code == 403

        parent = _user(tenant_id=tenant.id, role="parent")
        with _client(db, tenant, parent) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(parent, tenant.slug)).status_code == 403

        inactive_principal = _user(tenant_id=tenant.id, role="principal")
        inactive_principal.is_active = False
        with _client(db, tenant, inactive_principal) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(inactive_principal, tenant.slug)).status_code == 403

        cross_tenant_actor = _user(tenant_id=uuid.uuid4(), role="principal")
        with _client(db, tenant, cross_tenant_actor) as client:
            assert client.get("/leadership/onboarding/status", headers=_headers(cross_tenant_actor, tenant.slug)).status_code == 401

    app.dependency_overrides.clear()


def test_history_endpoint_and_no_delete_route() -> None:
    paths = app.openapi()["paths"]
    assert "/leadership/onboarding/history" in paths
    onboarding_paths = [paths[path] for path in paths if path.startswith("/leadership/onboarding")]
    assert all("delete" not in operations for operations in onboarding_paths)


def test_route_set_and_security_dependencies_are_complete() -> None:
    route_ops = set()
    route_map: dict[str, APIRoute] = {}
    for route in onboarding.router.routes:
        if isinstance(route, APIRoute):
            route_map[route.path] = route
            for method in route.methods:
                if method in {"GET", "POST", "PATCH"}:
                    route_ops.add((method, route.path))

    assert REQUIRED_ONBOARDING_ROUTES <= route_ops

    for _, path in REQUIRED_ONBOARDING_ROUTES:
        route = route_map[path]
        dependencies = {dep.call for dep in route.dependant.dependencies}
        assert resolve_tenant in dependencies
        assert onboarding.resolve_authenticated_leadership in dependencies


def test_fixed_catalogue_is_exact_and_arbitrary_keys_are_rejected() -> None:
    assert onboarding.STEP_CATALOGUE == EXPECTED_STEP_CATALOGUE
    with pytest.raises(HTTPException) as exc:
        onboarding._validate_step_key("arbitrary")
    assert exc.value.status_code == 422


def test_phase_9e_migration_head_and_chain() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert heads == ["c4f7a8e2d911"]

    revision_chain = {revision.revision for revision in script.iterate_revisions(heads[0], "base")}
    assert "b3c7d9e4f512" in revision_chain


def test_phase_9e_migration_file_contains_required_constraints_and_indexes() -> None:
    migration_path = Path("alembic/versions/c4f7a8e2d911_phase_9e_onboarding_workflow_foundation.py")
    assert migration_path.exists()

    spec = importlib.util.spec_from_file_location("phase_9e_migration", migration_path)
    assert spec and spec.loader

    content = migration_path.read_text(encoding="utf-8")
    assert "school_onboarding_runs" in content
    assert "school_onboarding_steps" in content
    assert "revision: str = \"c4f7a8e2d911\"" in content
    assert "uq_school_onboarding_runs_active_per_tenant" in content
    assert "uq_school_onboarding_steps_run_step" in content
    assert "down_revision: Union[str, None] = \"b3c7d9e4f512\"" in content


@pytest.mark.asyncio
async def test_step_lookup_is_tenant_scoped() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()
    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="data_imports",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(return_value=run)
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await onboarding.acknowledge_step(
                step_key="data_imports",
                body=onboarding.StepAcknowledgeRequest(note="ok"),
                tenant=tenant,
                actor=actor,
                db=db,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_audit_events_cover_all_lifecycle_actions_and_safe_payloads() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = _StatefulDb()

    run = SchoolOnboardingRun(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="in_progress",
        current_step_key="campus",
        started_by_user_id=actor.id,
        started_at=datetime.now(timezone.utc),
    )
    step = SchoolOnboardingStep(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        onboarding_run_id=run.id,
        step_key="data_imports",
        status="in_progress",
    )
    review_step = SchoolOnboardingStep(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        onboarding_run_id=run.id,
        step_key="readiness_review",
        status="in_progress",
    )

    audit = AsyncMock()

    with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.onboarding._load_active_run", new=AsyncMock(side_effect=[None, run, run, run, run, run, run, run])
    ), patch("services.gateway.routers.onboarding._load_step", new=AsyncMock(side_effect=[step, step, review_step])), patch(
        "services.gateway.routers.onboarding.compute_readiness",
        new=AsyncMock(return_value={"blocker_count": 0, "warning_count": 1, "step_statuses": {"data_imports": "in_progress"}}),
    ), patch("services.gateway.routers.onboarding.log_action", new=audit), patch(
        "services.gateway.routers.onboarding._build_run_status_payload", new=AsyncMock(return_value={"ok": True})
    ):
        await onboarding.start_onboarding(tenant=tenant, actor=actor, db=db)
        await onboarding.update_current_step(
            body=onboarding.CurrentStepUpdateRequest(step_key="people"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        await onboarding.acknowledge_step(
            step_key="data_imports",
            body=onboarding.StepAcknowledgeRequest(note="ready"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        await onboarding.skip_step(
            step_key="data_imports",
            body=onboarding.StepSkipRequest(reason="manual path"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        await onboarding.pause_onboarding(tenant=tenant, actor=actor, db=db)
        run.status = "paused"
        await onboarding.resume_onboarding(tenant=tenant, actor=actor, db=db)
        run.status = "ready"
        await onboarding.complete_onboarding(tenant=tenant, actor=actor, db=db)
        run.status = "in_progress"
        await onboarding.cancel_onboarding(tenant=tenant, actor=actor, db=db)

    actions = [call.kwargs.get("action") for call in audit.await_args_list]
    assert "onboarding.started" in actions
    assert "onboarding.current_step.changed" in actions
    assert "onboarding.step.acknowledged" in actions
    assert "onboarding.step.skipped" in actions
    assert "onboarding.paused" in actions
    assert "onboarding.resumed" in actions
    assert "onboarding.completed" in actions
    assert "onboarding.cancelled" in actions

    forbidden_tokens = {
        "password",
        "token",
        "csv",
        "email",
        "phone",
        "invited_email",
        "contact",
        "secret",
    }
    for call in audit.await_args_list:
        details = call.kwargs.get("details") or {}
        flattened = str(details).lower()
        assert not any(token in flattened for token in forbidden_tokens)
