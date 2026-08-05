from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.onboarding import readiness
from services.gateway.routers import auth as auth_router
from services.gateway.routers import imports, onboarding
from shared.auth.dependencies import require_role
from shared.db.models import AccountInvitation, ImportBatch, SchoolOnboardingRun, SchoolOnboardingStep, StudentEnrollment


REQUIRED_ROUTE_GROUPS = {
    "/health",
    "/leadership/master-data/campuses",
    "/leadership/academic-structure/classes",
    "/leadership/teacher-assignments",
    "/leadership/student-enrollments",
    "/leadership/people",
    "/leadership/families/summary",
    "/leadership/imports/summary",
    "/leadership/onboarding/status",
    "/leadership/onboarding/readiness",
    "/leadership/onboarding/history",
    "/timetable/",
    "/auth/accept-invitation",
    "/ingest/subjects",
    "/ingest/classes",
    "/ingest/teachers",
    "/ingest/students",
    "/ingest/parents",
}


def _tenant(slug: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug=slug, name=slug.title(), is_active=True, settings={})


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        name=role,
        email=f"{role}@example.test",
    )


class _Result:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _StateDb:
    def __init__(self):
        self.runs: list[SchoolOnboardingRun] = []
        self.steps: list[SchoolOnboardingStep] = []
        self.add = MagicMock(side_effect=self._add)
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    def _add(self, obj: object) -> None:
        now = datetime.now(timezone.utc)
        if isinstance(obj, SchoolOnboardingRun):
            if obj.created_at is None:
                obj.created_at = now
            if obj.updated_at is None:
                obj.updated_at = now
            self.runs.append(obj)
        elif isinstance(obj, SchoolOnboardingStep):
            if obj.created_at is None:
                obj.created_at = now
            if obj.updated_at is None:
                obj.updated_at = now
            self.steps.append(obj)

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        params = stmt.compile().params

        if entity is SchoolOnboardingStep:
            tenant_id = params.get("tenant_id_1")
            run_id = params.get("onboarding_run_id_1")
            rows = [
                step
                for step in self.steps
                if step.tenant_id == tenant_id and step.onboarding_run_id == run_id
            ]
            rows.sort(key=lambda row: row.created_at)
            return _Result(rows)

        if entity is SchoolOnboardingRun:
            tenant_id = params.get("tenant_id_1")
            rows = [run for run in self.runs if run.tenant_id == tenant_id]
            rows.sort(key=lambda row: row.created_at, reverse=True)
            return _Result(rows)

        return _Result([])


def _readiness_payload(
    *,
    blocked_steps: set[str],
    warning_checks: list[tuple[str, str, str, str]] | None = None,
    informational_checks: list[tuple[str, str, str, str]] | None = None,
) -> dict[str, object]:
    warning_checks = warning_checks or []
    informational_checks = informational_checks or []

    checks: list[dict[str, object]] = []

    for step in blocked_steps:
        checks.append(
            {
                "check_key": f"blocking_{step}",
                "step_key": step,
                "title": f"Blocking {step}",
                "status": "blocking",
                "current_value": 0,
                "required_value": 1,
                "message": f"{step} is incomplete.",
                "recommended_action": "Open workspace",
                "action_route": "/academic-structure" if step not in {"people", "family_relationships"} else "/people",
                "evidence_source": step,
            }
        )

    for check_key, step_key, message, route in warning_checks:
        checks.append(
            {
                "check_key": check_key,
                "step_key": step_key,
                "title": check_key,
                "status": "warning",
                "current_value": 1,
                "required_value": 0,
                "message": message,
                "recommended_action": "Review",
                "action_route": route,
                "evidence_source": check_key,
            }
        )

    for check_key, step_key, message, route in informational_checks:
        checks.append(
            {
                "check_key": check_key,
                "step_key": step_key,
                "title": check_key,
                "status": "informational",
                "current_value": 1,
                "required_value": 0,
                "message": message,
                "recommended_action": "Review",
                "action_route": route,
                "evidence_source": check_key,
            }
        )

    step_statuses = {step: "not_started" for step in onboarding.STEP_CATALOGUE}
    for step in blocked_steps:
        step_statuses[step] = "blocked"

    if not blocked_steps:
        for step in onboarding.STEP_CATALOGUE:
            if step not in {"data_imports"}:
                step_statuses[step] = "completed"
        step_statuses["data_imports"] = "in_progress"

    grouped = {
        group: [item for item in checks if item["step_key"] in keys]
        for group, keys in readiness.STEP_GROUPS.items()
    }

    completed_count = sum(1 for status in step_statuses.values() if status == "completed")
    blockers = [item for item in checks if item["status"] == "blocking"]
    warnings = [item for item in checks if item["status"] == "warning"]
    infos = [item for item in checks if item["status"] == "informational"]

    return {
        "checks": checks,
        "grouped_checks": grouped,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "informational_count": len(infos),
        "readiness_percentage": int((completed_count / len(onboarding.STEP_CATALOGUE)) * 100),
        "recommended_next_actions": [
            {
                "step_key": item["step_key"],
                "check_key": item["check_key"],
                "message": item["message"],
                "action_route": item["action_route"],
            }
            for item in (blockers[:3] or warnings[:1])
        ],
        "step_statuses": step_statuses,
    }


def _load_active_run(db: _StateDb, tenant_id: uuid.UUID) -> SchoolOnboardingRun | None:
    active = [run for run in db.runs if run.tenant_id == tenant_id and run.status in onboarding.ACTIVE_STATUSES]
    active.sort(key=lambda row: row.created_at, reverse=True)
    return active[0] if active else None


async def _load_active_run_async(db: _StateDb, tenant_id: uuid.UUID, *, lock: bool = False) -> SchoolOnboardingRun | None:
    del lock
    return _load_active_run(db, tenant_id)


async def _load_step_async(
    db: _StateDb,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    step_key: str,
    *,
    lock: bool = False,
) -> SchoolOnboardingStep | None:
    del lock
    for step in db.steps:
        if step.tenant_id == tenant_id and step.onboarding_run_id == run_id and step.step_key == step_key:
            return step
    return None


def _count_stub(values: list[int]):
    iterator = iter(values)

    async def _inner(db, stmt):
        del db, stmt
        return next(iterator)

    return _inner


def _readiness_values(
    *,
    teacher_without_profile: int = 0,
    stale_pointer: int = 0,
    multiple_active: int = 0,
    students_without_parent: int = 0,
    failed_imports: int = 0,
    preview_ready_imports: int = 0,
) -> list[int]:
    return [
        1,
        1,
        1,
        1,
        1,
        0,
        0,
        1,
        1,
        1,
        teacher_without_profile,
        0,
        1,
        1,
        1,
        1,
        1,
        multiple_active,
        stale_pointer,
        students_without_parent,
        1,
        5,
        1,
        failed_imports,
        preview_ready_imports,
        0,
        0,
        0,
    ]


def test_route_inventory_and_no_destructive_delete_routes() -> None:
    paths = app.openapi()["paths"]
    assert REQUIRED_ROUTE_GROUPS.issubset(paths.keys())
    assert "post" in paths["/auth/accept-invitation"]
    assert "get" in paths["/health"]
    assert all("delete" not in methods for path, methods in paths.items() if path.startswith("/leadership/onboarding"))
    assert all("delete" not in methods for path, methods in paths.items() if path.startswith("/leadership/imports"))


def test_role_and_active_user_enforcement() -> None:
    import asyncio

    tenant = _tenant("greenwood")
    leadership_dependency = require_role("principal", "school_admin")

    for role in ("teacher", "parent", "student"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(leadership_dependency(current_user=_user(tenant_id=tenant.id, role=role)))
        assert exc.value.status_code == 403

    asyncio.run(leadership_dependency(current_user=_user(tenant_id=tenant.id, role="principal")))
    asyncio.run(leadership_dependency(current_user=_user(tenant_id=tenant.id, role="school_admin")))

    inactive = _user(tenant_id=tenant.id, role="principal", is_active=False)
    with pytest.raises(HTTPException) as exc:
        onboarding._ensure_actor_tenant(inactive, tenant)
    assert exc.value.status_code == 403


def test_tenant_isolation_and_onboarding_lifecycle_contract() -> None:
    async def _run() -> None:
        db = _StateDb()
        tenant_a = _tenant("greenwood")
        tenant_b = _tenant("lakeside")
        actor_a = _user(tenant_id=tenant_a.id, role="principal")
        actor_b = _user(tenant_id=tenant_b.id, role="school_admin")
        audit_events: list[dict[str, object]] = []

        readiness_state = {
            tenant_a.id: "blocked",
            tenant_b.id: "blocked",
        }

        async def _compute(_db, tenant_id: uuid.UUID):
            if readiness_state[tenant_id] == "blocked":
                return _readiness_payload(
                    blocked_steps={
                        "campus",
                        "academic_year",
                        "terms",
                        "grade_levels",
                        "subjects",
                        "classes",
                        "subject_offerings",
                        "people",
                        "teacher_assignments",
                        "student_enrolments",
                        "timetable",
                    }
                )
            return _readiness_payload(
                blocked_steps=set(),
                warning_checks=[
                    (
                        "data_recent_failed_or_error_imports",
                        "data_imports",
                        "Failed import remains warning-level.",
                        "/data",
                    )
                ],
                informational_checks=[
                    (
                        "family_inactive_history",
                        "family_relationships",
                        "Historical family relationship retained.",
                        "/people",
                    )
                ],
            )

        async def _audit(*, db, tenant_id, action, entity_type, entity_id, actor_id, details):
            del db
            audit_events.append(
                {
                    "tenant_id": tenant_id,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "actor_id": actor_id,
                    "details": details,
                }
            )

        with patch("services.gateway.routers.onboarding.set_tenant_context", new=AsyncMock()), patch(
            "services.gateway.routers.onboarding.compute_readiness", new=_compute
        ), patch("services.gateway.routers.onboarding._load_active_run", new=_load_active_run_async), patch(
            "services.gateway.routers.onboarding._load_step", new=_load_step_async
        ), patch("services.gateway.routers.onboarding.log_action", new=_audit):
            # Empty tenant begins blocked.
            readiness_before = await onboarding.onboarding_readiness(tenant=tenant_a, actor=actor_a, db=db)
            assert readiness_before["blocker_count"] > 0

            first_run = await onboarding.start_onboarding(tenant=tenant_a, actor=actor_a, db=db)
            assert first_run["run_status"] == "in_progress"

            with pytest.raises(HTTPException) as duplicate_start:
                await onboarding.start_onboarding(tenant=tenant_a, actor=actor_a, db=db)
            assert duplicate_start.value.status_code == 409

            with pytest.raises(HTTPException) as blocked_complete:
                await onboarding.complete_onboarding(tenant=tenant_a, actor=actor_a, db=db)
            assert blocked_complete.value.status_code == 409

            # Resolve blockers and complete.
            readiness_state[tenant_a.id] = "ready"
            readiness_after = await onboarding.onboarding_readiness(tenant=tenant_a, actor=actor_a, db=db)
            assert readiness_after["blocker_count"] == 0
            assert readiness_after["warning_count"] >= 1

            completed = await onboarding.complete_onboarding(tenant=tenant_a, actor=actor_a, db=db)
            assert completed["run_status"] == "completed"
            assert completed["run"]["completed_by_user_id"] == str(actor_a.id)
            assert completed["run"]["completed_at"] is not None
            assert any(step["step_key"] == "readiness_review" and step["status"] == "completed" for step in completed["ordered_steps"])

            # History is preserved when starting a new run.
            second_run = await onboarding.start_onboarding(tenant=tenant_a, actor=actor_a, db=db)
            assert second_run["run_status"] == "in_progress"
            history_a = await onboarding.onboarding_history(page=1, page_size=20, tenant=tenant_a, actor=actor_a, db=db)
            run_statuses = [item["status"] for item in history_a["items"]]
            assert "completed" in run_statuses
            assert "in_progress" in run_statuses

            # Tenant B remains isolated and blocked.
            await onboarding.start_onboarding(tenant=tenant_b, actor=actor_b, db=db)
            readiness_b = await onboarding.onboarding_readiness(tenant=tenant_b, actor=actor_b, db=db)
            assert readiness_b["blocker_count"] > 0

            cross_tenant_actor = _user(tenant_id=tenant_b.id, role="principal")
            with pytest.raises(HTTPException) as tenant_mismatch:
                await onboarding.onboarding_status(tenant=tenant_a, actor=cross_tenant_actor, db=db)
            assert tenant_mismatch.value.status_code == 401

            assert all(event["tenant_id"] == tenant_a.id for event in audit_events if event["actor_id"] == actor_a.id)
            assert all(event["tenant_id"] == tenant_b.id for event in audit_events if event["actor_id"] == actor_b.id)

    import asyncio

    asyncio.run(_run())


def test_readiness_stale_pointer_and_multiple_active_blockers() -> None:
    async def _run() -> None:
        tenant_id = uuid.uuid4()
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(readiness, "_count", _count_stub(_readiness_values(stale_pointer=1)))
            payload = await readiness.compute_readiness(db, tenant_id)
        checks = {item["check_key"]: item for item in payload["checks"]}
        assert checks["ops_stale_class_pointer_conflict"]["status"] == "blocking"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(readiness, "_count", _count_stub(_readiness_values(stale_pointer=0)))
            payload = await readiness.compute_readiness(db, tenant_id)
        checks = {item["check_key"]: item for item in payload["checks"]}
        assert checks["ops_stale_class_pointer_conflict"]["status"] == "complete"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(readiness, "_count", _count_stub(_readiness_values(multiple_active=1)))
            payload = await readiness.compute_readiness(db, tenant_id)
        checks = {item["check_key"]: item for item in payload["checks"]}
        assert checks["ops_multiple_active_enrollment_diagnostic"]["status"] == "blocking"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(readiness, "_count", _count_stub(_readiness_values(multiple_active=0)))
            payload = await readiness.compute_readiness(db, tenant_id)
        checks = {item["check_key"]: item for item in payload["checks"]}
        assert checks["ops_multiple_active_enrollment_diagnostic"]["status"] == "complete"

    import asyncio

    asyncio.run(_run())


def test_readiness_warning_only_family_and_import_diagnostics() -> None:
    async def _run() -> None:
        tenant_id = uuid.uuid4()
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                readiness,
                "_count",
                _count_stub(
                    _readiness_values(
                        students_without_parent=1,
                        failed_imports=1,
                        preview_ready_imports=1,
                    )
                ),
            )
            payload = await readiness.compute_readiness(db, tenant_id)

        checks = {item["check_key"]: item for item in payload["checks"]}
        assert checks["family_students_without_parent_guardian"]["status"] == "warning"
        assert checks["data_recent_failed_or_error_imports"]["status"] == "warning"
        assert checks["data_preview_ready_uncommitted_imports"]["status"] == "informational"

    import asyncio

    asyncio.run(_run())


def test_idempotency_and_replay_protections() -> None:
    async def _run() -> None:
        assert "uq_school_onboarding_runs_active_per_tenant" in [index.name for index in SchoolOnboardingRun.__table__.indexes]
        assert "uq_student_enrollments_active_student_year" in [index.name for index in StudentEnrollment.__table__.indexes]

        tenant = _tenant("greenwood")
        actor = _user(tenant_id=tenant.id, role="principal")

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
            with pytest.raises(HTTPException) as duplicate_run:
                await onboarding.start_onboarding(tenant=tenant, actor=actor, db=AsyncMock())
        assert duplicate_run.value.status_code == 409

        batch = ImportBatch(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            entity_type="subjects",
            original_filename="subjects.csv",
            file_sha256="a" * 64,
            status="completed",
            mode="preview",
            created_by_user_id=actor.id,
            total_rows=1,
            valid_rows=1,
            invalid_rows=0,
            created_rows=1,
            updated_rows=0,
            skipped_rows=0,
            conflict_rows=0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            committed_at=datetime.now(timezone.utc),
        )
        import_db = AsyncMock()
        import_db.scalar = AsyncMock(return_value=batch)
        with patch("services.gateway.routers.imports.set_tenant_context", new=AsyncMock()):
            with pytest.raises(HTTPException) as duplicate_commit:
                await imports.commit_import(batch_id=batch.id, tenant=tenant, actor=actor, db=import_db)
        assert duplicate_commit.value.status_code == 409

        invitation = AccountInvitation(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            user_id=actor.id,
            invited_email=actor.email,
            role="principal",
            token_hash="deadbeef" * 8,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            accepted_at=datetime.now(timezone.utc),
            revoked_at=None,
            created_by_user_id=actor.id,
        )
        invitation_db = AsyncMock()
        invitation_db.scalar = AsyncMock(return_value=invitation)
        with pytest.raises(HTTPException) as replayed:
            await auth_router.accept_invitation(
                body=auth_router.AcceptInvitationRequest(token="raw-token", new_password="StrongPass1"),
                db=invitation_db,
            )
        assert replayed.value.status_code == 409

    import asyncio

    asyncio.run(_run())
