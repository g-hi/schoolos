from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from scripts import reset_demo_passwords as script
from shared.auth.passwords import verify_password


@dataclass
class _FakeResult:
    rows: list[object]

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[object]:
        return self.rows


class _FakeBegin:
    def __init__(self, session: "_FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.begin_entered += 1

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self._session.committed += 1
        else:
            self._session.rolled_back += 1
        return False


class _FakeSession:
    def __init__(self, response_batches: list[list[object]]) -> None:
        self._responses = [_FakeResult(rows) for rows in response_batches]
        self.execute_calls = 0
        self.begin_entered = 0
        self.committed = 0
        self.rolled_back = 0

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self)

    async def execute(self, _stmt) -> _FakeResult:
        if not self._responses:
            raise AssertionError("Unexpected extra query")
        self.execute_calls += 1
        return self._responses.pop(0)


def _enabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHOOLOS_RESET_DEMO_PASSWORDS", "true")
    monkeypatch.setenv("SCHOOLOS_DEMO_TENANT_SLUG", "greenwood")
    monkeypatch.setenv("SCHOOLOS_DEMO_PARENT_EMAIL", "parent@demo.school")
    monkeypatch.setenv("SCHOOLOS_DEMO_PARENT_PASSWORD", "ParentSecure#2026")
    monkeypatch.setenv("SCHOOLOS_DEMO_TEACHER_EMAIL", "teacher@demo.school")
    monkeypatch.setenv("SCHOOLOS_DEMO_TEACHER_PASSWORD", "TeacherSecure#2026")
    monkeypatch.setenv("SCHOOLOS_DEMO_PRINCIPAL_EMAIL", "principal@demo.school")
    monkeypatch.setenv("SCHOOLOS_DEMO_PRINCIPAL_PASSWORD", "PrincipalSecure#2026")


def _config() -> script.ResetConfig:
    return script.ResetConfig(
        tenant_slug="greenwood",
        accounts=(
            script.AccountResetRequest(
                email="parent@demo.school",
                role="parent",
                password="ParentSecure#2026",
            ),
            script.AccountResetRequest(
                email="teacher@demo.school",
                role="teacher",
                password="TeacherSecure#2026",
            ),
            script.AccountResetRequest(
                email="principal@demo.school",
                role="principal",
                password="PrincipalSecure#2026",
            ),
        ),
    )


def test_disabled_flag_successful_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHOOLOS_RESET_DEMO_PASSWORDS", raising=False)

    called = {"run": False}

    async def _never_called(_config: script.ResetConfig):
        called["run"] = True
        return []

    monkeypatch.setattr(script, "_run_enabled_reset", _never_called)

    assert script.main() == 0
    assert called["run"] is False


def test_missing_required_environment_variable_fails_safely(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _enabled_env(monkeypatch)
    monkeypatch.delenv("SCHOOLOS_DEMO_TEACHER_PASSWORD", raising=False)

    assert script.main() == 1
    output = capsys.readouterr().out
    assert "RESET_FAILED" in output
    assert "SCHOOLOS_DEMO_TEACHER_PASSWORD" in output
    assert "TeacherSecure#2026" not in output


@pytest.mark.asyncio
async def test_missing_tenant_causes_rollback() -> None:
    session = _FakeSession(response_batches=[[]])

    with pytest.raises(script.ResetError, match="Tenant lookup failed"):
        await script._reset_passwords(session, _config())

    assert session.begin_entered == 1
    assert session.committed == 0
    assert session.rolled_back == 1


@pytest.mark.asyncio
async def test_missing_user_causes_rollback() -> None:
    tenant = SimpleNamespace(id="tenant-1", slug="greenwood", is_active=True)
    parent = SimpleNamespace(password_hash="old-parent")
    principal = SimpleNamespace(password_hash="old-principal")
    session = _FakeSession(
        response_batches=[
            [tenant],
            [parent],
            [],
            [principal],
        ]
    )

    with pytest.raises(script.ResetError, match="User lookup failed"):
        await script._reset_passwords(session, _config())

    assert session.begin_entered == 1
    assert session.committed == 0
    assert session.rolled_back == 1


@pytest.mark.asyncio
async def test_role_mismatch_causes_rollback() -> None:
    tenant = SimpleNamespace(id="tenant-1", slug="greenwood", is_active=True)
    parent = SimpleNamespace(password_hash="old-parent")
    principal = SimpleNamespace(password_hash="old-principal")
    # Teacher account does not satisfy the role filter, so query yields no row.
    session = _FakeSession(
        response_batches=[
            [tenant],
            [parent],
            [],
            [principal],
        ]
    )

    with pytest.raises(script.ResetError, match="User lookup failed"):
        await script._reset_passwords(session, _config())

    assert session.begin_entered == 1
    assert session.committed == 0
    assert session.rolled_back == 1


@pytest.mark.asyncio
async def test_successful_execution_updates_exactly_three_users() -> None:
    tenant = SimpleNamespace(id="tenant-1", slug="greenwood", is_active=True)
    parent = SimpleNamespace(password_hash="old-parent")
    teacher = SimpleNamespace(password_hash="old-teacher")
    principal = SimpleNamespace(password_hash="old-principal")
    untouched = SimpleNamespace(password_hash="old-untouched")

    session = _FakeSession(
        response_batches=[
            [tenant],
            [parent],
            [teacher],
            [principal],
        ]
    )

    rows = await script._reset_passwords(session, _config())

    assert session.begin_entered == 1
    assert session.committed == 1
    assert session.rolled_back == 0
    assert len(rows) == 3
    assert rows == [
        ("greenwood", "parent@demo.school", "parent"),
        ("greenwood", "teacher@demo.school", "teacher"),
        ("greenwood", "principal@demo.school", "principal"),
    ]

    assert verify_password("ParentSecure#2026", parent.password_hash)
    assert verify_password("TeacherSecure#2026", teacher.password_hash)
    assert verify_password("PrincipalSecure#2026", principal.password_hash)
    assert untouched.password_hash == "old-untouched"


def test_no_sensitive_data_is_logged(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _enabled_env(monkeypatch)
    monkeypatch.setattr(script.settings, "database_url", "postgresql://user:pass@host:5432/schoolos")

    async def _fake_success(_config: script.ResetConfig):
        return [
            ("greenwood", "parent@demo.school", "parent"),
            ("greenwood", "teacher@demo.school", "teacher"),
            ("greenwood", "principal@demo.school", "principal"),
        ]

    monkeypatch.setattr(script, "_run_enabled_reset", _fake_success)

    assert script.main() == 0
    output = capsys.readouterr().out

    assert "RESET_COMPLETED" in output
    assert "tenant_slug=greenwood" in output
    assert "parent@demo.school" in output
    assert "teacher@demo.school" in output
    assert "principal@demo.school" in output

    assert "ParentSecure#2026" not in output
    assert "TeacherSecure#2026" not in output
    assert "PrincipalSecure#2026" not in output
    assert "$2" not in output
    assert "postgresql://user:pass@host:5432/schoolos" not in output
    assert "eyJ" not in output
