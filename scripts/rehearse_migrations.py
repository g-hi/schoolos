from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REHEARSAL_GATE_ENV = "SCHOOLOS_ALLOW_DISPOSABLE_MIGRATION_TEST"
REHEARSAL_GATE_VALUE = "true"
REHEARSAL_DB_PREFIX = "schoolos_rehearsal_"
RENDER_HOST_MARKERS = ("render", "onrender.com")


class SafetyError(RuntimeError):
    """Raised when a safety guard blocks execution."""


@dataclass
class ScenarioResult:
    name: str
    success: bool
    error: str | None
    first_failure_operation: str | None
    final_revision: str | None
    tables: list[str]
    details: dict[str, Any]


@dataclass
class RehearsalReport:
    guard_enabled: bool
    graph: dict[str, Any]
    scenario_a: ScenarioResult
    scenario_b: ScenarioResult
    scenario_c: ScenarioResult
    schema_differences: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "guard_enabled": self.guard_enabled,
            "graph": self.graph,
            "scenario_a": _scenario_to_json(self.scenario_a),
            "scenario_b": _scenario_to_json(self.scenario_b),
            "scenario_c": _scenario_to_json(self.scenario_c),
            "schema_differences": self.schema_differences,
        }


def _scenario_to_json(result: ScenarioResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "success": result.success,
        "error": result.error,
        "first_failure_operation": result.first_failure_operation,
        "final_revision": result.final_revision,
        "tables": result.tables,
        "details": result.details,
    }


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def require_rehearsal_gate() -> None:
    if os.environ.get(REHEARSAL_GATE_ENV, "").strip().lower() != REHEARSAL_GATE_VALUE:
        raise SafetyError(
            "Refusing to run. Set SCHOOLOS_ALLOW_DISPOSABLE_MIGRATION_TEST=true explicitly."
        )


def reject_preconfigured_database_url() -> None:
    if os.environ.get("DATABASE_URL"):
        raise SafetyError(
            "Refusing to run while DATABASE_URL is already configured in the parent environment."
        )


def validate_disposable_database_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db_name = parsed.path.lstrip("/")

    if host not in {"localhost", "127.0.0.1"}:
        raise SafetyError(f"Non-local host rejected: {host or '<empty>'}")

    if any(marker in host for marker in RENDER_HOST_MARKERS):
        raise SafetyError(f"Render-like hostname rejected: {host}")

    if not db_name.startswith(REHEARSAL_DB_PREFIX):
        raise SafetyError(
            "Database name rejected. Rehearsal database names must use prefix "
            f"{REHEARSAL_DB_PREFIX!r}."
        )


@dataclass
class DisposableContainer:
    name: str
    user: str
    password: str
    port: int


def _docker_available() -> bool:
    probe = _run_cmd(["docker", "version", "--format", "{{.Server.Version}}"])
    return probe.returncode == 0


def _start_disposable_postgres() -> DisposableContainer:
    if not _docker_available():
        raise RuntimeError("Docker is unavailable. Cannot run disposable migration rehearsal.")

    suffix = uuid.uuid4().hex[:10]
    container_name = f"{REHEARSAL_DB_PREFIX}pg_{suffix}"
    password = f"pw_{uuid.uuid4().hex}"
    user = "postgres"

    cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        f"POSTGRES_USER={user}",
        "-e",
        "POSTGRES_DB=postgres",
        "-p",
        "127.0.0.1::5432",
        "postgres:16-alpine",
    ]
    created = _run_cmd(cmd, check=True)
    if not created.stdout.strip():
        raise RuntimeError("Failed to start disposable PostgreSQL container.")

    port_cmd = _run_cmd(["docker", "port", container_name, "5432/tcp"], check=True)
    port_output = port_cmd.stdout.strip()
    match = re.search(r":(\d+)$", port_output)
    if not match:
        _safe_stop_container(container_name)
        raise RuntimeError(f"Could not parse mapped PostgreSQL port from: {port_output!r}")

    port = int(match.group(1))
    _wait_for_postgres_ready(container_name, user)

    return DisposableContainer(name=container_name, user=user, password=password, port=port)


def _wait_for_postgres_ready(container_name: str, user: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        ready = _run_cmd(
            ["docker", "exec", container_name, "pg_isready", "-U", user, "-d", "postgres"]
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    _safe_stop_container(container_name)
    raise RuntimeError("Disposable PostgreSQL container did not become ready in time.")


def _safe_stop_container(container_name: str) -> None:
    _run_cmd(["docker", "stop", container_name])


def _psql(
    container: DisposableContainer,
    database: str,
    sql: str,
    *,
    fail_ok: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "exec",
        "-i",
        container.name,
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        container.user,
        "-d",
        database,
        "-At",
        "-F",
        "\t",
        "-c",
        sql,
    ]
    result = _run_cmd(cmd)
    if not fail_ok and result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "psql command failed")
    return result


def _psql_file(container: DisposableContainer, database: str, sql_text: str) -> None:
    cmd = [
        "docker",
        "exec",
        "-i",
        container.name,
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        container.user,
        "-d",
        database,
        "-f",
        "-",
    ]
    completed = _run_cmd(cmd, input_text=sql_text)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "psql file execution failed")


def _create_database(container: DisposableContainer, db_name: str) -> None:
    _psql(container, "postgres", f'CREATE DATABASE "{db_name}";')


def _drop_database(container: DisposableContainer, db_name: str) -> None:
    _psql(
        container,
        "postgres",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",
    )
    _psql(container, "postgres", f'DROP DATABASE IF EXISTS "{db_name}";')


def _db_url(container: DisposableContainer, db_name: str) -> str:
    url = f"postgresql://{container.user}:{container.password}@127.0.0.1:{container.port}/{db_name}"
    validate_disposable_database_url(url)
    return url


def _alembic_upgrade_head(repo_root: Path, db_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    alembic_bin = shutil.which("alembic")
    if not alembic_bin:
        local_alembic = repo_root / ".venv" / "Scripts" / "alembic.exe"
        if local_alembic.exists():
            alembic_bin = str(local_alembic)
    if not alembic_bin:
        raise RuntimeError("Alembic CLI executable not found in PATH or .venv/Scripts/alembic.exe")
    return _run_cmd(
        [alembic_bin, "-c", str(repo_root / "alembic.ini"), "upgrade", "head"],
        cwd=repo_root,
        env=env,
    )


def _read_alembic_revision(container: DisposableContainer, db_name: str) -> str | None:
    has_table = _psql(
        container,
        db_name,
        "SELECT to_regclass('public.alembic_version') IS NOT NULL;",
        fail_ok=True,
    )
    if has_table.returncode != 0:
        return None
    if has_table.stdout.strip().lower() != "t":
        return None
    revision = _psql(container, db_name, "SELECT version_num FROM alembic_version LIMIT 1;", fail_ok=True)
    if revision.returncode != 0:
        return None
    return revision.stdout.strip() or None


def _list_tables(container: DisposableContainer, db_name: str) -> list[str]:
    rows = _psql(
        container,
        db_name,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name;",
        fail_ok=True,
    )
    if rows.returncode != 0:
        return []
    return [line.strip() for line in rows.stdout.splitlines() if line.strip()]


def _row_count(container: DisposableContainer, db_name: str, table_name: str) -> int:
    count = _psql(container, db_name, f"SELECT COUNT(*) FROM {table_name};")
    return int(count.stdout.strip() or "0")


def _schema_snapshot(container: DisposableContainer, db_name: str) -> dict[str, Any]:
    columns_sql = (
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, "
        "COALESCE(column_default,'') "
        "FROM information_schema.columns "
        "WHERE table_schema='public' "
        "ORDER BY table_name, ordinal_position;"
    )
    uniques_sql = (
        "SELECT tc.table_name, tc.constraint_name, string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position) "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
        "WHERE tc.table_schema='public' AND tc.constraint_type='UNIQUE' "
        "GROUP BY tc.table_name, tc.constraint_name "
        "ORDER BY tc.table_name, tc.constraint_name;"
    )
    fk_sql = (
        "SELECT tc.table_name, tc.constraint_name, ccu.table_name, "
        "string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position), "
        "string_agg(ccu.column_name, ',' ORDER BY kcu.ordinal_position) "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema "
        "WHERE tc.table_schema='public' AND tc.constraint_type='FOREIGN KEY' "
        "GROUP BY tc.table_name, tc.constraint_name, ccu.table_name "
        "ORDER BY tc.table_name, tc.constraint_name;"
    )
    check_sql = (
        "SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid = con.conrelid "
        "JOIN pg_namespace nsp ON nsp.oid = con.connamespace "
        "WHERE nsp.nspname='public' AND con.contype='c' "
        "ORDER BY rel.relname, con.conname;"
    )
    indexes_sql = (
        "SELECT tablename, indexname, indexdef "
        "FROM pg_indexes "
        "WHERE schemaname='public' "
        "ORDER BY tablename, indexname;"
    )

    return {
        "tables": _list_tables(container, db_name),
        "columns": _query_rows(container, db_name, columns_sql, 6),
        "unique_constraints": _query_rows(container, db_name, uniques_sql, 3),
        "foreign_keys": _query_rows(container, db_name, fk_sql, 5),
        "check_constraints": _query_rows(container, db_name, check_sql, 3),
        "indexes": _query_rows(container, db_name, indexes_sql, 3),
    }


def _query_rows(
    container: DisposableContainer,
    db_name: str,
    sql: str,
    width: int,
) -> list[list[str]]:
    completed = _psql(container, db_name, sql, fail_ok=True)
    if completed.returncode != 0:
        return []
    rows: list[list[str]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < width:
            parts += [""] * (width - len(parts))
        rows.append(parts[:width])
    return rows


def _extract_first_failure_operation(output: str) -> str | None:
    for marker in (
        "ERROR:",
        "sqlalchemy.exc",
        "asyncpg.exceptions",
        "Failed",
    ):
        for line in output.splitlines():
            if marker in line:
                return line.strip()
    return None


def _extract_uuid(output: str) -> str:
    uuid_re = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    match = uuid_re.search(output)
    if not match:
        raise RuntimeError(f"Expected UUID in SQL output but none found: {output!r}")
    return match.group(0)


def _mask_password_hashes(user_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for row in user_rows:
        hash_value = str(row.get("password_hash") or "")
        sanitized.append(
            {
                "id": row["id"],
                "email": row["email"],
                "role": row["role"],
                "is_active": row["is_active"],
                "password_hash_sha256": hashlib.sha256(hash_value.encode("utf-8")).hexdigest(),
            }
        )
    return sanitized


def _load_rows_for_preservation(
    container: DisposableContainer,
    db_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tenant_rows = _query_rows(
        container,
        db_name,
        "SELECT id::text, slug, is_active::text FROM tenants ORDER BY slug;",
        3,
    )
    user_rows = _query_rows(
        container,
        db_name,
        "SELECT id::text, COALESCE(email,''), role, is_active::text, COALESCE(password_hash,'') "
        "FROM users ORDER BY role, id;",
        5,
    )

    tenants = [
        {
            "id": row[0],
            "slug": row[1],
            "is_active": row[2].lower() == "true",
        }
        for row in tenant_rows
    ]
    users = [
        {
            "id": row[0],
            "email": row[1],
            "role": row[2],
            "is_active": row[3].lower() == "true",
            "password_hash": row[4],
        }
        for row in user_rows
    ]
    return tenants, users


def _assert_preservation(
    before_tenants: list[dict[str, Any]],
    before_users: list[dict[str, Any]],
    after_tenants: list[dict[str, Any]],
    after_users: list[dict[str, Any]],
) -> dict[str, bool]:
    before_tenant_map = {row["id"]: row for row in before_tenants}
    after_tenant_map = {row["id"]: row for row in after_tenants}
    before_user_map = {row["id"]: row for row in before_users}
    after_user_map = {row["id"]: row for row in after_users}

    tenants_unchanged = before_tenant_map == after_tenant_map
    users_unchanged = before_user_map == after_user_map

    return {
        "tenant_rows_preserved": tenants_unchanged,
        "user_rows_preserved": users_unchanged,
        "tenant_row_count_preserved": len(before_tenants) == len(after_tenants),
        "user_row_count_preserved": len(before_users) == len(after_users),
    }


def _apply_init_sql(repo_root: Path, container: DisposableContainer, db_name: str) -> None:
    init_sql_path = repo_root / "infra" / "postgres" / "init.sql"
    sql_text = init_sql_path.read_text(encoding="utf-8")
    _psql_file(container, db_name, sql_text)


def _insert_dummy_rehearsal_data(container: DisposableContainer, db_name: str) -> dict[str, str]:
    _psql(container, db_name, "DELETE FROM tenants;")
    tenant_id = _extract_uuid(
        _psql(
        container,
        db_name,
        "INSERT INTO tenants (name, slug, settings, is_active) "
        "VALUES ('Rehearsal Academy','rehearsal-academy','{}'::jsonb,true) "
        "RETURNING id::text;",
        ).stdout
    )

    teacher_user_id = _extract_uuid(
        _psql(
        container,
        db_name,
        "INSERT INTO users (tenant_id, name, email, role, password_hash, is_active, preferred_channel) "
        f"VALUES ('{tenant_id}'::uuid, 'Rehearsal Teacher', 'teacher.rehearsal@example.invalid', "
        "'teacher', 'dummy-hash-teacher', true, 'email') "
        "RETURNING id::text;",
        ).stdout
    )

    _psql(
        container,
        db_name,
        "INSERT INTO teachers (tenant_id, user_id, employee_id, max_weekly_hours) "
        f"VALUES ('{tenant_id}'::uuid, '{teacher_user_id}'::uuid, 'RH-TEACHER-001', 20);",
    )

    parent_user_id = _extract_uuid(
        _psql(
        container,
        db_name,
        "INSERT INTO users (tenant_id, name, email, role, password_hash, is_active, preferred_channel) "
        f"VALUES ('{tenant_id}'::uuid, 'Rehearsal Parent', 'parent.rehearsal@example.invalid', "
        "'parent', 'dummy-hash-parent', true, 'email') "
        "RETURNING id::text;",
        ).stdout
    )

    principal_user_id = _extract_uuid(
        _psql(
        container,
        db_name,
        "INSERT INTO users (tenant_id, name, email, role, password_hash, is_active, preferred_channel) "
        f"VALUES ('{tenant_id}'::uuid, 'Rehearsal Principal', 'principal.rehearsal@example.invalid', "
        "'principal', 'dummy-hash-principal', true, 'email') "
        "RETURNING id::text;",
        ).stdout
    )

    return {
        "tenant_id": tenant_id,
        "teacher_user_id": teacher_user_id,
        "parent_user_id": parent_user_id,
        "principal_user_id": principal_user_id,
    }


def _run_scenario_a(repo_root: Path, container: DisposableContainer, db_name: str) -> ScenarioResult:
    _create_database(container, db_name)
    db_url = _db_url(container, db_name)
    upgrade = _alembic_upgrade_head(repo_root, db_url)
    output = (upgrade.stdout or "") + "\n" + (upgrade.stderr or "")
    success = upgrade.returncode == 0
    return ScenarioResult(
        name="scenario_a_empty_db_alembic_only",
        success=success,
        error=None if success else f"alembic upgrade failed with exit code {upgrade.returncode}",
        first_failure_operation=None if success else _extract_first_failure_operation(output),
        final_revision=_read_alembic_revision(container, db_name),
        tables=_list_tables(container, db_name),
        details={
            "alembic_exit_code": upgrade.returncode,
            "alembic_stdout_tail": (upgrade.stdout or "").splitlines()[-20:],
            "alembic_stderr_tail": (upgrade.stderr or "").splitlines()[-20:],
        },
    )


def _run_scenario_b(repo_root: Path, container: DisposableContainer, db_name: str) -> ScenarioResult:
    _create_database(container, db_name)
    _apply_init_sql(repo_root, container, db_name)

    before_tenants = _row_count(container, db_name, "tenants")
    before_users = _row_count(container, db_name, "users")
    tables_before = _list_tables(container, db_name)

    db_url = _db_url(container, db_name)
    upgrade = _alembic_upgrade_head(repo_root, db_url)
    output = (upgrade.stdout or "") + "\n" + (upgrade.stderr or "")
    success = upgrade.returncode == 0

    after_tenants = _row_count(container, db_name, "tenants")
    after_users = _row_count(container, db_name, "users")

    return ScenarioResult(
        name="scenario_b_init_sql_then_alembic",
        success=success,
        error=None if success else f"alembic upgrade failed with exit code {upgrade.returncode}",
        first_failure_operation=None if success else _extract_first_failure_operation(output),
        final_revision=_read_alembic_revision(container, db_name),
        tables=_list_tables(container, db_name),
        details={
            "seed_counts_before_upgrade": {
                "tenants": before_tenants,
                "users": before_users,
            },
            "seed_counts_after_upgrade": {
                "tenants": after_tenants,
                "users": after_users,
            },
            "tables_before_upgrade": tables_before,
            "schema_snapshot": _schema_snapshot(container, db_name),
            "alembic_exit_code": upgrade.returncode,
            "alembic_stdout_tail": (upgrade.stdout or "").splitlines()[-20:],
            "alembic_stderr_tail": (upgrade.stderr or "").splitlines()[-20:],
        },
    )


def _run_scenario_c(repo_root: Path, container: DisposableContainer, db_name: str) -> ScenarioResult:
    _create_database(container, db_name)
    _apply_init_sql(repo_root, container, db_name)
    dummy_ids = _insert_dummy_rehearsal_data(container, db_name)

    before_tenants, before_users = _load_rows_for_preservation(container, db_name)
    before_counts = {
        "tenants": len(before_tenants),
        "users": len(before_users),
    }

    db_url = _db_url(container, db_name)
    upgrade = _alembic_upgrade_head(repo_root, db_url)
    output = (upgrade.stdout or "") + "\n" + (upgrade.stderr or "")
    success = upgrade.returncode == 0

    after_tenants, after_users = _load_rows_for_preservation(container, db_name)
    assertions = _assert_preservation(before_tenants, before_users, after_tenants, after_users)

    return ScenarioResult(
        name="scenario_c_data_preservation",
        success=success,
        error=None if success else f"alembic upgrade failed with exit code {upgrade.returncode}",
        first_failure_operation=None if success else _extract_first_failure_operation(output),
        final_revision=_read_alembic_revision(container, db_name),
        tables=_list_tables(container, db_name),
        details={
            "dummy_identity_ids": {
                "tenant_id": dummy_ids["tenant_id"],
                "teacher_user_id": dummy_ids["teacher_user_id"],
                "parent_user_id": dummy_ids["parent_user_id"],
                "principal_user_id": dummy_ids["principal_user_id"],
            },
            "before_counts": before_counts,
            "after_counts": {
                "tenants": len(after_tenants),
                "users": len(after_users),
            },
            "before_tenants": before_tenants,
            "after_tenants": after_tenants,
            "before_users_redacted": _mask_password_hashes(before_users),
            "after_users_redacted": _mask_password_hashes(after_users),
            "preservation_assertions": assertions,
            "alembic_exit_code": upgrade.returncode,
            "alembic_stdout_tail": (upgrade.stdout or "").splitlines()[-20:],
            "alembic_stderr_tail": (upgrade.stderr or "").splitlines()[-20:],
            "schema_snapshot": _schema_snapshot(container, db_name),
        },
    )


def _schema_diff(
    left: dict[str, Any],
    right: dict[str, Any],
    left_label: str,
    right_label: str,
) -> dict[str, Any]:
    def _as_set(rows: list[list[str]]) -> set[tuple[str, ...]]:
        return {tuple(row) for row in rows}

    diff: dict[str, Any] = {
        "tables_only_in_left": sorted(set(left.get("tables", [])) - set(right.get("tables", []))),
        "tables_only_in_right": sorted(set(right.get("tables", [])) - set(left.get("tables", []))),
    }

    for key in (
        "columns",
        "unique_constraints",
        "foreign_keys",
        "check_constraints",
        "indexes",
    ):
        left_set = _as_set(left.get(key, []))
        right_set = _as_set(right.get(key, []))
        diff[f"{key}_only_in_{left_label}"] = sorted([list(x) for x in left_set - right_set])
        diff[f"{key}_only_in_{right_label}"] = sorted([list(x) for x in right_set - left_set])

    watch_tables = [
        "tenants",
        "users",
        "families",
        "student_parents",
        "weekly_student_reports",
        "weekly_student_report_versions",
        "weekly_student_report_review_events",
    ]
    diff["watch_tables"] = watch_tables
    return diff


def analyze_revision_graph(repo_root: Path) -> dict[str, Any]:
    versions_dir = repo_root / "alembic" / "versions"
    revision_re = re.compile(r"^revision:\s*str\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    down_re = re.compile(
        r"^down_revision:\s*Union\[str, None\]\s*=\s*(?:['\"]([^'\"]+)['\"]|None)",
        re.MULTILINE,
    )

    records: list[dict[str, str | None]] = []
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        rev_match = revision_re.search(text)
        down_match = down_re.search(text)
        revision = rev_match.group(1) if rev_match else None
        down_revision = down_match.group(1) if down_match else None
        records.append(
            {
                "file": str(path.relative_to(repo_root)).replace("\\", "/"),
                "revision": revision,
                "down_revision": down_revision,
            }
        )

    revision_to_files: dict[str, list[str]] = {}
    all_revisions: set[str] = set()
    all_down_revisions: set[str] = set()

    for rec in records:
        revision = rec["revision"]
        if revision:
            all_revisions.add(revision)
            revision_to_files.setdefault(revision, []).append(str(rec["file"]))
        if rec["down_revision"]:
            all_down_revisions.add(str(rec["down_revision"]))

    duplicates = {rev: files for rev, files in revision_to_files.items() if len(files) > 1}
    roots = sorted([rec["revision"] for rec in records if rec["down_revision"] is None and rec["revision"]])
    heads = sorted(list(all_revisions - all_down_revisions))
    broken_down_references = sorted(list(all_down_revisions - all_revisions))

    return {
        "records": records,
        "roots": roots,
        "heads": heads,
        "broken_down_references": broken_down_references,
        "duplicate_revisions": duplicates,
        "exactly_one_root": len(roots) == 1,
        "exactly_one_head": len(heads) == 1,
        "has_broken_references": bool(broken_down_references),
        "has_duplicate_revisions": bool(duplicates),
    }


def run_rehearsal(repo_root: Path) -> RehearsalReport:
    require_rehearsal_gate()
    reject_preconfigured_database_url()

    graph = analyze_revision_graph(repo_root)

    container = _start_disposable_postgres()
    db_names = {
        "a": f"{REHEARSAL_DB_PREFIX}a_{uuid.uuid4().hex[:12]}",
        "b": f"{REHEARSAL_DB_PREFIX}b_{uuid.uuid4().hex[:12]}",
        "c": f"{REHEARSAL_DB_PREFIX}c_{uuid.uuid4().hex[:12]}",
    }

    try:
        scenario_a = _run_scenario_a(repo_root, container, db_names["a"])
        scenario_b = _run_scenario_b(repo_root, container, db_names["b"])
        scenario_c = _run_scenario_c(repo_root, container, db_names["c"])

        schema_diffs: dict[str, Any] = {}
        b_snapshot = scenario_b.details.get("schema_snapshot")
        c_snapshot = scenario_c.details.get("schema_snapshot")
        if isinstance(b_snapshot, dict) and isinstance(c_snapshot, dict):
            schema_diffs["scenario_b_vs_scenario_c"] = _schema_diff(
                b_snapshot,
                c_snapshot,
                "scenario_b",
                "scenario_c",
            )

        return RehearsalReport(
            guard_enabled=True,
            graph=graph,
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            scenario_c=scenario_c,
            schema_differences=schema_diffs,
        )
    finally:
        for name in db_names.values():
            try:
                _drop_database(container, name)
            except Exception:
                pass
        _safe_stop_container(container.name)


def _print_summary(report: RehearsalReport) -> None:
    print("Disposable SchoolOS migration rehearsal complete")
    print("Graph checks:")
    print(f"  - roots: {report.graph.get('roots', [])}")
    print(f"  - heads: {report.graph.get('heads', [])}")
    print(
        "  - status: "
        f"one_root={report.graph.get('exactly_one_root')} "
        f"one_head={report.graph.get('exactly_one_head')} "
        f"broken_refs={report.graph.get('has_broken_references')} "
        f"duplicate_revisions={report.graph.get('has_duplicate_revisions')}"
    )
    for scenario in (report.scenario_a, report.scenario_b, report.scenario_c):
        print(f"{scenario.name}: {'SUCCESS' if scenario.success else 'FAILURE'}")
        if scenario.error:
            print(f"  - error: {scenario.error}")
        if scenario.first_failure_operation:
            print(f"  - first_failure_operation: {scenario.first_failure_operation}")
        print(f"  - final_revision: {scenario.final_revision}")
        print(f"  - tables: {len(scenario.tables)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run disposable, local-only migration rehearsal scenarios for SchoolOS."
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write full JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    report = run_rehearsal(repo_root)

    _print_summary(report)
    if args.json_output:
        args.json_output.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
        print(f"JSON report written to: {args.json_output}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        print(f"SAFETY BLOCK: {exc}", file=sys.stderr)
        raise SystemExit(2)
