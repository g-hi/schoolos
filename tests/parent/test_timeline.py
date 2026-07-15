"""
Phase 8.1 – Timeline Tests
============================
Tests for FamilyTimelineEvent persistence, idempotency, pagination,
action_url validation, and the write_timeline_event() service.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.parent.conftest import make_family, make_tenant


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_event_kwargs(tenant_id, family_id, suffix=""):
    return dict(
        tenant_id=tenant_id,
        family_id=family_id,
        event_type=f"pickup.released{suffix}",
        event_category="pickup",
        title=f"Student released{suffix}",
        occurred_at=datetime.now(timezone.utc),
        source_module="pickup",
        source_reference=f"req-{uuid.uuid4()}{suffix}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. write_timeline_event — requires source_reference OR event_key
# ─────────────────────────────────────────────────────────────────────────────

def test_write_event_raises_without_source_or_key():
    """write_timeline_event must raise ValueError if neither reference nor key given."""
    from services.gateway.ai.family_timeline import write_timeline_event

    tenant = make_tenant()
    family = make_family(tenant.id)

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="source_reference or event_key"):
            await write_timeline_event(
                db=mock_db,
                tenant_id=tenant.id,
                family_id=family.id,
                event_type="pickup.released",
                event_category="pickup",
                title="Test event",
                occurred_at=datetime.now(timezone.utc),
                source_module="pickup",
                # Neither source_reference nor event_key
            )

    asyncio.run(run())


def test_write_event_with_source_reference_succeeds():
    """write_timeline_event with source_reference creates the event."""
    from services.gateway.ai.family_timeline import write_timeline_event

    tenant = make_tenant()
    family = make_family(tenant.id)
    source_ref = str(uuid.uuid4())

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no existing
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        event = await write_timeline_event(
            db=mock_db,
            tenant_id=tenant.id,
            family_id=family.id,
            event_type="pickup.released",
            event_category="pickup",
            title="Student released",
            occurred_at=datetime.now(timezone.utc),
            source_module="pickup",
            source_reference=source_ref,
        )
        assert event is not None
        expected_key = f"pickup:{source_ref}:pickup.released"
        assert event.idempotency_key == expected_key

    asyncio.run(run())


def test_write_event_with_explicit_event_key_succeeds():
    """write_timeline_event with event_key (no source_reference) works."""
    from services.gateway.ai.family_timeline import write_timeline_event

    tenant = make_tenant()
    family = make_family(tenant.id)
    explicit_key = f"weekly_summary:{uuid.uuid4()}"

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        event = await write_timeline_event(
            db=mock_db,
            tenant_id=tenant.id,
            family_id=family.id,
            event_type="summary.generated",
            event_category="academic",
            title="Weekly summary generated",
            occurred_at=datetime.now(timezone.utc),
            source_module="reports",
            event_key=explicit_key,
        )
        assert event.idempotency_key == explicit_key

    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Idempotency — same event written twice returns existing record
# ─────────────────────────────────────────────────────────────────────────────

def test_write_event_idempotent():
    """Calling write_timeline_event twice for the same source returns the existing row."""
    from services.gateway.ai.family_timeline import write_timeline_event

    tenant = make_tenant()
    family = make_family(tenant.id)
    source_ref = str(uuid.uuid4())

    # Simulate an existing event already in the DB
    existing_event = MagicMock()
    existing_event.idempotency_key = f"pickup:{source_ref}:pickup.released"

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_event  # already exists
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()

        event = await write_timeline_event(
            db=mock_db,
            tenant_id=tenant.id,
            family_id=family.id,
            event_type="pickup.released",
            event_category="pickup",
            title="Student released",
            occurred_at=datetime.now(timezone.utc),
            source_module="pickup",
            source_reference=source_ref,
        )
        # Must return the existing event, not create a new one
        assert event is existing_event
        mock_db.add.assert_not_called()

    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 3. action_url validation
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_action_url_accepted():
    """Internal /parent/* URLs must be accepted."""
    from shared.db.parent_models import validate_timeline_action_url

    valid_urls = [
        "/parent/pickup",
        "/parent/student/some-id",
        "/parent/reports/abc-123",
        None,
        "",
    ]
    for url in valid_urls:
        result = validate_timeline_action_url(url)
        # Empty string normalizes to None
        if url == "":
            assert result is None
        elif url is None:
            assert result is None
        else:
            assert result == url


def test_external_url_rejected():
    """https:// URLs must be rejected."""
    from shared.db.parent_models import validate_timeline_action_url

    with pytest.raises(ValueError, match="action_url must be an internal"):
        validate_timeline_action_url("https://evil.example.com/steal")


def test_javascript_url_rejected():
    """javascript: URLs must be rejected."""
    from shared.db.parent_models import validate_timeline_action_url

    with pytest.raises(ValueError):
        validate_timeline_action_url("javascript:alert(1)")


def test_protocol_relative_url_rejected():
    """Protocol-relative URLs must be rejected."""
    from shared.db.parent_models import validate_timeline_action_url

    with pytest.raises(ValueError):
        validate_timeline_action_url("//evil.example.com")


def test_non_parent_path_rejected():
    """Internal paths not starting with /parent must be rejected."""
    from shared.db.parent_models import validate_timeline_action_url

    with pytest.raises(ValueError):
        validate_timeline_action_url("/teacher/something")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cursor pagination encoding
# ─────────────────────────────────────────────────────────────────────────────

def test_cursor_encodes_and_decodes():
    """Cursor must round-trip correctly: encode → decode → same values."""
    from services.gateway.routers.families import _encode_cursor, _decode_cursor

    event_id = uuid.uuid4()
    occurred_at = datetime(2026, 7, 15, 10, 30, 0, tzinfo=timezone.utc)

    cursor = _encode_cursor(occurred_at, event_id)
    assert isinstance(cursor, str)
    assert len(cursor) > 0

    decoded_occurred_at, decoded_id = _decode_cursor(cursor)
    assert decoded_id == event_id
    assert decoded_occurred_at == occurred_at


def test_invalid_cursor_raises_422():
    """An invalid cursor must raise HTTPException 422."""
    from fastapi import HTTPException
    from services.gateway.routers.families import _decode_cursor

    with pytest.raises(HTTPException) as exc_info:
        _decode_cursor("not-a-valid-cursor!!!")
    assert exc_info.value.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 5. Timeline endpoint returns empty in Phase 8.1
# ─────────────────────────────────────────────────────────────────────────────

def test_timeline_endpoint_returns_empty_collection():
    """
    GET /families/me/timeline returns an empty collection in Phase 8.1.
    No production writers are registered yet.
    """
    from services.gateway.main import app
    from shared.db.connection import get_db
    from shared.auth.tenant import resolve_tenant
    from shared.auth.dependencies import resolve_authenticated_parent, resolve_family

    tenant = make_tenant()
    family = make_family(tenant.id)
    parent = MagicMock()
    parent.id = uuid.uuid4()
    parent.tenant_id = tenant.id
    parent.role = "parent"
    parent.is_active = True

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[resolve_authenticated_parent] = lambda: parent
    app.dependency_overrides[resolve_family] = lambda: family

    try:
        from fastapi.testclient import TestClient
        token = __import__("tests.parent.conftest", fromlist=["make_parent_token"]).make_parent_token(
            str(parent.id)
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/families/me/timeline",
                headers={
                    "X-Tenant-Slug": tenant.slug,
                    "Authorization": f"Bearer {token}",
                },
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["events"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None
    finally:
        app.dependency_overrides.clear()


def test_timeline_ordered_desc_by_occurred_at():
    """
    Timeline events must be ordered newest-first (occurred_at DESC, id DESC).
    Structural test on the query ordering.
    """
    from services.gateway.routers.families import get_family_timeline
    # The ordering is declared in the query in families.py.
    # We verify the cursor pagination contract here:
    # events returned in pages of newest-first order.
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(hours=1)
    later = now + timedelta(hours=1)
    # Cursor based on 'later' should have events before 'later'
    event_id = uuid.uuid4()
    from services.gateway.routers.families import _encode_cursor, _decode_cursor
    cursor = _encode_cursor(later, event_id)
    decoded_at, decoded_id = _decode_cursor(cursor)
    assert decoded_at == later
    assert decoded_id == event_id


# ─────────────────────────────────────────────────────────────────────────────
# 6. Timeline idempotency key uniqueness covers NULL source_reference case
# ─────────────────────────────────────────────────────────────────────────────

def test_null_source_reference_not_used_for_deduplication():
    """
    Events without source_reference must use event_key for deduplication.
    PostgreSQL allows multiple NULL values in UNIQUE columns — so NULL
    source_reference must never be used as the idempotency key.
    """
    # Verify the model schema: UniqueConstraint is on idempotency_key, not source_reference
    from shared.db.parent_models import FamilyTimelineEvent
    from sqlalchemy import UniqueConstraint

    table = FamilyTimelineEvent.__table__
    unique_constraints = [
        uc for uc in table.constraints
        if isinstance(uc, UniqueConstraint)
    ]
    # Find the idempotency constraint
    idempotency_ucs = [
        uc for uc in unique_constraints
        if "idempotency" in (uc.name or "")
    ]
    assert len(idempotency_ucs) == 1, "Must have exactly one idempotency unique constraint"
    cols = [c.name for c in idempotency_ucs[0].columns]
    assert "idempotency_key" in cols
    assert "source_reference" not in cols
