from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway.routers import timetable_setup_imports
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import ImportBatch


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True, name="Leader", email="leader@example.test")


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def _batch(tenant_id: uuid.UUID, actor_id: uuid.UUID) -> ImportBatch:
    return ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        entity_type="timetable_workbook",
        original_filename="workbook.xlsx",
        file_sha256="b" * 64,
        status="validated",
        mode="workbook",
        import_format="xlsx",
        created_by_user_id=actor_id,
        total_rows=0,
        valid_rows=0,
        invalid_rows=0,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        conflict_rows=0,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        committed_at=None,
        metadata_json={"normalized_by_entity": {}},
    )


def test_validated_workbook_commit_is_idempotent_and_summarized() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    batch = _batch(tenant.id, actor.id)

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.scalar = AsyncMock(side_effect=[0])

    async def _load_batch(*args, **kwargs):
        return batch

    original_load = timetable_setup_imports._load_batch
    original_readiness = timetable_setup_imports.compute_timetable_input_readiness
    timetable_setup_imports._load_batch = _load_batch

    async def _fake_readiness(_db, _tenant_id):
        return {"blocker_count": 0, "warning_count": 0, "information_count": 0, "is_generation_ready": True}

    timetable_setup_imports.compute_timetable_input_readiness = _fake_readiness
    try:
        with _client(db, tenant, actor) as client:
            first = client.post(f"/leadership/timetable-setup/imports/workbooks/{batch.id}/commit")
            second = client.post(f"/leadership/timetable-setup/imports/workbooks/{batch.id}/commit")

        assert first.status_code == 200
        assert first.json()["batch"]["status"] == "committed"
        assert second.status_code == 409
    finally:
        timetable_setup_imports._load_batch = original_load
        timetable_setup_imports.compute_timetable_input_readiness = original_readiness
        app.dependency_overrides.clear()


def test_commit_requires_validated_status() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    batch = _batch(tenant.id, actor.id)
    batch.status = "preview_ready"

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def _load_batch(*args, **kwargs):
        return batch

    original = timetable_setup_imports._load_batch
    timetable_setup_imports._load_batch = _load_batch
    try:
        with _client(db, tenant, actor) as client:
            response = client.post(f"/leadership/timetable-setup/imports/workbooks/{batch.id}/commit")
        assert response.status_code == 409
    finally:
        timetable_setup_imports._load_batch = original
        app.dependency_overrides.clear()
