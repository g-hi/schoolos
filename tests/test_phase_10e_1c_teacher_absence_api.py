from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import services.gateway.routers.teacher_absences as api
from services.timetable.teacher_absences import TeacherAbsenceError
from shared.auth.dependencies import resolve_authenticated_teacher
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from services.gateway.main import app
from shared.db.models import TeacherAbsence


class Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class FakeDB:
    def __init__(self, *, scalar_values: list[object] | None = None, rows: list[object] | None = None) -> None:
        self.scalar = AsyncMock(side_effect=scalar_values or [])
        self.execute = AsyncMock(return_value=Result(rows or []))
        self.commit = AsyncMock()
        self.added: list[object] = []

    async def execute_context(self, *args: object, **kwargs: object) -> None:
        return None


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _user(tenant_id: uuid.UUID, *, role: str = "teacher") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True)


def _teacher(tenant_id: uuid.UUID, user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id)


def _absence(tenant_id: uuid.UUID, teacher_id: uuid.UUID, *, status_value: str = "reported") -> TeacherAbsence:
    return TeacherAbsence(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        scope_type="whole_day",
        selected_periods=None,
        reason_code="sick",
        private_note="sensitive note",
        status=status_value,
        source_type="teacher",
        reported_by_user_id=uuid.uuid4(),
        reported_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        confirmed_at=None,
        cancelled_at=None,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def _report_request(**overrides: object) -> api.TeacherAbsenceReportRequest:
    values: dict[str, object] = {
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 1),
        "scope_type": "whole_day",
        "reason_code": "sick",
    }
    values.update(overrides)
    return api.TeacherAbsenceReportRequest(**values)


@pytest.mark.asyncio
async def test_teacher_can_report_only_for_own_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = _tenant()
    actor = _user(tenant.id)
    teacher = _teacher(tenant.id, actor.id)
    db = FakeDB(scalar_values=[teacher])
    created = _absence(tenant.id, teacher.id)
    report = AsyncMock(return_value=created)
    monkeypatch.setattr(api, "report_absence", report)
    monkeypatch.setattr(api, "set_tenant_context", AsyncMock())

    result = await api.report_teacher_absence(_report_request(), tenant=tenant, actor=actor, db=db)

    assert result is created
    report.assert_awaited_once()
    assert report.await_args.kwargs["teacher_id"] == teacher.id
    assert report.await_args.kwargs["reported_by_user_id"] == actor.id
    assert report.await_args.kwargs["source_type"] == "teacher"
    assert "teacher_id" not in api.TeacherAbsenceReportRequest.model_fields
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_teacher_list_and_get_are_own_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = _tenant()
    actor = _user(tenant.id)
    teacher = _teacher(tenant.id, actor.id)
    own = _absence(tenant.id, teacher.id)
    db = FakeDB(scalar_values=[teacher], rows=[own])
    monkeypatch.setattr(api, "set_tenant_context", AsyncMock())

    listed = await api.list_teacher_absences(tenant=tenant, actor=actor, db=db, page=1, page_size=20)
    assert listed["items"][0]["id"] == own.id
    statement = db.execute.await_args.args[0]
    assert "teacher_absences.teacher_id" in str(statement)

    db.scalar = AsyncMock(side_effect=[teacher, own])
    loaded = await api.get_teacher_absence(own.id, tenant=tenant, actor=actor, db=db)
    assert loaded["private_note"] == "sensitive note"


@pytest.mark.asyncio
async def test_teacher_cannot_get_another_teachers_absence() -> None:
    tenant = _tenant()
    actor = _user(tenant.id)
    teacher = _teacher(tenant.id, actor.id)
    db = FakeDB(scalar_values=[teacher, None])
    with pytest.raises(HTTPException) as exc:
        await api.get_teacher_absence(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_leadership_report_list_and_view_are_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = _tenant()
    actor = _user(tenant.id, role="principal")
    teacher = _teacher(tenant.id, uuid.uuid4())
    absence = _absence(tenant.id, teacher.id)
    db = FakeDB(rows=[absence])
    monkeypatch.setattr(api, "set_tenant_context", AsyncMock())
    report = AsyncMock(return_value=absence)
    monkeypatch.setattr(api, "report_absence", report)

    request = api.LeadershipAbsenceReportRequest(
        teacher_id=teacher.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        scope_type="whole_day",
        reason_code="sick",
    )
    assert await api.report_leadership_absence(request, tenant=tenant, actor=actor, db=db) is absence
    assert report.await_args.kwargs["teacher_id"] == teacher.id
    assert report.await_args.kwargs["source_type"] == "leadership"

    listed = await api.list_leadership_absences(tenant=tenant, actor=actor, db=db, page=1, page_size=20)
    assert listed["items"][0]["id"] == absence.id
    db.scalar = AsyncMock(return_value=absence)
    viewed = await api.get_leadership_absence(absence.id, tenant=tenant, actor=actor, db=db)
    assert viewed["private_note"] == "sensitive note"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_name", "service_name", "service_kwarg"),
    [
        ("confirm_leadership_absence", "confirm_absence", "confirmed_by_user_id"),
        ("cancel_leadership_absence", "cancel_absence", "cancelled_by_user_id"),
        ("close_leadership_absence", "close_absence", None),
    ],
)
async def test_leadership_lifecycle_routes_delegate_without_router_commit(
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
    service_name: str,
    service_kwarg: str | None,
) -> None:
    tenant = _tenant()
    actor = _user(tenant.id, role="school_admin")
    absence = _absence(tenant.id, uuid.uuid4(), status_value="confirmed")
    db = FakeDB()
    monkeypatch.setattr(api, "set_tenant_context", AsyncMock())
    operation = AsyncMock(return_value=absence)
    monkeypatch.setattr(api, service_name, operation)

    result = await getattr(api, operation_name)(absence.id, tenant=tenant, actor=actor, db=db)

    assert result is absence
    assert operation.await_args.kwargs["tenant_id"] == tenant.id
    assert operation.await_args.kwargs["absence_id"] == absence.id
    if service_kwarg:
        assert operation.await_args.kwargs[service_kwarg] == actor.id
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_service_error_mapping_is_stable_and_does_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = _tenant()
    actor = _user(tenant.id, role="principal")
    db = FakeDB()
    monkeypatch.setattr(api, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(api, "confirm_absence", AsyncMock(side_effect=TeacherAbsenceError("absence_transition_invalid", "private database detail")))

    with pytest.raises(HTTPException) as exc:
        await api.confirm_leadership_absence(uuid.uuid4(), tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "absence_transition_invalid", "message": "Absence operation could not be completed."}
    assert "private database detail" not in str(exc.value.detail)


def test_absence_router_paths_and_methods_are_registered() -> None:
    teacher_paths = {(route.path, method) for route in api.teacher_router.routes for method in route.methods}
    leadership_paths = {(route.path, method) for route in api.leadership_router.routes for method in route.methods}
    assert ("/teacher/operations/absences", "POST") in teacher_paths
    assert ("/teacher/operations/absences", "GET") in teacher_paths
    assert ("/teacher/operations/absences/{absence_id}", "GET") in teacher_paths
    assert {("/leadership/operations/absences", "POST"), ("/leadership/operations/absences", "GET")} <= leadership_paths
    assert {("/leadership/operations/absences/{absence_id}", "GET"), ("/leadership/operations/absences/{absence_id}/confirm", "POST"), ("/leadership/operations/absences/{absence_id}/cancel", "POST"), ("/leadership/operations/absences/{absence_id}/close", "POST")} <= leadership_paths


def test_real_fastapi_absence_contract() -> None:
    paths = app.openapi()["paths"]
    expected_paths = {
        "/teacher/operations/absences",
        "/teacher/operations/absences/{absence_id}",
        "/leadership/operations/absences",
        "/leadership/operations/absences/{absence_id}",
        "/leadership/operations/absences/{absence_id}/confirm",
        "/leadership/operations/absences/{absence_id}/cancel",
        "/leadership/operations/absences/{absence_id}/close",
    }
    assert expected_paths <= set(paths)

    unauthenticated = TestClient(app, raise_server_exceptions=False).get(
        "/teacher/operations/absences"
    )
    assert unauthenticated.status_code in {401, 403}

    tenant = _tenant()
    actor = _user(tenant.id)
    teacher = _teacher(tenant.id, actor.id)
    absence = _absence(tenant.id, teacher.id)
    db = FakeDB(scalar_values=[teacher], rows=[absence])

    async def mock_get_db():
        yield db

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_teacher] = lambda: actor
    try:
        with TestClient(app) as client:
            response = client.get("/teacher/operations/absences")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["id"] == str(absence.id)
        assert payload["items"][0]["reported_at"].endswith(("Z", "+00:00"))
        assert payload["items"][0]["private_note"] == "sensitive note"
    finally:
        app.dependency_overrides.clear()
