from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from services.gateway.main import app
from shared.auth.jwt import create_access_token
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", settings={})


def _user(*, tenant_id: uuid.UUID, role: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        is_active=True,
        name=f"{role.title()} User",
        email=f"{role}@school.test",
    )


def _mock_db_for_user(user: SimpleNamespace) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session.execute = AsyncMock(return_value=result)
    session.add = lambda *_args, **_kwargs: None
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _override_auth(tenant: SimpleNamespace, db_session: AsyncMock) -> None:
    async def _mock_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant


def _report(status_value: str, *, row_version: int = 1, version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status_value,
        row_version=row_version,
        current_version_number=version,
    )


def _auth_headers(*, user: SimpleNamespace, tenant_slug: str, jwt_role: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        role=jwt_role or user.role,
        tenant_slug=tenant_slug,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant_slug,
    }
    if extra:
        headers.update(extra)
    return headers


def test_staff_jwt_authentication_required():
    tenant = _tenant()
    db = _mock_db_for_user(_user(tenant_id=tenant.id, role="teacher"))
    _override_auth(tenant, db)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/weekly-reports/init",
                    headers={"X-Tenant-Slug": tenant.slug},
                    json={"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"},
                )
            assert response.status_code in {401, 403}
        finally:
            app.dependency_overrides.clear()


def test_staff_identity_cannot_be_spoofed_by_headers():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    headers = _auth_headers(
        user=teacher,
        tenant_slug=tenant.slug,
        extra={"X-User-Role": "principal", "X-User-Id": str(uuid.uuid4())},
    )

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/approve",
                    headers=headers,
                    json={"expected_row_version": 1},
                )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_exact_supported_db_roles_are_enforced():
    tenant = _tenant()
    unsupported = _user(tenant_id=tenant.id, role="staff")
    db = _mock_db_for_user(unsupported)
    _override_auth(tenant, db)

    headers = _auth_headers(user=unsupported, tenant_slug=tenant.slug, jwt_role="teacher")

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/weekly-reports/init",
                    headers=headers,
                    json={"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"},
                )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_same_tenant_teacher_without_relationship_is_denied():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.initialize_report",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Student not found.")),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/weekly-reports/init",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"},
                )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_authorized_teacher_can_initialize_report():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    initialized = _report("draft", row_version=1, version=1)
    service_result = SimpleNamespace(report=initialized, created_version=None)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.initialize_report",
        new=AsyncMock(return_value=service_result),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/weekly-reports/init",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"},
                )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "draft"
            assert body["current_version_number"] == 1
        finally:
            app.dependency_overrides.clear()


def test_unauthorized_teacher_cannot_initialize_or_edit():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    init_side_effect = HTTPException(status_code=404, detail="Student not found.")
    edit_side_effect = HTTPException(status_code=404, detail="Student not found.")

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.initialize_report",
        new=AsyncMock(side_effect=init_side_effect),
    ), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.edit_report",
        new=AsyncMock(side_effect=edit_side_effect),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                init_response = client.post(
                    "/weekly-reports/init",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"},
                )
                edit_response = client.patch(
                    f"/weekly-reports/{uuid.uuid4()}/draft",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={
                        "expected_row_version": 1,
                        "title": "Weekly Report",
                        "sections": [{"section_type": "teacher_comment", "content": "Plain text"}],
                    },
                )
            assert init_response.status_code == 404
            assert edit_response.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_teacher_can_generate_edit_and_submit_for_review():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    generated = _report("pending_review", row_version=3, version=2)
    edited = _report("pending_review", row_version=4, version=3)
    submitted = _report("pending_review", row_version=5, version=3)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.get_provider",
        return_value=SimpleNamespace(provider_name="deterministic"),
    ), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.generate_draft",
        new=AsyncMock(return_value=SimpleNamespace(report=generated, created_version=None)),
    ), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.edit_report",
        new=AsyncMock(return_value=SimpleNamespace(report=edited, created_version=None)),
    ), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.submit_for_review",
        new=AsyncMock(return_value=submitted),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                generate_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/generate",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"expected_row_version": 1, "use_ai": True},
                )
                edit_response = client.patch(
                    f"/weekly-reports/{uuid.uuid4()}/draft",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={
                        "expected_row_version": 3,
                        "title": "Updated",
                        "sections": [{"section_type": "teacher_comment", "content": "Updated text"}],
                    },
                )
                submit_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/submit-review",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"expected_row_version": 4, "comment": "Ready"},
                )
            assert generate_response.status_code == 200
            assert edit_response.status_code == 200
            assert submit_response.status_code == 200
        finally:
            app.dependency_overrides.clear()


def test_teacher_cannot_approve_or_publish():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    headers = _auth_headers(user=teacher, tenant_slug=tenant.slug)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                approve_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/approve",
                    headers=headers,
                    json={"expected_row_version": 1},
                )
                publish_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/publish",
                    headers=headers,
                    json={"expected_row_version": 1},
                )
            assert approve_response.status_code == 403
            assert publish_response.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_leadership_can_request_changes_and_approve():
    tenant = _tenant()
    principal = _user(tenant_id=tenant.id, role="principal")
    db = _mock_db_for_user(principal)
    _override_auth(tenant, db)

    changes_requested = _report("changes_requested", row_version=6, version=3)
    approved = _report("approved", row_version=7, version=3)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.request_changes",
        new=AsyncMock(return_value=changes_requested),
    ), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.approve",
        new=AsyncMock(return_value=approved),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                changes_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/request-changes",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 5, "comment": "Revise section 2"},
                )
                approve_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/approve",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 6, "comment": "Approved"},
                )
            assert changes_response.status_code == 200
            assert approve_response.status_code == 200
        finally:
            app.dependency_overrides.clear()


def test_self_approval_rejected():
    tenant = _tenant()
    principal = _user(tenant_id=tenant.id, role="principal")
    db = _mock_db_for_user(principal)
    _override_auth(tenant, db)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.approve",
        new=AsyncMock(side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers cannot approve their own reports.")),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/approve",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 4},
                )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_draft_and_pending_review_cannot_be_published_and_only_approved_can_publish():
    tenant = _tenant()
    principal = _user(tenant_id=tenant.id, role="principal")
    db = _mock_db_for_user(principal)
    _override_auth(tenant, db)

    blocked_publish = HTTPException(status_code=409, detail="Report must be approved before publication.")
    published = _report("published", row_version=9, version=4)

    publish_mock = AsyncMock(side_effect=[blocked_publish, blocked_publish, published])

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.publish",
        new=publish_mock,
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                draft_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/publish",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 2},
                )
                pending_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/publish",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 3},
                )
                approved_response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/publish",
                    headers=_auth_headers(user=principal, tenant_slug=tenant.slug),
                    json={"expected_row_version": 8},
                )
            assert draft_response.status_code == 409
            assert pending_response.status_code == 409
            assert approved_response.status_code == 200
        finally:
            app.dependency_overrides.clear()


def test_editing_approved_or_published_creates_new_version_and_requires_reapproval():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    edited = _report("pending_review", row_version=11, version=5)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.edit_report",
        new=AsyncMock(return_value=SimpleNamespace(report=edited, created_version=None)),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.patch(
                    f"/weekly-reports/{uuid.uuid4()}/draft",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={
                        "expected_row_version": 10,
                        "title": "Revised",
                        "sections": [{"section_type": "teacher_comment", "content": "Revision text"}],
                    },
                )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "pending_review"
            assert body["current_version_number"] == 5
        finally:
            app.dependency_overrides.clear()


def test_stale_row_version_returns_http_409():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.submit_for_review",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="The report was updated by another user.")),
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/weekly-reports/{uuid.uuid4()}/submit-review",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json={"expected_row_version": 1},
                )
            assert response.status_code == 409
        finally:
            app.dependency_overrides.clear()


def test_initialization_is_idempotent_and_archived_report_blocks_duplicate_logical_report():
    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_db_for_user(teacher)
    _override_auth(tenant, db)

    same_report_id = uuid.uuid4()
    first = _report("draft", row_version=1, version=1)
    first.id = same_report_id
    archived_existing = _report("archived", row_version=4, version=2)
    archived_existing.id = same_report_id

    initialize_mock = AsyncMock(side_effect=[SimpleNamespace(report=first, created_version=None), SimpleNamespace(report=archived_existing, created_version=None)])

    with patch("services.gateway.routers.weekly_reports.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.weekly_reports.WeeklyReportService.initialize_report",
        new=initialize_mock,
    ):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                body = {"student_id": str(uuid.uuid4()), "week_start": "2026-07-13"}
                first_response = client.post(
                    "/weekly-reports/init",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json=body,
                )
                second_response = client.post(
                    "/weekly-reports/init",
                    headers=_auth_headers(user=teacher, tenant_slug=tenant.slug),
                    json=body,
                )
            assert first_response.status_code == 200
            assert second_response.status_code == 200
            assert first_response.json()["report_id"] == second_response.json()["report_id"]
        finally:
            app.dependency_overrides.clear()
