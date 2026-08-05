from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from openpyxl import Workbook

from services.gateway.main import app
from services.gateway.routers import timetable_setup_imports
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True, name="Leader", email="leader@example.test")


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    return db


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Teachers"
    ws.append(["teacher_id", "teacher_name", "active"])
    ws.append(["T-1", "Ada", "yes"])
    payload = io.BytesIO()
    wb.save(payload)
    payload.seek(0)
    return payload.read()


def test_valid_workbook_upload_is_accepted() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()

    with _client(db, tenant, actor) as client:
        response = client.post(
            "/leadership/timetable-setup/imports/workbooks",
            files={"file": ("timetable.xlsx", io.BytesIO(_xlsx_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["entity_type"] == "timetable_workbook"
    assert payload["batch"]["import_format"] == "xlsx"
    app.dependency_overrides.clear()


def test_upload_rejects_empty_and_legacy_formats_and_malformed_xlsx() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()

    with _client(db, tenant, actor) as client:
        empty = client.post("/leadership/timetable-setup/imports/workbooks", files={"file": ("empty.xlsx", io.BytesIO(b""), "application/octet-stream")})
        xls = client.post("/leadership/timetable-setup/imports/workbooks", files={"file": ("legacy.xls", io.BytesIO(b"dummy"), "application/octet-stream")})
        xlsm = client.post("/leadership/timetable-setup/imports/workbooks", files={"file": ("macro.xlsm", io.BytesIO(b"dummy"), "application/octet-stream")})
        malformed = client.post("/leadership/timetable-setup/imports/workbooks", files={"file": ("broken.xlsx", io.BytesIO(b"not-a-zip"), "application/octet-stream")})

    assert empty.status_code == 422
    assert xls.status_code == 422
    assert xlsm.status_code == 422
    assert malformed.status_code == 422
    app.dependency_overrides.clear()


def test_upload_rejects_oversized_payload_when_limit_reduced() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    db = _db()
    original = timetable_setup_imports.settings.timetable_workbook_max_upload_bytes
    timetable_setup_imports.settings.timetable_workbook_max_upload_bytes = 8
    try:
        with _client(db, tenant, actor) as client:
            response = client.post(
                "/leadership/timetable-setup/imports/workbooks",
                files={"file": ("big.xlsx", io.BytesIO(_xlsx_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 413
    finally:
        timetable_setup_imports.settings.timetable_workbook_max_upload_bytes = original
        app.dependency_overrides.clear()
