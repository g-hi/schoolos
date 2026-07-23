from __future__ import annotations

import importlib.util
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.gateway.announcements import (
    LEGAL_TRANSITIONS,
    claim_due_announcement_ids,
    claim_due_notification_ids,
    deliver_notification,
    resolve_recipients,
    validate_scheduled_at,
    validate_target,
    validate_timezone,
    validate_transition,
    publish_announcement,
)
from services.gateway.routers.announcements import router as announcements_router
from services.gateway.routers.announcements import AnnouncementCreateRequest, AnnouncementTargetRequest, list_announcement_target_options, list_parent_notifications, mark_all_parent_notifications_read
from shared.auth.dependencies import resolve_authenticated_leadership, resolve_authenticated_parent
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import Announcement, AnnouncementTarget, Notification


def result(*, scalar=None, rows=None, first=None):
    return SimpleNamespace(
        scalar_one=lambda: scalar,
        scalar_one_or_none=lambda: scalar,
        scalars=lambda: SimpleNamespace(all=lambda: rows or []),
        all=lambda: rows or ([] if first is None else [first]),
        first=lambda: first,
    )


class Transaction:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("rollback" if exc_type else "commit")


def test_orm_model_parity_and_constraints() -> None:
    assert {"id", "tenant_id", "author_user_id", "title", "body", "status", "scheduled_at", "published_at", "archived_at", "publication_claimed_at", "publication_claimed_by"} <= {c.name for c in Announcement.__table__.columns}
    assert {"announcement_id", "target_type", "target_key", "grade", "class_id", "family_id", "student_id"} <= {c.name for c in AnnouncementTarget.__table__.columns}
    assert {"recipient_user_id", "announcement_id", "delivery_status", "read_at", "attempt_count"} <= {c.name for c in Notification.__table__.columns}
    status_constraint = next(c for c in Announcement.__table__.constraints if (getattr(c, "name", "") or "").endswith("valid_announcement_status"))
    assert "publishing" in str(status_constraint.sqltext)
    names = {getattr(c, "name", None) for c in AnnouncementTarget.__table__.constraints}
    assert any(name and name.endswith("valid_announcement_target_shape") for name in names)
    assert "uq_announcement_target_key" in names
    assert any(name and name.endswith("uq_announcement_notification_recipient") for name in {getattr(c, "name", None) for c in Notification.__table__.constraints})


def test_migration_chain_and_upgrade_downgrade_structure() -> None:
    path = Path("alembic/versions/c85b_announcements_phase_85b.py")
    spec = importlib.util.spec_from_file_location("phase_85b_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "b6d4fe19f7c2"
    op = MagicMock()
    with patch.object(migration, "op", op):
        migration.upgrade()
        migration.downgrade()
    assert op.create_table.call_args_list[0].args[0] == "announcements"
    assert {call.args[0] for call in op.create_table.call_args_list} >= {"announcements", "announcement_targets", "notifications"}
    announcement_columns = [arg.name for arg in op.create_table.call_args_list[0].args[1:] if hasattr(arg, "name")]
    target_columns = [arg.name for arg in op.create_table.call_args_list[1].args[1:] if hasattr(arg, "name")]
    assert "publication_claimed_at" in announcement_columns
    assert "publication_claimed_by" in announcement_columns
    assert "target_key" in target_columns
    assert op.drop_table.call_args_list[-1].args[0] == "announcements"


def test_target_schema_rejects_mismatched_columns() -> None:
    with pytest.raises(ValidationError):
        AnnouncementTargetRequest(target_type="school", grade="Grade 1")
    with pytest.raises(HTTPException):
        validate_target("grade", class_id=uuid.uuid4(), grade="Grade 1")
    validate_target("school")
    validate_target("grade", grade="Grade 1")
    validate_target("class", class_id=uuid.uuid4())
    validate_target("family", family_id=uuid.uuid4())
    validate_target("student", student_id=uuid.uuid4())


def test_target_key_builder_generates_stable_keys() -> None:
    from services.gateway.routers.announcements import _target_key_from_request

    class_id = uuid.uuid4()
    family_id = uuid.uuid4()
    student_id = uuid.uuid4()
    assert _target_key_from_request(AnnouncementTargetRequest(target_type="school")) == "school"
    assert _target_key_from_request(AnnouncementTargetRequest(target_type="grade", grade="Grade 4")) == "grade:Grade 4"
    assert _target_key_from_request(AnnouncementTargetRequest(target_type="class", class_id=class_id)) == f"class:{class_id}"
    assert _target_key_from_request(AnnouncementTargetRequest(target_type="family", family_id=family_id)) == f"family:{family_id}"
    assert _target_key_from_request(AnnouncementTargetRequest(target_type="student", student_id=student_id)) == f"student:{student_id}"


def test_scheduling_validation_and_lifecycle_matrix() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    validate_timezone("UTC")
    validate_scheduled_at(future)
    with pytest.raises(HTTPException):
        validate_timezone("Invalid/Zone")
    with pytest.raises(HTTPException):
        validate_scheduled_at(datetime.now(timezone.utc))
    assert LEGAL_TRANSITIONS["draft"] == {"scheduled", "published"}
    assert LEGAL_TRANSITIONS["scheduled"] == {"draft", "published"}
    assert LEGAL_TRANSITIONS["published"] == {"archived"}
    for current, target in [("draft", "scheduled"), ("draft", "published"), ("scheduled", "draft"), ("scheduled", "published"), ("published", "archived")]:
        validate_transition(current, target)
    for current, target in [("archived", "draft"), ("published", "draft"), ("draft", "archived"), ("scheduled", "archived")]:
        with pytest.raises(HTTPException):
            validate_transition(current, target)


def test_leadership_dependency_allows_principal_and_school_admin_but_denies_parent_and_teacher() -> None:
    from shared.auth.dependencies import require_role
    import asyncio

    dependency = require_role("principal", "school_admin")
    asyncio.run(dependency(current_user=SimpleNamespace(role="principal")))
    asyncio.run(dependency(current_user=SimpleNamespace(role="school_admin")))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(current_user=SimpleNamespace(role="parent")))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(dependency(current_user=SimpleNamespace(role="teacher")))
    assert exc2.value.status_code == 403


def test_communication_routes_require_leadership_dependency() -> None:
    from services.gateway.routers.communication import router
    from shared.auth.dependencies import resolve_authenticated_leadership

    protected_routes = {
        ("POST", "/communication/daily-digest"),
        ("POST", "/communication/broadcast"),
        ("GET", "/communication/log"),
        ("GET", "/communication/stats"),
        ("GET", "/communication/grades"),
        ("GET", "/communication/agents"),
    }
    prefixed_routes = {(next(iter(route.methods)), route.path) for route in router.routes if getattr(route, "methods", None)}
    for method, path in protected_routes:
        route = next((route for route in router.routes if getattr(route, "path", None) == path and method in getattr(route, "methods", set())), None)
        assert route is not None, f"missing route: {method} {path}"
        assert (method, path) in prefixed_routes
        dependency_calls = {dep.call for dep in route.dependant.dependencies}
        assert resolve_authenticated_leadership in dependency_calls


def test_announcement_target_options_route_requires_leadership_dependency() -> None:
    route = next((r for r in announcements_router.routes if getattr(r, "path", None) == "/announcements/target-options" and "GET" in getattr(r, "methods", set())), None)
    assert route is not None
    dependency_calls = {dep.call for dep in route.dependant.dependencies}
    assert resolve_authenticated_leadership in dependency_calls


def test_target_options_request_resolves_static_route() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(rows=[("Grade 1", "A"), ("Grade 1", "B")])

    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_leadership] = lambda: SimpleNamespace(id=uuid.uuid4(), role="principal")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/announcements/target-options", params={"target_type": "grade"})
        assert response.status_code == 200
        assert response.json()["items"][0]["target_value"] == "Grade 1"
    finally:
        app.dependency_overrides.clear()


def test_target_options_request_denies_non_leadership() -> None:
    tenant_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield AsyncMock()

    async def _deny_leadership():
        raise HTTPException(status_code=403, detail="Forbidden")

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_leadership] = _deny_leadership
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/announcements/target-options", params={"target_type": "grade"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recipient_resolution_deduplicates_parent_across_children_and_targets() -> None:
    tenant_id = uuid.uuid4()
    parent = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="parent", is_active=True)
    db = AsyncMock()
    db.execute.return_value = result(rows=[parent])
    targets = [
        AnnouncementTarget(tenant_id=tenant_id, announcement_id=uuid.uuid4(), target_type="school"),
        AnnouncementTarget(tenant_id=tenant_id, announcement_id=uuid.uuid4(), target_type="student", student_id=uuid.uuid4()),
    ]
    with patch("services.gateway.announcements._validate_target_tenant", new=AsyncMock()):
        recipients = await resolve_recipients(db, tenant_id, targets)
    assert [user.id for user in recipients] == [parent.id]
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_target_tenant_validation_rejects_cross_tenant_target() -> None:
    from services.gateway.announcements import _validate_target_tenant
    target = AnnouncementTarget(tenant_id=uuid.uuid4(), announcement_id=uuid.uuid4(), target_type="class", class_id=uuid.uuid4())
    db = AsyncMock()
    db.execute.return_value = result(scalar=None)
    with pytest.raises(HTTPException) as exc:
        await _validate_target_tenant(db, uuid.uuid4(), target)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_delivery_failure_rolls_back_delivery_side_transaction_and_logs_safe_warning(caplog) -> None:
    events = []
    db = AsyncMock()
    db.begin = lambda: Transaction(events)
    tenant_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    db.execute.side_effect = [
        result(scalar=Notification(id=uuid.uuid4(), tenant_id=tenant_id, recipient_user_id=recipient_id, title="Title", body="Body", attempt_count=0)),
        result(scalar=None),
    ]
    db.get.return_value = SimpleNamespace(id=recipient_id, tenant_id=tenant_id, preferred_channel="sms")
    db.rollback = AsyncMock()
    with patch("services.gateway.announcements.send_to_user", new=AsyncMock(side_effect=RuntimeError("provider payload"))), caplog.at_level(logging.WARNING):
        with pytest.raises(Exception):
            await deliver_notification(db, uuid.uuid4(), tenant_id)
    assert "begin" in events
    assert "rollback" in events
    assert "provider payload" not in caplog.text
    assert "announcement notification delivery failed" in caplog.text
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_due_claim_uses_skip_locked_and_only_due_scheduled_rows() -> None:
    events = []
    db = AsyncMock()
    db.begin = lambda: Transaction(events)
    announcements = [
        Announcement(id=uuid.uuid4(), tenant_id=uuid.uuid4(), author_user_id=uuid.uuid4(), title="A", body="A", status="scheduled", timezone="UTC"),
        Announcement(id=uuid.uuid4(), tenant_id=uuid.uuid4(), author_user_id=uuid.uuid4(), title="B", body="B", status="scheduled", timezone="UTC"),
    ]
    db.execute.return_value = result(rows=announcements)
    claimed = await claim_due_announcement_ids(db, uuid.uuid4(), limit=2, claimant_id="worker-1")
    assert claimed == [ann.id for ann in announcements]
    assert all(ann.status == "publishing" for ann in announcements)
    assert all(ann.publication_claimed_by == "worker-1" for ann in announcements)
    assert all(ann.publication_claimed_at is not None for ann in announcements)
    assert events == ["begin", "commit"]
    statement = db.execute.call_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(compile_kwargs={"literal_binds": True})).upper()


@pytest.mark.asyncio
async def test_due_notification_claim_uses_retryable_status_and_due_time() -> None:
    events = []
    db = AsyncMock()
    db.begin = lambda: Transaction(events)
    notifications = [
        Notification(id=uuid.uuid4(), tenant_id=uuid.uuid4(), recipient_user_id=uuid.uuid4(), title="A", body="A", delivery_status="failed"),
        Notification(id=uuid.uuid4(), tenant_id=uuid.uuid4(), recipient_user_id=uuid.uuid4(), title="B", body="B", delivery_status="pending"),
    ]
    db.execute.return_value = result(rows=notifications)
    claimed = await claim_due_notification_ids(db, uuid.uuid4(), limit=5)
    assert claimed == [row.id for row in notifications]
    statement = db.execute.call_args.args[0]
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "FOR UPDATE" in rendered
    assert "DELIVERY_STATUS" in rendered


@pytest.mark.asyncio
async def test_parent_visibility_requires_recipient_notification() -> None:
    from services.gateway.routers.announcements import get_parent_announcement
    db = AsyncMock()
    db.execute.return_value = result(first=None)
    with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await get_parent_announcement(uuid.uuid4(), tenant=SimpleNamespace(id=uuid.uuid4()), parent=SimpleNamespace(id=uuid.uuid4()), db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_publication_creates_snapshot_once_and_writes_audit_and_timeline() -> None:
    tenant_id = uuid.uuid4()
    announcement_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    family_id = uuid.uuid4()
    announcement = Announcement(id=announcement_id, tenant_id=tenant_id, author_user_id=uuid.uuid4(), title="Closure", body="School is closed", status="draft", timezone="UTC")
    target = AnnouncementTarget(id=uuid.uuid4(), tenant_id=tenant_id, announcement_id=announcement_id, target_type="school")
    parent = SimpleNamespace(id=parent_id, tenant_id=tenant_id, role="parent", is_active=True)
    notification = Notification(id=uuid.uuid4(), tenant_id=tenant_id, announcement_id=announcement_id, recipient_user_id=parent_id, title="Closure", body="School is closed")
    db = AsyncMock()
    db.begin = lambda: Transaction([])
    db.get_bind = MagicMock(return_value=MagicMock())
    db.add = MagicMock()
    db.execute.side_effect = [
        result(scalar=announcement),
        result(rows=[target]),
        result(rows=[parent]),
        result(rows=[]),
        result(rows=[notification.id]),
    ]
    audit = AsyncMock()
    timeline = AsyncMock()
    with (
        patch("services.gateway.announcements._validate_target_tenant", new=AsyncMock()),
        patch("services.gateway.announcements._write_publication_side_effects", new=AsyncMock()) as side_effects,
        patch("services.gateway.announcements.deliver_notification", new=AsyncMock()),
    ):
        published = await publish_announcement(db, tenant_id, announcement_id)
    assert published.status == "published"
    assert published.published_at is not None
    db.add.assert_called_once()
    side_effects.assert_awaited_once()


@pytest.mark.asyncio
async def test_republishing_published_announcement_is_idempotent() -> None:
    announcement = Announcement(id=uuid.uuid4(), tenant_id=uuid.uuid4(), author_user_id=uuid.uuid4(), title="Already live", body="Body", status="published", published_at=datetime.now(timezone.utc), timezone="UTC")
    db = AsyncMock()
    db.begin = lambda: Transaction([])
    db.execute.return_value = result(scalar=announcement)
    published = await publish_announcement(db, announcement.tenant_id, announcement.id)
    assert published is announcement
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_preference_disabled_delivery_is_recorded_skipped() -> None:
    notification = Notification(id=uuid.uuid4(), tenant_id=uuid.uuid4(), recipient_user_id=uuid.uuid4(), title="Title", body="Body", attempt_count=0)
    user = SimpleNamespace(id=notification.recipient_user_id, tenant_id=notification.tenant_id, preferred_channel="email")
    preferences = SimpleNamespace(email_notifications=False, in_app_notifications=True)
    db = AsyncMock()
    db.begin = lambda: Transaction([])
    db.execute.side_effect = [result(scalar=notification), result(scalar=preferences)]
    db.get.return_value = user
    with patch("services.gateway.announcements.send_to_user", new=AsyncMock()) as send:
        updated = await deliver_notification(db, notification.id, notification.tenant_id)
    assert updated.delivery_status == "skipped"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_failure_sets_retry_metadata_and_safe_error_code() -> None:
    notification = Notification(id=uuid.uuid4(), tenant_id=uuid.uuid4(), recipient_user_id=uuid.uuid4(), title="Title", body="Body", attempt_count=0)
    user = SimpleNamespace(id=notification.recipient_user_id, tenant_id=notification.tenant_id, preferred_channel="sms")
    db = AsyncMock()
    db.begin = lambda: Transaction([])
    db.execute.side_effect = [result(scalar=notification), result(scalar=None)]
    db.get.return_value = user
    with patch("services.gateway.announcements.send_to_user", new=AsyncMock(return_value=SimpleNamespace(status="failed", error="twilio_error"))):
        updated = await deliver_notification(db, notification.id, notification.tenant_id)
    assert updated.delivery_status == "failed"
    assert updated.last_error_code == "TWILIO_ERROR"
    assert updated.next_attempt_at is not None


@pytest.mark.asyncio
async def test_publish_accepts_publishing_state_and_clears_claim_fields() -> None:
    tenant_id = uuid.uuid4()
    announcement = Announcement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        author_user_id=uuid.uuid4(),
        title="Live",
        body="Body",
        status="publishing",
        timezone="UTC",
        publication_claimed_at=datetime.now(timezone.utc),
        publication_claimed_by="worker",
    )
    target = AnnouncementTarget(id=uuid.uuid4(), tenant_id=tenant_id, announcement_id=announcement.id, target_type="school", target_key="school")
    db = AsyncMock()
    db.begin = lambda: Transaction([])
    db.get_bind = MagicMock(return_value=MagicMock())
    db.add = MagicMock()
    db.execute.side_effect = [result(scalar=announcement), result(rows=[target]), result(rows=[])]
    with (
        patch("services.gateway.announcements._write_publication_side_effects", new=AsyncMock()),
        patch("services.gateway.announcements.resolve_recipients", new=AsyncMock(return_value=[])),
    ):
        published = await publish_announcement(db, tenant_id, announcement.id)
    assert published.status == "published"
    assert published.publication_claimed_at is None
    assert published.publication_claimed_by is None


@pytest.mark.asyncio
async def test_parent_read_all_only_updates_own_tenant_notifications() -> None:
    parent_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    rows = [Notification(id=uuid.uuid4(), tenant_id=tenant_id, recipient_user_id=parent_id, title="A", body="A"), Notification(id=uuid.uuid4(), tenant_id=tenant_id, recipient_user_id=parent_id, title="B", body="B")]
    db = AsyncMock()
    db.execute.return_value = result(rows=rows)
    with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
        response = await mark_all_parent_notifications_read(tenant=SimpleNamespace(id=tenant_id), parent=SimpleNamespace(id=parent_id), db=db)
    assert response == {"updated": 2}
    assert all(row.read_at is not None for row in rows)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_parent_notification_list_supports_unread_filter_and_pagination() -> None:
    parent_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    row = Notification(id=uuid.uuid4(), tenant_id=tenant_id, recipient_user_id=parent_id, title="A", body="B")
    db = AsyncMock()
    db.execute.return_value = result(rows=[row])
    with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
        response = await list_parent_notifications(read=False, page=2, page_size=1, tenant=SimpleNamespace(id=tenant_id), parent=SimpleNamespace(id=parent_id), db=db)
    assert response["page"] == 2
    assert response["page_size"] == 1
    assert response["items"][0]["read_at"] is None


def test_notification_snapshot_has_one_announcement_recipient_key() -> None:
    constraint_names = {getattr(c, "name", None) for c in Notification.__table__.constraints}
    assert any(name and name.endswith("uq_announcement_notification_recipient") for name in constraint_names)


def test_parent_create_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AnnouncementCreateRequest(title="Title", body="Body", targets=[{"target_type": "school"}], author_user_id=uuid.uuid4())


def test_parent_notifications_unread_count_route_requires_parent_dependency() -> None:
    from services.gateway.routers.announcements import router
    from shared.auth.dependencies import resolve_authenticated_parent

    route = next((r for r in router.routes if getattr(r, "path", None) == "/parent/notifications/unread-count" and "GET" in getattr(r, "methods", set())), None)
    assert route is not None
    dependency_calls = {dep.call for dep in route.dependant.dependencies}
    assert resolve_authenticated_parent in dependency_calls


def test_parent_role_dependency_denies_non_parent_for_unread_count() -> None:
    from shared.auth.dependencies import require_role
    import asyncio

    dependency = require_role("parent")
    asyncio.run(dependency(current_user=SimpleNamespace(role="parent")))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(current_user=SimpleNamespace(role="teacher")))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_parent_unread_count_returns_zero_when_no_unread() -> None:
    from services.gateway.routers.announcements import get_parent_unread_notification_count

    tenant_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(scalar=0)
    with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
        response = await get_parent_unread_notification_count(
            tenant=SimpleNamespace(id=tenant_id),
            parent=SimpleNamespace(id=parent_id),
            db=db,
        )
    assert response == {"unread_count": 0}


@pytest.mark.asyncio
async def test_announcement_target_options_return_expected_target_value_formats() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    class_id = uuid.uuid4()
    family_id = uuid.uuid4()
    student_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_leadership] = lambda: SimpleNamespace(id=uuid.uuid4(), role="principal")
    db.execute.side_effect = [
        result(rows=[("Grade 1", "A"), ("Grade 1", "B"), ("Grade 2", "A")]),
        result(rows=[(class_id, "Grade 1", "A", "2025-2026")]),
        result(rows=[(family_id, "Family One", "Student One", "Grade 1", "A")]),
        result(rows=[(student_id, "Student One", "Grade 1", "A", "Family One")]),
    ]
    try:
        with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
            with TestClient(app, raise_server_exceptions=False) as client:
                grade_response = client.get("/announcements/target-options", params={"target_type": "grade"})
                class_response = client.get("/announcements/target-options", params={"target_type": "class"})
                family_response = client.get("/announcements/target-options", params={"target_type": "family"})
                student_response = client.get("/announcements/target-options", params={"target_type": "student"})

        assert grade_response.status_code == 200
        assert grade_response.json()["items"][0]["target_type"] == "grade"
        assert grade_response.json()["items"][0]["target_value"] == "Grade 1"
        assert grade_response.json()["items"][0]["label"] == "Grade 1"
        assert grade_response.json()["items"][0]["secondary_label"] == "A, B"

        assert class_response.status_code == 200
        assert class_response.json()["items"][0]["target_value"] == str(class_id)
        assert family_response.status_code == 200
        assert family_response.json()["items"][0]["target_value"] == str(family_id)
        assert student_response.status_code == 200
        assert student_response.json()["items"][0]["target_value"] == str(student_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_announcement_target_options_apply_search_filters_and_limit() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(rows=[(uuid.uuid4(), "Student Alpha", "Grade 1", "A", "Family Alpha"), (uuid.uuid4(), "Student Beta", "Grade 1", "B", "Family Beta")])
    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_leadership] = lambda: SimpleNamespace(id=uuid.uuid4(), role="principal")
    try:
        with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/announcements/target-options", params={"target_type": "student", "q": "alpha", "limit": 1})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["label"] == "Student Alpha"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_announcement_target_options_remain_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(rows=[("Grade 3", "C")])
    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_leadership] = lambda: SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    try:
        with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/announcements/target-options", params={"target_type": "grade"})
        assert response.status_code == 200
        statement = db.execute.call_args.args[0]
        rendered = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "TENANT_ID" in rendered
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_parent_unread_count_excludes_read_and_isolation_filters() -> None:
    from services.gateway.routers.announcements import get_parent_unread_notification_count

    tenant_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(scalar=3)
    with patch("services.gateway.routers.announcements.set_tenant_context", new=AsyncMock()):
        response = await get_parent_unread_notification_count(
            tenant=SimpleNamespace(id=tenant_id),
            parent=SimpleNamespace(id=parent_id),
            db=db,
        )
    assert response == {"unread_count": 3}
    statement = db.execute.call_args.args[0]
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "COUNT(" in rendered
    assert "TENANT_ID" in rendered
    assert "RECIPIENT_USER_ID" in rendered
    assert "READ_AT IS NULL" in rendered


def test_unread_count_request_route_resolves_static_endpoint_not_dynamic() -> None:
    tenant_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = result(scalar=0)

    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_parent] = lambda: SimpleNamespace(id=parent_id, role="parent")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/parent/notifications/unread-count")
        assert response.status_code == 200
        assert response.json() == {"unread_count": 0}
    finally:
        app.dependency_overrides.clear()


def test_unread_count_request_denies_non_parent() -> None:
    tenant_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(announcements_router)

    async def _mock_get_db():
        yield AsyncMock()

    async def _deny_parent():
        raise HTTPException(status_code=403, detail="Forbidden")

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_parent] = _deny_parent
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/parent/notifications/unread-count")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
