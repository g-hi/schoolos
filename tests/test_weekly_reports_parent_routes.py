from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from services.gateway.main import app
from shared.auth.jwt import create_access_token
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant(*, slug: str = "greenwood") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug=slug, settings={})


def _parent_user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="parent",
        is_active=True,
        name="Aisha Parent",
        email="aisha@example.test",
    )


def _db_with_execute_sequence(results: list[object]) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=results)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _result_scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _result_first(value: object) -> MagicMock:
    result = MagicMock()
    result.first.return_value = value
    return result


def _result_all(value: object) -> MagicMock:
    result = MagicMock()
    result.all.return_value = value
    return result


def _override_tenant_and_db(tenant: SimpleNamespace, db_session: AsyncMock) -> None:
    async def _mock_get_db():
        yield db_session

    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_db] = _mock_get_db


def _headers(*, user: SimpleNamespace, tenant_slug: str, token_tenant: str | None = None) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        role="parent",
        tenant_slug=token_tenant or tenant_slug,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant_slug,
    }


def test_parent_authentication_required():
    tenant = _tenant()
    user = _parent_user(tenant_id=tenant.id)
    db = _db_with_execute_sequence([_result_scalar(user)])
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/parent/reports", headers={"X-Tenant-Slug": tenant.slug})
            assert response.status_code in {401, 403}
        finally:
            app.dependency_overrides.clear()


def test_parent_sees_only_published_reports_and_no_internal_fields():
    tenant = _tenant()
    parent = _parent_user(tenant_id=tenant.id)

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        status="published",
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 19),
        published_version_number=2,
        published_at=datetime.now(timezone.utc),
    )
    student = SimpleNamespace(id=report.student_id, name="Ahmed Hassan")
    klass = SimpleNamespace(grade="Grade 6", section="A")
    version = SimpleNamespace(content_json={"title": "Weekly Report", "sections": [{"section_type": "teacher_comment", "content": "Safe text"}]})

    db = _db_with_execute_sequence(
        [
            _result_scalar(parent),
            _result_all([(report, student, klass)]),
            _result_scalar(version),
        ]
    )
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/parent/reports", headers=_headers(user=parent, tenant_slug=tenant.slug))
            assert response.status_code == 200, response.text
            body = response.json()
            assert len(body) == 1
            assert "status" not in body[0]
            assert "current_evidence_snapshot" not in body[0]
            assert "validation_errors" not in body[0]
        finally:
            app.dependency_overrides.clear()


def test_parent_report_detail_hides_internal_review_fields():
    tenant = _tenant()
    parent = _parent_user(tenant_id=tenant.id)

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        status="published",
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 19),
        published_version_number=2,
        published_at=datetime.now(timezone.utc),
    )
    student = SimpleNamespace(id=report.student_id, name="Ahmed Hassan")
    klass = SimpleNamespace(grade="Grade 6", section="A")
    version = SimpleNamespace(
        content_json={
            "title": "Weekly Report",
            "sections": [{"section_type": "teacher_comment", "content": "No HTML"}],
            "validation_errors": [{"code": "internal"}],
            "evidence_ids": ["staff_input_1"],
        }
    )

    db = _db_with_execute_sequence(
        [
            _result_scalar(parent),
            _result_first((report, student, klass)),
            _result_scalar(version),
            _result_scalar(None),
        ]
    )
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.parent_reports.log_action",
        new=AsyncMock(),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(f"/parent/reports/{report.id}", headers=_headers(user=parent, tenant_slug=tenant.slug))
            assert response.status_code == 200, response.text
            detail = response.json()
            assert "sections" in detail
            assert "review_comments" not in detail
            assert "validation_errors" not in detail
            assert "evidence_snapshot" not in detail
        finally:
            app.dependency_overrides.clear()


def test_parent_cannot_read_other_family_or_unpublished_reports_uses_not_found():
    tenant = _tenant()
    parent = _parent_user(tenant_id=tenant.id)

    db = _db_with_execute_sequence(
        [
            _result_scalar(parent),
            _result_first(None),
        ]
    )
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    f"/parent/reports/{uuid.uuid4()}",
                    headers=_headers(user=parent, tenant_slug=tenant.slug),
                )
            assert response.status_code == 404
            assert response.json().get("detail") == "Report not found."
        finally:
            app.dependency_overrides.clear()


def test_parent_cannot_read_another_tenant_report():
    tenant = _tenant(slug="greenwood")
    parent = _parent_user(tenant_id=tenant.id)

    db = _db_with_execute_sequence([_result_scalar(parent)])
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    f"/parent/reports/{uuid.uuid4()}",
                    headers=_headers(user=parent, tenant_slug=tenant.slug, token_tenant="other-school"),
                )
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()


def test_parent_child_filtering_applies_validate_parent_student_access():
    tenant = _tenant()
    parent = _parent_user(tenant_id=tenant.id)

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        student_id=uuid.uuid4(),
        status="published",
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 19),
        published_version_number=1,
        published_at=datetime.now(timezone.utc),
    )
    student = SimpleNamespace(id=report.student_id, name="Fatimah Hassan")
    klass = SimpleNamespace(grade="Grade 4", section="B")
    version = SimpleNamespace(content_json={"title": "Weekly Report", "sections": []})

    db = _db_with_execute_sequence(
        [
            _result_scalar(parent),
            _result_scalar(SimpleNamespace(student_id=report.student_id)),
            _result_all([(report, student, klass)]),
            _result_scalar(version),
        ]
    )
    _override_tenant_and_db(tenant, db)

    with patch("services.gateway.routers.parent_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    f"/parent/reports?student_id={report.student_id}",
                    headers=_headers(user=parent, tenant_slug=tenant.slug),
                )
            assert response.status_code == 200
            assert len(response.json()) == 1
            assert response.json()[0]["student_id"] == str(report.student_id)
        finally:
            app.dependency_overrides.clear()
