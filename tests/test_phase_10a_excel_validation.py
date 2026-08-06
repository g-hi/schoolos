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
from shared.db.models import ImportBatch, ImportRowResult


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID, role: str = "principal") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True, name="Leader", email="leader@example.test")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return type("S", (), {"all": lambda _self: self._rows})()


def _batch(tenant_id: uuid.UUID, actor_id: uuid.UUID) -> ImportBatch:
    return ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        entity_type="timetable_workbook",
        original_filename="timetable.xlsx",
        file_sha256="a" * 64,
        status="preview_ready",
        mode="workbook",
        import_format="xlsx",
        created_by_user_id=actor_id,
        total_rows=4,
        valid_rows=4,
        invalid_rows=0,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        conflict_rows=0,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        committed_at=None,
        metadata_json={
            "sheets": [
                {
                    "original_sheet_name": "Teachers",
                    "proposed_entity_type": "teachers",
                    "ignored": False,
                    "required_unmapped_fields": [],
                    "mappings": [
                        {"source_column": "teacher_id", "target_field": "teacher_id"},
                        {"source_column": "teacher_name", "target_field": "teacher_name"},
                        {"source_column": "email", "target_field": "email"},
                        {"source_column": "department", "target_field": "department"},
                    ],
                },
                {
                    "original_sheet_name": "Periods",
                    "proposed_entity_type": "periods",
                    "ignored": False,
                    "required_unmapped_fields": [],
                    "mappings": [
                        {"source_column": "schedule_name", "target_field": "schedule_name"},
                        {"source_column": "period_number", "target_field": "period_number"},
                        {"source_column": "start_time", "target_field": "start_time"},
                        {"source_column": "end_time", "target_field": "end_time"},
                        {"source_column": "teaching_period", "target_field": "teaching_period"},
                    ],
                },
                {
                    "original_sheet_name": "Teaching Requirements",
                    "proposed_entity_type": "teaching_requirements",
                    "ignored": False,
                    "required_unmapped_fields": [],
                    "mappings": [
                        {"source_column": "academic_year", "target_field": "academic_year"},
                        {"source_column": "term", "target_field": "term"},
                        {"source_column": "class_code", "target_field": "class_code"},
                        {"source_column": "subject_code", "target_field": "subject_code"},
                        {"source_column": "sessions_per_week", "target_field": "sessions_per_week"},
                        {"source_column": "periods_per_session", "target_field": "periods_per_session"},
                    ],
                },
            ]
        },
    )


def _client(db: AsyncMock, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_validation_generates_blockers_for_invalid_times_and_missing_refs() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    batch = _batch(tenant.id, actor.id)

    teacher_row = ImportRowResult(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=batch.id,
        row_number=1,
        status="valid",
        action="none",
        entity_reference_id=None,
        error_code=None,
        error_message=None,
        severity=None,
        sheet_name="Teachers",
        source_column=None,
        field_name=None,
        field_errors={"sheet_row_number": 2},
        normalized_data={},
        row_data={"teacher_id": "T-1", "teacher_name": "Ada", "email": "", "department": ""},
    )
    period_row = ImportRowResult(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=batch.id,
        row_number=2,
        status="valid",
        action="none",
        entity_reference_id=None,
        error_code=None,
        error_message=None,
        severity=None,
        sheet_name="Periods",
        source_column=None,
        field_name=None,
        field_errors={"sheet_row_number": 2},
        normalized_data={},
        row_data={"schedule_name": "Main", "period_number": "1", "start_time": "25:00", "end_time": "08:00", "teaching_period": "yes"},
    )
    req_row = ImportRowResult(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=batch.id,
        row_number=3,
        status="valid",
        action="none",
        entity_reference_id=None,
        error_code=None,
        error_message=None,
        severity=None,
        sheet_name="Teaching Requirements",
        source_column=None,
        field_name=None,
        field_errors={"sheet_row_number": 2},
        normalized_data={},
        row_data={"academic_year": "2026-2027", "term": "Term 1", "class_code": "10A", "subject_code": "MATH", "sessions_per_week": "0", "periods_per_session": "0"},
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def _execute(stmt):
        text = str(stmt)
        if "SELECT import_row_results" in text:
            return _Result([teacher_row, period_row, req_row])
        return _Result([])

    db.execute = AsyncMock(side_effect=_execute)

    async def _scalar(stmt):
        text = str(stmt)
        if "max(import_row_results.row_number)" in text:
            return 3
        return None

    db.scalar = AsyncMock(side_effect=_scalar)

    async def _load_batch(*args, **kwargs):
        return batch

    original = timetable_setup_imports._load_batch
    timetable_setup_imports._load_batch = _load_batch
    try:
        with _client(db, tenant, actor) as client:
            response = client.post(f"/leadership/timetable-setup/imports/workbooks/{batch.id}/validate")
        assert response.status_code == 200
        payload = response.json()
        assert payload["diagnostics"]["blocker_count"] > 0
        assert payload["batch"]["status"] == "validation_failed"
    finally:
        timetable_setup_imports._load_batch = original
        app.dependency_overrides.clear()


def test_blockers_prevent_commit() -> None:
    tenant = _tenant()
    actor = _actor(tenant.id)
    batch = _batch(tenant.id, actor.id)
    batch.status = "validated"

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.scalar = AsyncMock(side_effect=[1])

    async def _load_batch(*args, **kwargs):
        return batch

    original = timetable_setup_imports._load_batch
    timetable_setup_imports._load_batch = _load_batch
    try:
        with _client(db, tenant, actor) as client:
            response = client.post(f"/leadership/timetable-setup/imports/workbooks/{batch.id}/commit")
        assert response.status_code == 409
        assert "blocked" in response.json()["detail"].lower()
    finally:
        timetable_setup_imports._load_batch = original
        app.dependency_overrides.clear()
