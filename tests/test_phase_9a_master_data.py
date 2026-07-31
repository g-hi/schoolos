from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException

from services.gateway.routers import master_data as md
from shared.auth.dependencies import require_role
from shared.db.models import AcademicYear, Campus, GradeLevel, Term


class _Result:
    def __init__(self, *, rows=None):
        self._rows = rows or []

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_principal_and_school_admin_allowed_parent_denied() -> None:
    dependency = require_role("principal", "school_admin")
    await dependency(current_user=SimpleNamespace(role="principal"))
    await dependency(current_user=SimpleNamespace(role="school_admin"))
    with pytest.raises(HTTPException) as exc:
        await dependency(current_user=SimpleNamespace(role="parent"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_campus_create_list_update_and_deactivate_with_audit(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(md, "log_action", audit)

    db.scalar.side_effect = [None]
    created = await md.create_campus(
        md.CampusCreateRequest(name="Main Campus", code="main", description="HQ", is_active=True),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["code"] == "MAIN"
    assert created["is_active"] is True

    campus = Campus(id=uuid.uuid4(), tenant_id=tenant.id, name="Main Campus", code="MAIN", description="HQ", is_active=True)
    db.execute.return_value = _Result(rows=[campus])
    rows = await md.list_campuses(tenant=tenant, actor=actor, db=db)
    assert len(rows) == 1
    stmt = db.execute.call_args.args[0]
    assert tenant.id in stmt.compile().params.values()

    db.scalar.side_effect = [campus, None]
    updated = await md.update_campus(
        campus.id,
        md.CampusUpdateRequest(name="Main Campus Updated", is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["name"] == "Main Campus Updated"
    assert updated["is_active"] is False
    assert any(call.kwargs.get("action") == "master_data.campus.deactivated" for call in audit.await_args_list)


@pytest.mark.asyncio
async def test_academic_year_create_list_update_and_invalid_dates(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await md.create_academic_year(
            md.AcademicYearCreateRequest(
                name="2026-2027",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 1),
                is_current=False,
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    previous_current = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date=date(2025, 9, 1),
        end_date=date(2026, 6, 30),
        is_current=True,
        is_active=True,
    )
    db.execute.return_value = _Result(rows=[previous_current])
    db.scalar.side_effect = [None]
    created = await md.create_academic_year(
        md.AcademicYearCreateRequest(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_current=True,
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["is_current"] is True
    assert previous_current.is_current is False

    year = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=True,
    )
    db.execute.return_value = _Result(rows=[year])
    rows = await md.list_academic_years(tenant=tenant, actor=actor, db=db)
    assert rows[0]["name"] == "2026-2027"

    db.scalar.side_effect = [year, None]
    updated = await md.update_academic_year(
        year.id,
        md.AcademicYearUpdateRequest(name="2026-2027 A", is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["name"] == "2026-2027 A"
    assert updated["is_active"] is False


@pytest.mark.asyncio
async def test_create_current_year_clears_previous_current_same_tenant_only(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    other_tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    current_same_tenant = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date=date(2025, 9, 1),
        end_date=date(2026, 6, 30),
        is_current=True,
        is_active=True,
    )
    current_other_tenant = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        name="2025-2026",
        start_date=date(2025, 9, 1),
        end_date=date(2026, 6, 30),
        is_current=True,
        is_active=True,
    )

    async def _execute(statement):
        params = statement.compile().params
        scoped_tenant = next((value for key, value in params.items() if key.startswith("tenant_id")), None)
        if scoped_tenant == tenant.id:
            return _Result(rows=[current_same_tenant])
        if scoped_tenant == other_tenant.id:
            return _Result(rows=[current_other_tenant])
        return _Result(rows=[])

    db.execute.side_effect = _execute
    db.scalar.side_effect = [None]

    created = await md.create_academic_year(
        md.AcademicYearCreateRequest(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_current=True,
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["is_current"] is True
    assert current_same_tenant.is_current is False
    assert current_other_tenant.is_current is True


@pytest.mark.asyncio
async def test_update_to_current_clears_previous_current(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    previous_current = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date=date(2025, 9, 1),
        end_date=date(2026, 6, 30),
        is_current=True,
        is_active=True,
    )
    to_promote = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=False,
        is_active=True,
    )

    async def _execute(statement):
        return _Result(rows=[previous_current])

    db.execute.side_effect = _execute
    db.scalar.side_effect = [to_promote, None]

    updated = await md.update_academic_year(
        to_promote.id,
        md.AcademicYearUpdateRequest(is_current=True),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["is_current"] is True
    assert previous_current.is_current is False


@pytest.mark.asyncio
async def test_term_creation_validation_and_cross_tenant_year_rejection(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    year = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=True,
    )

    db.scalar.side_effect = [year, None]
    created = await md.create_term(
        md.TermCreateRequest(
            academic_year_id=year.id,
            name="Term 1",
            code="t1",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 20),
            sequence=1,
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["code"] == "T1"

    db.scalar.side_effect = [year]
    with pytest.raises(HTTPException) as exc:
        await md.create_term(
            md.TermCreateRequest(
                academic_year_id=year.id,
                name="Term 2",
                code="T2",
                start_date=date(2027, 7, 1),
                end_date=date(2027, 7, 20),
                sequence=2,
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    db.scalar.side_effect = [None]
    with pytest.raises(HTTPException) as exc2:
        await md.create_term(
            md.TermCreateRequest(
                academic_year_id=uuid.uuid4(),
                name="Invalid",
                code="INV",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 12, 1),
                sequence=1,
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 422


@pytest.mark.asyncio
async def test_grade_level_create_list_update_and_duplicate(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    db.scalar.side_effect = [None]
    created = await md.create_grade_level(
        md.GradeLevelCreateRequest(name="Grade 1", code="g1", sequence=1, is_active=True),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["code"] == "G1"

    level = GradeLevel(id=uuid.uuid4(), tenant_id=tenant.id, name="Grade 1", code="G1", sequence=1, is_active=True)
    db.execute.return_value = _Result(rows=[level])
    rows = await md.list_grade_levels(tenant=tenant, actor=actor, db=db)
    assert rows[0]["sequence"] == 1

    db.scalar.side_effect = [level, None]
    updated = await md.update_grade_level(
        level.id,
        md.GradeLevelUpdateRequest(name="Grade One", is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["name"] == "Grade One"
    assert updated["is_active"] is False

    db.scalar.side_effect = [uuid.uuid4()]
    with pytest.raises(HTTPException) as exc:
        await md.create_grade_level(
            md.GradeLevelCreateRequest(name="Grade X", code="G1", sequence=2, is_active=True),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_tenant_isolation_update_not_found_and_duplicate_detection(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(md, "log_action", AsyncMock())

    db.scalar.side_effect = [None]
    with pytest.raises(HTTPException) as exc:
        await md.update_campus(
            uuid.uuid4(),
            md.CampusUpdateRequest(name="Nope"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 404

    year = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=True,
    )
    term = Term(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=year.id,
        name="Term 1",
        code="T1",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 1),
        sequence=1,
        is_active=True,
    )
    db.scalar.side_effect = [term, year, uuid.uuid4()]
    with pytest.raises(HTTPException) as exc2:
        await md.update_term(
            term.id,
            md.TermUpdateRequest(code="T1"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 409


@pytest.mark.asyncio
async def test_setup_summary_counts_and_readiness(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(md, "set_tenant_context", AsyncMock())

    db.scalar.side_effect = [1, 1, 2, 3]
    summary = await md.setup_summary(tenant=tenant, actor=actor, db=db)
    assert summary["counts"]["campuses"] == 1
    assert summary["counts"]["terms"] == 2
    assert summary["readiness"]["is_master_data_configured"] is True


def test_model_constraints_and_columns_present() -> None:
    campus_columns = {c.name for c in Campus.__table__.columns}
    year_columns = {c.name for c in AcademicYear.__table__.columns}
    term_columns = {c.name for c in Term.__table__.columns}
    grade_columns = {c.name for c in GradeLevel.__table__.columns}

    assert {"tenant_id", "name", "code", "is_active", "created_at", "updated_at"} <= campus_columns
    assert {"tenant_id", "name", "start_date", "end_date", "is_current", "is_active"} <= year_columns
    assert {"tenant_id", "academic_year_id", "name", "code", "start_date", "end_date", "sequence", "is_active"} <= term_columns
    assert {"tenant_id", "name", "code", "sequence", "is_active"} <= grade_columns

    campus_constraints = {getattr(c, "name", None) for c in Campus.__table__.constraints}
    year_constraints = {getattr(c, "name", None) for c in AcademicYear.__table__.constraints}
    term_constraints = {getattr(c, "name", None) for c in Term.__table__.constraints}
    grade_constraints = {getattr(c, "name", None) for c in GradeLevel.__table__.constraints}

    assert "uq_campus_code_per_tenant" in campus_constraints
    assert "uq_academic_year_name_per_tenant" in year_constraints
    assert "uq_term_code_per_year_per_tenant" in term_constraints
    assert "uq_grade_level_code_per_tenant" in grade_constraints
    assert any((name or "").endswith("ck_terms_sequence_positive") for name in term_constraints)
    assert any((name or "").endswith("ck_grade_levels_sequence_positive") for name in grade_constraints)


def test_migration_parity_and_single_head() -> None:
    path = Path("alembic/versions/9a4d3b2c1f00_phase_9a_master_data_foundation.py")
    spec = importlib.util.spec_from_file_location("phase_9a_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "9a4d3b2c1f00"
    assert migration.down_revision == "e1f4a2c9d113"

    op = MagicMock()
    migration.op = op
    migration.upgrade()
    migration.downgrade()

    created_tables = {call.args[0] for call in op.create_table.call_args_list}
    assert created_tables == {"campuses", "academic_years", "terms", "grade_levels"}

    partial_unique_index_calls = [
        call for call in op.create_index.call_args_list if call.args and call.args[0] == "uq_academic_year_current_per_tenant"
    ]
    assert len(partial_unique_index_calls) == 1
    assert partial_unique_index_calls[0].kwargs.get("unique") is True
    assert str(partial_unique_index_calls[0].kwargs.get("postgresql_where")) == "is_current IS TRUE"

    assert op.drop_table.call_args_list[0].args[0] == "grade_levels"
    assert op.drop_table.call_args_list[-1].args[0] == "campuses"

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
