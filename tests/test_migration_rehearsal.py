from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import rehearse_migrations as rm


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_requires_explicit_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rm.REHEARSAL_GATE_ENV, raising=False)
    with pytest.raises(rm.SafetyError):
        rm.require_rehearsal_gate()


def test_rejects_preconfigured_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/unsafe")
    with pytest.raises(rm.SafetyError):
        rm.reject_preconfigured_database_url()


def test_validate_disposable_url_rejects_nonlocal_host() -> None:
    with pytest.raises(rm.SafetyError):
        rm.validate_disposable_database_url(
            "postgresql://postgres:anything@db.production.example:5432/schoolos_rehearsal_x"
        )


def test_validate_disposable_url_rejects_nonrehearsal_db_name() -> None:
    with pytest.raises(rm.SafetyError):
        rm.validate_disposable_database_url(
            "postgresql://postgres:anything@127.0.0.1:5432/schoolos"
        )


def test_revision_graph_is_linear_and_single_head() -> None:
    graph = rm.analyze_revision_graph(_repo_root())

    assert graph["exactly_one_root"] is True
    assert graph["exactly_one_head"] is True
    assert graph["has_broken_references"] is False
    assert graph["has_duplicate_revisions"] is False


@pytest.mark.external_container
def test_disposable_rehearsal_end_to_end() -> None:
    if os.environ.get("SCHOOLOS_RUN_EXTERNAL_MIGRATION_REHEARSAL", "").lower() != "true":
        pytest.skip("External container rehearsal disabled. Set SCHOOLOS_RUN_EXTERNAL_MIGRATION_REHEARSAL=true")

    if not rm._docker_available():
        pytest.skip("Docker unavailable; external container rehearsal skipped")

    previous_database_url = os.environ.pop("DATABASE_URL", None)
    try:
        os.environ[rm.REHEARSAL_GATE_ENV] = rm.REHEARSAL_GATE_VALUE
        report = rm.run_rehearsal(_repo_root())

        assert report.graph["exactly_one_root"] is True
        assert report.graph["exactly_one_head"] is True

        if report.scenario_a.success is False:
            assert report.scenario_a.error
            assert report.scenario_a.first_failure_operation

        if report.scenario_b.success is False:
            assert report.scenario_b.error
            assert report.scenario_b.first_failure_operation
        else:
            assert report.scenario_b.final_revision

        if report.scenario_c.success is False:
            assert report.scenario_c.error
            assert report.scenario_c.first_failure_operation
        else:
            assert report.scenario_c.final_revision
            preservation = report.scenario_c.details.get("preservation_assertions", {})
            assert preservation.get("tenant_rows_preserved") is True
            assert preservation.get("user_rows_preserved") is True
            assert preservation.get("tenant_row_count_preserved") is True
            assert preservation.get("user_row_count_preserved") is True
    finally:
        if previous_database_url is not None:
            os.environ["DATABASE_URL"] = previous_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        os.environ.pop(rm.REHEARSAL_GATE_ENV, None)
