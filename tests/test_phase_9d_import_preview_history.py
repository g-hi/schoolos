from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from services.gateway.main import app
from shared.auth.jwt import create_access_token
from shared.auth.jwt import get_current_user
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


def _headers(user: SimpleNamespace, tenant_slug: str) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=user.role, tenant_slug=tenant_slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": tenant_slug}


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_import_router_exposes_required_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/leadership/imports/preview" in paths
    assert "/leadership/imports/{batch_id}/commit" in paths
    assert "/leadership/imports" in paths
    assert "/leadership/imports/summary" in paths
    assert "/leadership/imports/{batch_id}" in paths
    assert "/leadership/imports/{batch_id}/rows" in paths
    assert "/leadership/imports/{batch_id}/cancel" in paths
    assert "/leadership/imports/{batch_id}/errors.csv" in paths
    import_paths = [paths[path] for path in paths if path.startswith("/leadership/imports")]
    assert all("delete" not in operations for operations in import_paths)


def test_preview_subject_import_creates_history_batch_without_mutating_business_models() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    db.scalar = AsyncMock(side_effect=[None, None])

    with _client(db, tenant, actor) as client:
        response = client.post(
            "/leadership/imports/preview",
            data={"entity_type": "subjects"},
            files={"file": ("../../subjects.csv", io.BytesIO(b"code,name\nMATH,Mathematics\nENG,English\n"), "text/csv")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["entity_type"] == "subjects"
    assert payload["batch"]["status"] == "preview_ready"
    assert payload["batch"]["original_filename"] == "subjects.csv"
    assert len(payload["batch"]["file_sha256"]) == 64
    assert payload["rows"][0]["status"] == "valid"
    added_names = [call.args[0].__class__.__name__ for call in db.add.call_args_list]
    assert "ImportBatch" in added_names
    assert "ImportRowResult" in added_names
    assert "StudentEnrollment" not in added_names
    assert "Student" not in added_names
    assert "Class" not in added_names
    assert "User" not in added_names
    app.dependency_overrides.clear()


def test_preview_rejects_invalid_csv_and_unknown_entity() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    db.scalar = AsyncMock(return_value=None)

    with _client(db, tenant, actor) as client:
        bad_csv = client.post(
            "/leadership/imports/preview",
            data={"entity_type": "subjects"},
            files={"file": ("subjects.csv", io.BytesIO(b"code,extra\nMATH,x\n"), "text/csv")},
        )
        bad_entity = client.post(
            "/leadership/imports/preview",
            data={"entity_type": "robots"},
            files={"file": ("subjects.csv", io.BytesIO(b"code,name\nMATH,Mathematics\n"), "text/csv")},
        )

    assert bad_csv.status_code == 422
    assert bad_entity.status_code == 422
    app.dependency_overrides.clear()


def test_import_history_list_summary_rows_errors_and_cancel() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    batch = ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        entity_type="subjects",
        original_filename="subjects.csv",
        file_sha256="a" * 64,
        status="preview_ready",
        mode="preview",
        created_by_user_id=actor.id,
        total_rows=2,
        valid_rows=1,
        invalid_rows=1,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        conflict_rows=0,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        committed_at=None,
    )
    row = ImportRowResult(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=batch.id,
        row_number=2,
        status="invalid",
        action="none",
        entity_reference_id=None,
        error_code="missing_required_field",
        error_message="name is required.",
        field_errors={"name": "required"},
        normalized_data={"code": "MATH"},
        row_data={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.execute = AsyncMock(side_effect=[
        _Result(rows=[]),
        _Result(rows=[batch]),
        _Result(rows=[]),
        _Result(rows=[batch]),
        _Result(rows=[]),
        _Result(rows=[row]),
        _Result(rows=[]),
        _Result(rows=[row]),
        _Result(rows=[]),
    ])
    db.scalar = AsyncMock(return_value=batch)

    with _client(db, tenant, actor) as client:
        listed = client.get("/leadership/imports")
        summary = client.get("/leadership/imports/summary")
        rows = client.get(f"/leadership/imports/{batch.id}/rows")
        errors = client.get(f"/leadership/imports/{batch.id}/errors.csv")
        cancelled = client.post(f"/leadership/imports/{batch.id}/cancel")

    assert listed.status_code == 200
    assert summary.status_code == 200
    assert rows.status_code == 200
    assert errors.status_code == 200
    assert "row_number,status,error_code,error_message" in errors.text
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    app.dependency_overrides.clear()


def test_preview_requires_principal_or_school_admin() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id, role="teacher")
    db = _db()
    db.scalar = AsyncMock(return_value=None)

    with _client(db, tenant, actor) as client:
        response = client.post(
            "/leadership/imports/preview",
            data={"entity_type": "subjects"},
            files={"file": ("subjects.csv", io.BytesIO(b"code,name\nMATH,Mathematics\n"), "text/csv")},
        )

    assert response.status_code == 403
    app.dependency_overrides.clear()
