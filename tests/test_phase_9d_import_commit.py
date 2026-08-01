from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from services.gateway.main import app
from shared.auth.jwt import create_access_token, get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import ImportBatch, ImportRowResult


class _Result:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def scalar_one_or_none(self):
        return self._scalar


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True, name="User", email=f"{role}@example.test")


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_commit_applies_only_valid_and_skipped_rows() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    batch = ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        entity_type="subjects",
        original_filename="subjects.csv",
        file_sha256="b" * 64,
        status="preview_ready",
        mode="preview",
        created_by_user_id=actor.id,
        total_rows=4,
        valid_rows=2,
        invalid_rows=1,
        created_rows=0,
        updated_rows=0,
        skipped_rows=1,
        conflict_rows=1,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        committed_at=None,
    )
    rows = [
        ImportRowResult(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=batch.id, row_number=1, status="valid", action="create", entity_reference_id=None, error_code=None, error_message=None, field_errors={}, normalized_data={"code": "MATH", "name": "Mathematics"}, row_data={}),
        ImportRowResult(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=batch.id, row_number=2, status="skipped", action="skip", entity_reference_id=None, error_code=None, error_message=None, field_errors={}, normalized_data={"code": "ENG", "name": "English"}, row_data={}),
        ImportRowResult(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=batch.id, row_number=3, status="invalid", action="none", entity_reference_id=None, error_code="missing_required_field", error_message="name is required.", field_errors={"name": "required"}, normalized_data={"code": "SCI"}, row_data={}),
        ImportRowResult(id=uuid.uuid4(), tenant_id=tenant.id, import_batch_id=batch.id, row_number=4, status="conflict", action="skip", entity_reference_id=None, error_code="duplicate_existing_record", error_message="Subject already exists.", field_errors={"code": "already_exists"}, normalized_data={"code": "HIS", "name": "History"}, row_data={}),
    ]
    db.scalar = AsyncMock(return_value=batch)
    db.execute = AsyncMock(return_value=_Result(rows=rows))

    with _client(db, tenant, actor) as client:
        response = client.post(f"/leadership/imports/{batch.id}/commit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["status"] == "completed"
    assert payload["batch"]["created_rows"] == 1
    assert payload["batch"]["skipped_rows"] == 1
    assert payload["batch"]["invalid_rows"] == 1
    assert payload["batch"]["conflict_rows"] == 1
    added_names = [call.args[0].__class__.__name__ for call in db.add.call_args_list]
    assert "Subject" in added_names
    assert "Student" not in added_names
    assert "Teacher" not in added_names
    db.commit.assert_awaited()
    app.dependency_overrides.clear()


def test_commit_rejects_batches_not_ready_or_already_committing() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    ready_batch = ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        entity_type="subjects",
        original_filename="subjects.csv",
        file_sha256="c" * 64,
        status="committing",
        mode="preview",
        created_by_user_id=actor.id,
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        conflict_rows=0,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        committed_at=None,
    )
    db.scalar = AsyncMock(return_value=ready_batch)

    with _client(db, tenant, actor) as client:
        response = client.post(f"/leadership/imports/{ready_batch.id}/commit")

    assert response.status_code == 409
    app.dependency_overrides.clear()


def test_phase_9d_is_current_migration_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "b3c7d9e4f512"

    revision_chain = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }

    assert "1a9d5e7c3b21" in revision_chain
