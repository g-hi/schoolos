from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from shared.config import settings
from tests.parent.conftest import make_parent_token, make_parent_user, make_tenant


@pytest.fixture(autouse=True)
def _use_memory_checkpoint_backend():
    original_backend = settings.copilot_checkpoint_backend
    settings.copilot_checkpoint_backend = "memory"
    try:
        yield
    finally:
        settings.copilot_checkpoint_backend = original_backend


def _install_parent_assistant_overrides(app, *, tenant, parent, db_session):
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant
    from shared.auth.dependencies import resolve_authenticated_parent

    async def mock_get_db():
        yield db_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_parent] = lambda: parent


def test_parent_assistant_run_requires_bearer():
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant

    tenant = make_tenant()

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/parent/assistant/run",
                headers={"X-Tenant-Slug": tenant.slug},
                json={"message": "Summarize my family."},
            )
        assert response.status_code in {401, 403}, response.text
    finally:
        app.dependency_overrides.clear()


def test_parent_assistant_run_returns_safe_unavailable_for_missing_family():
    from services.gateway.main import app

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    token = make_parent_token(str(parent.id), tenant.slug)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        MagicMock(),
        MagicMock(scalar_one_or_none=MagicMock(return_value=parent)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(all=MagicMock(return_value=[])),
    ])
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    _install_parent_assistant_overrides(app, tenant=tenant, parent=parent, db_session=mock_session)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/parent/assistant/run",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
                json={"message": "Summarize my family."},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["unavailable_reason"] == "missing_family"
    finally:
        app.dependency_overrides.clear()


def test_parent_assistant_continue_is_workflow_scoped_to_owner():
    from services.gateway.main import app
    from services.gateway.routers.parent_assistant import service

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    token = make_parent_token(str(parent.id), tenant.slug)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    _install_parent_assistant_overrides(app, tenant=tenant, parent=parent, db_session=mock_session)
    try:
        service._memory_checkpoint_store._data[(str(tenant.id), "req-1")] = (
            {
                "tenant_id": str(tenant.id),
                "tenant_slug": tenant.slug,
                "user_id": str(uuid.uuid4()),
                "user_role": "parent",
                "intent": "parent_assistant",
                "request_id": "req-1",
                "conversation_id": "conv-1",
                "structured_input": {},
                "school_context": {},
                "original_message": "Summarize my family.",
                "final_response": {
                    "status": "needs_clarification",
                    "request_id": "req-1",
                    "message": "Which child do you mean?",
                    "execution": {
                        "workflow": "parent_assistant",
                        "current_step": "parent_student_resolution",
                        "validation_passed": False,
                        "retry_count": 0,
                        "tenant_slug": tenant.slug,
                    },
                },
            },
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/parent/assistant/continue",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
                json={"request_id": "req-1", "message": "Ahmed"},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "error"
        assert body["message"] == "No workflow state found for this request."
    finally:
        service._memory_checkpoint_store._data.clear()
        app.dependency_overrides.clear()


def test_parent_assistant_status_rejects_teacher_checkpoint():
    from services.gateway.main import app
    from services.gateway.routers.parent_assistant import service

    tenant = make_tenant()
    parent = make_parent_user(tenant.id)
    token = make_parent_token(str(parent.id), tenant.slug)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    _install_parent_assistant_overrides(app, tenant=tenant, parent=parent, db_session=mock_session)
    try:
        service._memory_checkpoint_store._data[(str(tenant.id), "req-2")] = (
            {
                "tenant_id": str(tenant.id),
                "tenant_slug": tenant.slug,
                "user_id": str(parent.id),
                "user_role": "teacher",
                "intent": "lesson_planning",
                "request_id": "req-2",
                "conversation_id": "conv-2",
                "structured_input": {},
                "school_context": {},
                "original_message": "Create lesson",
                "final_response": {
                    "status": "pending_review",
                    "request_id": "req-2",
                    "message": "Lesson ready",
                    "execution": {
                        "workflow": "lesson_planning",
                        "current_step": "human_approval",
                        "validation_passed": True,
                        "retry_count": 0,
                        "tenant_slug": tenant.slug,
                    },
                },
            },
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/parent/assistant/status/req-2",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "error"
        assert body["message"] == "No workflow state found for this request."
    finally:
        service._memory_checkpoint_store._data.clear()
        app.dependency_overrides.clear()