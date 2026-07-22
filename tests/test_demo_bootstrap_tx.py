from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.gateway.routers import demo_bootstrap
from services.gateway.main import app

# Reuse helpers from the existing demo tests
from tests.test_demo_bootstrap import _set_gate, _apply_payload, _secret_header, _install_store, Store


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_apply_queries_inside_transaction(monkeypatch: pytest.MonkeyPatch):
    """Ensure all DB queries in apply() run while the transaction is active."""
    _set_gate(monkeypatch)

    # Create a very small fake session maker that exposes an _in_tx flag
    class TxFakeBegin:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            self.session._in_tx = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.session._in_tx = False
            return False

    class TxFakeSession:
        def __init__(self):
            self._in_tx = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def begin(self):
            return TxFakeBegin(self)
        def add(self, obj):
            # no-op add for testing
            return None

        async def flush(self):
            return None

    def maker():
        return TxFakeSession()

    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: maker)

    # Patch the DB lookup helpers to assert that db._in_tx is True when called.
    async def fake_find_tenant(db, slug: str):
        assert getattr(db, "_in_tx", False) is True
        return None

    async def fake_find_users(db, normalized_email: str):
        assert getattr(db, "_in_tx", False) is True
        return []

    monkeypatch.setattr(demo_bootstrap, "_find_tenant_by_slug_for_update", fake_find_tenant)
    monkeypatch.setattr(demo_bootstrap, "_find_users_by_email_case_insensitive_for_update", fake_find_users)

    with _client() as client:
        resp = client.post(
            "/internal/demo-bootstrap/apply",
            json=_apply_payload(create_if_missing=True),
            headers=_secret_header(),
        )

    assert resp.status_code == 200


def test_tenant_creation_rolls_back_on_write_failure(monkeypatch: pytest.MonkeyPatch):
    """If a write fails while creating users, any tenant creation must be rolled back."""
    _set_gate(monkeypatch)
    store = Store(tenants=[], users=[])
    # Configure the fake session to raise when adding objects (simulates DB failure)
    maker = _install_store(monkeypatch, store, raise_on_add=True)

    with _client() as client:
        resp = client.post(
            "/internal/demo-bootstrap/apply",
            json=_apply_payload(create_if_missing=True),
            headers=_secret_header(),
        )

    assert resp.status_code == 500
    # ensure tenant creation was rolled back
    assert len(store.tenants) == 0
