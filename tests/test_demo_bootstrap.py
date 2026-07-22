from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from services.gateway.routers import auth as auth_router
from services.gateway.routers import demo_bootstrap
from services.gateway.main import app
from shared.db.models import Tenant, User


@dataclass
class Store:
    tenants: list[Any]
    users: list[Any]


class _FakeBegin:
    def __init__(self, session: "FakeSession"):
        self.session = session
        self._snapshot: dict[str, Any] = {}

    async def __aenter__(self):
        self._snapshot = {
            "tenants": list(self.session.store.tenants),
            "users": list(self.session.store.users),
            "tenant_fields": {
                id(t): {
                    "id": getattr(t, "id", None),
                    "name": getattr(t, "name", None),
                    "slug": getattr(t, "slug", None),
                    "settings": copy.deepcopy(getattr(t, "settings", {})),
                    "is_active": getattr(t, "is_active", None),
                }
                for t in self.session.store.tenants
            },
            "user_fields": {
                id(u): {
                    "id": getattr(u, "id", None),
                    "tenant_id": getattr(u, "tenant_id", None),
                    "name": getattr(u, "name", None),
                    "email": getattr(u, "email", None),
                    "role": getattr(u, "role", None),
                    "password_hash": getattr(u, "password_hash", None),
                    "is_active": getattr(u, "is_active", None),
                    "phone": getattr(u, "phone", None),
                    "preferred_channel": getattr(u, "preferred_channel", None),
                }
                for u in self.session.store.users
            },
        }
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc:
            self.session.store.tenants = self._snapshot["tenants"]
            self.session.store.users = self._snapshot["users"]

            for tenant in self.session.store.tenants:
                values = self._snapshot["tenant_fields"][id(tenant)]
                tenant.id = values["id"]
                tenant.name = values["name"]
                tenant.slug = values["slug"]
                tenant.settings = values["settings"]
                tenant.is_active = values["is_active"]

            for user in self.session.store.users:
                values = self._snapshot["user_fields"][id(user)]
                user.id = values["id"]
                user.tenant_id = values["tenant_id"]
                user.name = values["name"]
                user.email = values["email"]
                user.role = values["role"]
                user.password_hash = values["password_hash"]
                user.is_active = values["is_active"]
                user.phone = values["phone"]
                user.preferred_channel = values["preferred_channel"]

        return False


class FakeSession:
    def __init__(self, store: Store, *, raise_on_add: bool = False):
        self.store = store
        self.raise_on_add = raise_on_add
        self.add_calls = 0
        self.flush_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return _FakeBegin(self)

    def add(self, obj: Any) -> None:
        self.add_calls += 1
        if self.raise_on_add:
            raise SQLAlchemyError("simulated write error")

        if isinstance(obj, Tenant):
            if obj.settings is None:
                obj.settings = {}
            self.store.tenants.append(obj)
            return
        if isinstance(obj, User):
            self.store.users.append(obj)
            return
        raise AssertionError(f"Unexpected add object type: {type(obj)!r}")

    async def flush(self) -> None:
        self.flush_calls += 1
        for tenant in self.store.tenants:
            if getattr(tenant, "id", None) is None:
                tenant.id = uuid.uuid4()
        for user in self.store.users:
            if getattr(user, "id", None) is None:
                user.id = uuid.uuid4()


class FakeSessionMaker:
    def __init__(self, store: Store, *, raise_on_add: bool = False):
        self.store = store
        self.raise_on_add = raise_on_add
        self.open_count = 0

    def __call__(self):
        self.open_count += 1
        return FakeSession(self.store, raise_on_add=self.raise_on_add)


def _tenant(slug: str = "greenwood", *, active: bool = True, name: str = "Greenwood"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug=slug,
        name=name,
        settings={},
        is_active=active,
    )


def _user(
    *,
    tenant_id,
    email: str,
    role: str,
    active: bool = True,
    password_hash: str | None = "hash-x",
    name: str = "Demo User",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        email=email,
        role=role,
        password_hash=password_hash,
        is_active=active,
        phone=None,
        preferred_channel="whatsapp",
    )


def _status_payload() -> dict[str, Any]:
    return {
        "tenant_slug": " greenwood ",
        "accounts": [
            {"email": "teacher@example.test", "role": "teacher"},
            {"email": "parent@example.test", "role": "parent"},
            {"email": "principal@example.test", "role": "principal"},
        ],
    }


def _apply_payload(*, create_if_missing: bool = False) -> dict[str, Any]:
    return {
        "tenant": {
            "slug": " greenwood ",
            "name": "Greenwood International School",
            "create_if_missing": create_if_missing,
        },
        "accounts": [
            {
                "email": "teacher@example.test",
                "role": "teacher",
                "display_name": "Teacher Demo",
                "password": "TeacherTempPass1!",
            },
            {
                "email": "parent@example.test",
                "role": "parent",
                "display_name": "Parent Demo",
                "password": "ParentTempPass1!",
            },
            {
                "email": "principal@example.test",
                "role": "principal",
                "display_name": "Principal Demo",
                "password": "PrincipalTempPass1!",
            },
        ],
    }


def _install_store(monkeypatch: pytest.MonkeyPatch, store: Store, *, raise_on_add: bool = False) -> FakeSessionMaker:
    maker = FakeSessionMaker(store, raise_on_add=raise_on_add)
    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: maker)

    async def fake_find_tenant(db, slug: str):
        for tenant in db.store.tenants:
            if tenant.slug == slug:
                return tenant
        return None

    async def fake_find_users(db, normalized_email: str):
        out = []
        for user in db.store.users:
            email = (user.email or "").lower().strip()
            if email == normalized_email:
                out.append(user)
        return out

    monkeypatch.setattr(demo_bootstrap, "_find_tenant_by_slug", fake_find_tenant)
    monkeypatch.setattr(demo_bootstrap, "_find_users_by_email_case_insensitive", fake_find_users)
    # Also patch the FOR UPDATE variants used in the transactional path
    monkeypatch.setattr(demo_bootstrap, "_find_tenant_by_slug_for_update", fake_find_tenant)
    monkeypatch.setattr(demo_bootstrap, "_find_users_by_email_case_insensitive_for_update", fake_find_users)
    return maker


def _set_gate(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True, secret: str | None = "bootstrap-secret"):
    monkeypatch.setenv("SCHOOLOS_ENABLE_DEMO_BOOTSTRAP", "true" if enabled else "false")
    if secret is None:
        monkeypatch.delenv("SCHOOLOS_DEMO_BOOTSTRAP_SECRET", raising=False)
    else:
        monkeypatch.setenv("SCHOOLOS_DEMO_BOOTSTRAP_SECRET", secret)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _secret_header(value: str | None = "bootstrap-secret") -> dict[str, str]:
    if value is None:
        return {}
    return {"X-SchoolOS-Bootstrap-Secret": value}


def test_disabled_feature_returns_404_without_db_access(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch, enabled=False, secret="bootstrap-secret")
    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("db access")))

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    assert response.status_code == 404


def test_missing_configured_secret_returns_404_without_db_access(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch, enabled=True, secret=None)
    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("db access")))

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    assert response.status_code == 404


def test_missing_request_secret_returns_404_without_db_access(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("db access")))

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload())

    assert response.status_code == 404


def test_incorrect_request_secret_returns_404_without_db_access(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    monkeypatch.setattr(demo_bootstrap, "get_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("db access")))

    with _client() as client:
        response = client.post(
            "/internal/demo-bootstrap/status",
            json=_status_payload(),
            headers=_secret_header("wrong-secret"),
        )

    assert response.status_code == 404


def test_valid_security_gate_reaches_endpoint_logic(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[_tenant(slug="greenwood")], users=[])
    maker = _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    assert response.status_code == 200
    assert maker.open_count == 1


def test_status_endpoint_is_read_only(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(
        tenants=[tenant],
        users=[
            _user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", password_hash="a"),
            _user(tenant_id=tenant.id, email="parent@example.test", role="parent", password_hash="b"),
            _user(tenant_id=tenant.id, email="principal@example.test", role="principal", password_hash="c"),
        ],
    )
    before = copy.deepcopy(
        [
            (u.email, u.role, u.password_hash, u.is_active, u.tenant_id, u.name)
            for u in store.users
        ]
    )
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    after = [(u.email, u.role, u.password_hash, u.is_active, u.tenant_id, u.name) for u in store.users]
    assert response.status_code == 200
    assert before == after


def test_status_reports_missing_tenant(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[], users=[])
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    data = response.json()
    assert response.status_code == 200
    assert data["tenant"] == {"slug": "greenwood", "exists": False, "active": False}


def test_status_reports_existing_active_tenant(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[_tenant(slug="greenwood", active=True)], users=[])
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    data = response.json()
    assert response.status_code == 200
    assert data["tenant"] == {"slug": "greenwood", "exists": True, "active": True}


def test_status_detects_email_in_other_tenant(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    target = _tenant(slug="greenwood")
    other = _tenant(slug="other-school")
    store = Store(
        tenants=[target, other],
        users=[_user(tenant_id=other.id, email="teacher@example.test", role="teacher")],
    )
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    row = response.json()["accounts"][0]
    assert response.status_code == 200
    assert row["exists"] is True
    assert row["belongs_to_target_tenant"] is False


def test_status_detects_role_mismatch(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(
        tenants=[tenant],
        users=[_user(tenant_id=tenant.id, email="teacher@example.test", role="parent")],
    )
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    row = response.json()["accounts"][0]
    assert response.status_code == 200
    assert row["role_matches"] is False


def test_status_detects_inactive_account(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(
        tenants=[tenant],
        users=[_user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", active=False)],
    )
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    row = response.json()["accounts"][0]
    assert response.status_code == 200
    assert row["active"] is False


def test_status_detects_missing_password_hash(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(
        tenants=[tenant],
        users=[_user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", password_hash=None)],
    )
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=_status_payload(), headers=_secret_header())

    row = response.json()["accounts"][0]
    assert response.status_code == 200
    assert row["has_password_hash"] is False


@pytest.mark.parametrize(
    "accounts",
    [
        [{"email": "a@test", "role": "teacher"}, {"email": "b@test", "role": "parent"}],
        [
            {"email": "a@test", "role": "teacher"},
            {"email": "b@test", "role": "parent"},
            {"email": "c@test", "role": "principal"},
            {"email": "d@test", "role": "teacher"},
        ],
    ],
)
def test_accounts_count_must_be_exactly_three(monkeypatch: pytest.MonkeyPatch, accounts):
    _set_gate(monkeypatch)
    _install_store(monkeypatch, Store(tenants=[], users=[]))
    payload = {"tenant_slug": "greenwood", "accounts": accounts}
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=payload, headers=_secret_header())
    assert response.status_code == 422


def test_duplicate_emails_rejected(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    _install_store(monkeypatch, Store(tenants=[], users=[]))
    payload = _status_payload()
    payload["accounts"][1]["email"] = payload["accounts"][0]["email"].upper()
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=payload, headers=_secret_header())
    assert response.status_code == 422


def test_missing_required_role_rejected(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    _install_store(monkeypatch, Store(tenants=[], users=[]))
    payload = _status_payload()
    payload["accounts"][2]["role"] = "teacher"
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/status", json=payload, headers=_secret_header())
    assert response.status_code == 422


def test_inactive_tenant_aborts_apply_without_writes(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[_tenant(slug="greenwood", active=False)], users=[])
    maker = _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    assert response.status_code == 409
    assert len(store.users) == 0
    assert maker.open_count == 1


def test_missing_tenant_without_create_flag_aborts(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[], users=[])
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post(
            "/internal/demo-bootstrap/apply",
            json=_apply_payload(create_if_missing=False),
            headers=_secret_header(),
        )
    assert response.status_code == 409
    assert len(store.tenants) == 0


def test_missing_tenant_with_create_flag_creates_tenant(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    store = Store(tenants=[], users=[])
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post(
            "/internal/demo-bootstrap/apply",
            json=_apply_payload(create_if_missing=True),
            headers=_secret_header(),
        )
    data = response.json()
    assert response.status_code == 200
    assert data["tenant_created"] is True
    assert len(store.tenants) == 1


def test_three_missing_users_created_atomically(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(tenants=[tenant], users=[])
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    data = response.json()
    assert response.status_code == 200
    assert data["created_users"] == 3
    assert data["updated_users"] == 0
    assert len(store.users) == 3


def test_existing_users_only_password_hash_updated(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    users = [
        _user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", password_hash="old1", name="T Name"),
        _user(tenant_id=tenant.id, email="parent@example.test", role="parent", password_hash="old2", name="P Name"),
        _user(tenant_id=tenant.id, email="principal@example.test", role="principal", password_hash="old3", name="R Name"),
    ]
    before_fields = [(u.name, u.email, u.role, u.tenant_id, u.is_active) for u in users]
    before_hashes = [u.password_hash for u in users]
    store = Store(tenants=[tenant], users=users)
    _install_store(monkeypatch, store)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())

    assert response.status_code == 200
    assert response.json()["updated_users"] == 3
    after_fields = [(u.name, u.email, u.role, u.tenant_id, u.is_active) for u in users]
    after_hashes = [u.password_hash for u in users]
    assert before_fields == after_fields
    assert before_hashes != after_hashes


def test_mixed_create_update_is_atomic(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    existing = [_user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", password_hash="old")]
    store = Store(tenants=[tenant], users=existing)
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    data = response.json()
    assert response.status_code == 200
    assert data["created_users"] == 2
    assert data["updated_users"] == 1
    assert len(store.users) == 3


def test_email_in_another_tenant_aborts_and_rolls_back(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    target = _tenant(slug="greenwood")
    other = _tenant(slug="other")
    users = [_user(tenant_id=other.id, email="teacher@example.test", role="teacher", password_hash="old")]
    store = Store(tenants=[target, other], users=users)
    before = copy.deepcopy([(u.email, u.password_hash, u.tenant_id) for u in users])
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    after = [(u.email, u.password_hash, u.tenant_id) for u in users]
    assert response.status_code == 409
    assert before == after


def test_existing_wrong_role_aborts_and_rolls_back(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    users = [_user(tenant_id=tenant.id, email="teacher@example.test", role="parent", password_hash="old")]
    store = Store(tenants=[tenant], users=users)
    before_hash = users[0].password_hash
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    assert response.status_code == 409
    assert users[0].password_hash == before_hash


def test_existing_inactive_user_aborts_and_rolls_back(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    users = [_user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", active=False, password_hash="old")]
    store = Store(tenants=[tenant], users=users)
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    assert response.status_code == 409
    assert users[0].password_hash == "old"


def test_ambiguous_case_insensitive_email_matches_abort(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    users = [
        _user(tenant_id=tenant.id, email="teacher@example.test", role="teacher"),
        _user(tenant_id=tenant.id, email="TEACHER@example.test", role="teacher"),
    ]
    store = Store(tenants=[tenant], users=users)
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    assert response.status_code == 409


def test_any_failure_leaves_all_three_users_unchanged(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    users = [
        _user(tenant_id=tenant.id, email="teacher@example.test", role="teacher", password_hash="h1"),
        _user(tenant_id=tenant.id, email="parent@example.test", role="parent", password_hash="h2"),
        _user(tenant_id=tenant.id, email="principal@example.test", role="principal", password_hash="h3"),
    ]
    before = [u.password_hash for u in users]
    store = Store(tenants=[tenant], users=users)
    _install_store(monkeypatch, store)

    original_hash = demo_bootstrap._pwd_context.hash

    def fail_on_second(value: str):
        if value == "ParentTempPass1!":
            raise RuntimeError("hash failure")
        return original_hash(value)

    monkeypatch.setattr(demo_bootstrap._pwd_context, "hash", fail_on_second)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())

    after = [u.password_hash for u in users]
    assert response.status_code == 500
    assert before == after


def test_success_affects_exactly_three_users(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(tenants=[tenant], users=[])
    _install_store(monkeypatch, store)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    assert response.status_code == 200
    emails = sorted((u.email or "") for u in store.users)
    assert emails == ["parent@example.test", "principal@example.test", "teacher@example.test"]


def test_existing_user_non_password_fields_unchanged(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    user_obj = _user(
        tenant_id=tenant.id,
        email="teacher@example.test",
        role="teacher",
        password_hash="oldhash",
        name="Original Teacher Name",
    )
    parent_obj = _user(tenant_id=tenant.id, email="parent@example.test", role="parent", password_hash="old2")
    principal_obj = _user(tenant_id=tenant.id, email="principal@example.test", role="principal", password_hash="old3")
    store = Store(tenants=[tenant], users=[user_obj, parent_obj, principal_obj])
    _install_store(monkeypatch, store)
    before = (user_obj.name, user_obj.email, user_obj.role, user_obj.tenant_id, user_obj.is_active)
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=_apply_payload(), headers=_secret_header())
    after = (user_obj.name, user_obj.email, user_obj.role, user_obj.tenant_id, user_obj.is_active)
    assert response.status_code == 200
    assert before == after
    assert user_obj.password_hash != "oldhash"


def test_new_hashes_verify_with_same_auth_configuration(monkeypatch: pytest.MonkeyPatch):
    _set_gate(monkeypatch)
    tenant = _tenant(slug="greenwood")
    store = Store(tenants=[tenant], users=[])
    _install_store(monkeypatch, store)
    payload = _apply_payload()
    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=payload, headers=_secret_header())
    assert response.status_code == 200
    expected_by_email = {entry["email"].lower().strip(): entry["password"] for entry in payload["accounts"]}
    for user in store.users:
        assert auth_router._pwd_context.verify(expected_by_email[user.email], user.password_hash)


def test_sensitive_values_never_exposed_in_response_or_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    _set_gate(monkeypatch)
    secret = "bootstrap-secret"
    payload = _apply_payload()
    payload["accounts"][0]["password"] = "SensitiveTeacherPass!"
    payload["accounts"][1]["password"] = "SensitiveParentPass!"
    payload["accounts"][2]["password"] = "SensitivePrincipalPass!"

    tenant = _tenant(slug="greenwood")
    store = Store(tenants=[tenant], users=[])
    _install_store(monkeypatch, store, raise_on_add=True)

    with _client() as client:
        response = client.post("/internal/demo-bootstrap/apply", json=payload, headers=_secret_header(secret))

    text = response.text + "\n" + "\n".join(r.message for r in caplog.records)
    # Raise-on-add simulates a DB write failure (non-Integrity). This should
    # surface as a safe 500 (not a 409) and must not contain secrets.
    assert response.status_code == 500
    assert "SensitiveTeacherPass!" not in text
    assert "SensitiveParentPass!" not in text
    assert "SensitivePrincipalPass!" not in text
    assert secret not in text
    assert "DATABASE_URL" not in text
    assert "jwt" not in text.lower()
    assert "password_hash" not in text.lower()
