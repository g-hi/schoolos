from __future__ import annotations

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

from services.gateway.routers import academic_structure as acs
from shared.auth.dependencies import require_role
from shared.db.models import AcademicYear, Campus, Class, GradeLevel, Subject, SubjectOffering, Teacher


class _Result:
    def __init__(self, *, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _load_migration_module():
    path = Path("alembic/versions/4f2e1d9b7c30_phase_9b1_academic_structure_foundation.py")
    spec = importlib.util.spec_from_file_location("phase_9b1_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class _Inspector:
    def __init__(self, *, unique_constraints=None, indexes=None):
        self._unique_constraints = unique_constraints or []
        self._indexes = indexes or []

    def get_unique_constraints(self, table_name):
        return list(self._unique_constraints)

    def get_indexes(self, table_name):
        return list(self._indexes)


def _active_scope(tenant_id: uuid.UUID) -> tuple[Campus, AcademicYear, GradeLevel]:
    campus = Campus(id=uuid.uuid4(), tenant_id=tenant_id, name="Main", code="MAIN", is_active=True)
    year = AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=True,
    )
    level = GradeLevel(id=uuid.uuid4(), tenant_id=tenant_id, name="Grade 5", code="G5", sequence=5, is_active=True)
    return campus, year, level


@pytest.mark.asyncio
async def test_principal_and_school_admin_allowed_parent_and_teacher_denied() -> None:
    dependency = require_role("principal", "school_admin")
    await dependency(current_user=SimpleNamespace(role="principal"))
    await dependency(current_user=SimpleNamespace(role="school_admin"))

    with pytest.raises(HTTPException) as exc1:
        await dependency(current_user=SimpleNamespace(role="parent"))
    assert exc1.value.status_code == 403

    with pytest.raises(HTTPException) as exc2:
        await dependency(current_user=SimpleNamespace(role="teacher"))
    assert exc2.value.status_code == 403


@pytest.mark.asyncio
async def test_create_list_update_canonical_class_and_legacy_fields(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()
    campus, year, level = _active_scope(tenant.id)

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(acs, "log_action", audit)

    db.scalar.side_effect = [campus, year, level, None, None]
    created = await acs.create_class(
        acs.ClassCreateRequest(
            campus_id=campus.id,
            academic_year_id=year.id,
            grade_level_id=level.id,
            code="5A-HR",
            section="A",
            class_teacher_id=None,
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["grade"] == level.name
    assert created["academic_year"] == year.name
    assert created["section"] == "A"

    canonical_row = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=level.name,
        section="A",
        academic_year=year.name,
        campus_id=campus.id,
        academic_year_id=year.id,
        grade_level_id=level.id,
        code="5A-HR",
        is_active=True,
    )
    legacy_row = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade="Grade 4",
        section="B",
        academic_year="2025-2026",
        campus_id=None,
        academic_year_id=None,
        grade_level_id=None,
        code=None,
        is_active=True,
    )
    db.execute.return_value = _Result(
        rows=[
            (canonical_row, campus, year, level, None),
            (legacy_row, None, None, None, None),
        ]
    )
    listed = await acs.list_classes(tenant=tenant, actor=actor, db=db)
    assert len(listed) == 2
    assert listed[1]["campus_id"] is None
    assert listed[1]["grade"] == "Grade 4"

    existing = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=level.name,
        section="A",
        academic_year=year.name,
        campus_id=campus.id,
        academic_year_id=year.id,
        grade_level_id=level.id,
        code="5A-HR",
        is_active=True,
    )
    db.scalar.side_effect = [existing, campus, year, level, None, None]
    updated = await acs.update_class(
        existing.id,
        acs.ClassUpdateRequest(section="A1", code="5A-HR-1"),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["section"] == "A1"
    assert updated["grade"] == level.name
    assert updated["academic_year"] == year.name
    assert any(call.kwargs.get("action") == "academic_structure.class.updated" for call in audit.await_args_list)


@pytest.mark.asyncio
async def test_cross_tenant_or_inactive_class_references_rejected(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    db = _db()

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())

    with pytest.raises(HTTPException) as campus_exc:
        db.scalar.side_effect = [None]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=uuid.uuid4(),
                academic_year_id=uuid.uuid4(),
                grade_level_id=uuid.uuid4(),
                code="C1",
                section="A",
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert campus_exc.value.status_code == 422

    campus, year, level = _active_scope(tenant.id)
    with pytest.raises(HTTPException) as year_exc:
        db.scalar.side_effect = [campus, None]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=campus.id,
                academic_year_id=uuid.uuid4(),
                grade_level_id=level.id,
                code="C2",
                section="A",
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert year_exc.value.status_code == 422

    with pytest.raises(HTTPException) as level_exc:
        db.scalar.side_effect = [campus, year, None]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=campus.id,
                academic_year_id=year.id,
                grade_level_id=uuid.uuid4(),
                code="C3",
                section="A",
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert level_exc.value.status_code == 422

    with pytest.raises(HTTPException) as teacher_exc:
        db.scalar.side_effect = [campus, year, level, None]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=campus.id,
                academic_year_id=year.id,
                grade_level_id=level.id,
                code="C4",
                section="A",
                class_teacher_id=uuid.uuid4(),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert teacher_exc.value.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_canonical_class_rules_and_cross_campus_allowed(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()
    campus_a, year, level = _active_scope(tenant.id)
    campus_b = Campus(id=uuid.uuid4(), tenant_id=tenant.id, name="West", code="WEST", is_active=True)

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(acs, "log_action", AsyncMock())

    with pytest.raises(HTTPException) as dup_section_exc:
        db.scalar.side_effect = [campus_a, year, level, uuid.uuid4()]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=campus_a.id,
                academic_year_id=year.id,
                grade_level_id=level.id,
                code="X-1",
                section="A",
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert dup_section_exc.value.status_code == 409

    with pytest.raises(HTTPException) as dup_code_exc:
        db.scalar.side_effect = [campus_a, year, level, None, uuid.uuid4()]
        await acs.create_class(
            acs.ClassCreateRequest(
                campus_id=campus_a.id,
                academic_year_id=year.id,
                grade_level_id=level.id,
                code="X-1",
                section="B",
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert dup_code_exc.value.status_code == 409

    db.scalar.side_effect = [campus_b, year, level, None, None]
    created = await acs.create_class(
        acs.ClassCreateRequest(
            campus_id=campus_b.id,
            academic_year_id=year.id,
            grade_level_id=level.id,
            code="X-2",
            section="A",
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["campus_id"] == str(campus_b.id)


@pytest.mark.asyncio
async def test_class_activation_and_deactivation_audit(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()
    campus, year, level = _active_scope(tenant.id)

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(acs, "log_action", audit)

    item = Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=level.name,
        section="A",
        academic_year=year.name,
        campus_id=campus.id,
        academic_year_id=year.id,
        grade_level_id=level.id,
        code="5A",
        is_active=True,
    )

    db.scalar.side_effect = [item, campus, year, level]
    deactivated = await acs.update_class(
        item.id,
        acs.ClassUpdateRequest(is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert deactivated["is_active"] is False

    db.scalar.side_effect = [item, campus, year, level, None, None]
    activated = await acs.update_class(
        item.id,
        acs.ClassUpdateRequest(is_active=True),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert activated["is_active"] is True
    actions = [call.kwargs.get("action") for call in audit.await_args_list]
    assert "academic_structure.class.deactivated" in actions
    assert "academic_structure.class.activated" in actions


def test_no_hard_delete_routes() -> None:
    for route in acs.router.routes:
        methods = getattr(route, "methods", set())
        assert "DELETE" not in methods


@pytest.mark.asyncio
async def test_subject_offering_create_list_update_and_duplicate(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="school_admin")
    db = _db()
    campus, year, level = _active_scope(tenant.id)
    subject = Subject(id=uuid.uuid4(), tenant_id=tenant.id, name="Mathematics", code="MATH")

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(acs, "log_action", audit)

    db.scalar.side_effect = [campus, year, level, subject, None]
    created = await acs.create_subject_offering(
        acs.SubjectOfferingCreateRequest(
            campus_id=campus.id,
            academic_year_id=year.id,
            grade_level_id=level.id,
            subject_id=subject.id,
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert created["subject_code"] == "MATH"

    offering = SubjectOffering(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=campus.id,
        academic_year_id=year.id,
        grade_level_id=level.id,
        subject_id=subject.id,
        is_active=True,
    )
    db.execute.return_value = _Result(rows=[(offering, campus, year, level, subject)])
    listed = await acs.list_subject_offerings(tenant=tenant, actor=actor, db=db)
    assert len(listed) == 1

    db.scalar.side_effect = [offering, campus, year, level, subject, None]
    updated = await acs.update_subject_offering(
        offering.id,
        acs.SubjectOfferingUpdateRequest(is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["is_active"] is False

    with pytest.raises(HTTPException) as dup_exc:
        db.scalar.side_effect = [campus, year, level, subject, uuid.uuid4()]
        await acs.create_subject_offering(
            acs.SubjectOfferingCreateRequest(
                campus_id=campus.id,
                academic_year_id=year.id,
                grade_level_id=level.id,
                subject_id=subject.id,
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert dup_exc.value.status_code == 409

    actions = [call.kwargs.get("action") for call in audit.await_args_list]
    assert "academic_structure.subject_offering.created" in actions
    assert "academic_structure.subject_offering.deactivated" in actions


@pytest.mark.asyncio
async def test_subject_offering_cross_tenant_reference_rejected(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()
    campus, year, level = _active_scope(tenant.id)

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        db.scalar.side_effect = [campus, year, level, None]
        await acs.create_subject_offering(
            acs.SubjectOfferingCreateRequest(
                campus_id=campus.id,
                academic_year_id=year.id,
                grade_level_id=level.id,
                subject_id=uuid.uuid4(),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_summary_counts(monkeypatch) -> None:
    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), role="principal")
    db = _db()

    monkeypatch.setattr(acs, "set_tenant_context", AsyncMock())

    db.scalar.side_effect = [10, 6, 4, 5, 8, 3]
    payload = await acs.summary(tenant=tenant, actor=actor, db=db)
    assert payload["counts"]["total_classes"] == 10
    assert payload["counts"]["canonical_classes"] == 6
    assert payload["counts"]["legacy_classes"] == 4
    assert payload["counts"]["active_canonical_classes"] == 5
    assert payload["counts"]["subject_offerings"] == 8
    assert payload["counts"]["active_subject_offerings"] == 3


def test_class_and_subject_offering_model_parity() -> None:
    class_columns = {c.name for c in Class.__table__.columns}
    offering_columns = {c.name for c in SubjectOffering.__table__.columns}

    assert {"campus_id", "academic_year_id", "grade_level_id", "code", "is_active", "updated_at"} <= class_columns
    assert {"tenant_id", "campus_id", "academic_year_id", "grade_level_id", "subject_id", "is_active", "created_at", "updated_at"} <= offering_columns

    class_constraint_names = {getattr(c, "name", None) for c in Class.__table__.constraints}
    assert any((name or "").endswith("ck_classes_canonical_scope_all_or_none") for name in class_constraint_names)

    class_index_names = {idx.name for idx in Class.__table__.indexes}
    assert "uq_classes_legacy_identity" in class_index_names
    assert "uq_classes_canonical_section" in class_index_names
    assert "uq_classes_code_per_academic_year" in class_index_names

    offering_constraint_names = {getattr(c, "name", None) for c in SubjectOffering.__table__.constraints}
    assert "uq_subject_offering_scope" in offering_constraint_names

    offering_index_names = {idx.name for idx in SubjectOffering.__table__.indexes}
    assert {
        "ix_subject_offerings_tenant_id",
        "ix_subject_offerings_campus_id",
        "ix_subject_offerings_academic_year_id",
        "ix_subject_offerings_grade_level_id",
        "ix_subject_offerings_subject_id",
        "ix_subject_offerings_is_active",
    } <= offering_index_names


def test_migration_schema_drift_helpers_match_exact_columns_and_skip_unrelated() -> None:
    migration = _load_migration_module()

    inspector = _Inspector(
        unique_constraints=[
            {"name": "uq_class_per_tenant", "column_names": ["tenant_id", "grade", "section", "academic_year"]},
            {"name": "uq_classes_auto_named", "column_names": ["academic_year", "section", "grade", "tenant_id"]},
            {"name": "uq_unrelated", "column_names": ["tenant_id", "grade", "section"]},
            {"name": None, "column_names": ["tenant_id", "grade", "section", "academic_year"]},
        ],
        indexes=[
            {"name": "uq_class_per_tenant", "column_names": ["tenant_id", "grade", "section", "academic_year"], "unique": True},
            {"name": "uq_classes_unique_index", "column_names": ["academic_year", "tenant_id", "section", "grade"], "unique": True},
            {"name": "uq_classes_backing_constraint", "column_names": ["tenant_id", "grade", "section", "academic_year"], "unique": True, "duplicates_constraint": "uq_class_per_tenant"},
            {"name": "ix_unrelated", "column_names": ["tenant_id"], "unique": False},
        ],
    )

    assert set(migration._matching_legacy_unique_constraints(inspector)) == {"uq_class_per_tenant", "uq_classes_auto_named"}
    assert migration._matching_legacy_unique_indexes(inspector) == ["uq_classes_unique_index"]


def test_migration_drop_legacy_class_uniqueness_handles_absent_and_backing_indexes() -> None:
    migration = _load_migration_module()
    op = MagicMock()
    migration.op = op
    migration.sa.inspect = lambda bind: _Inspector(
        unique_constraints=[{"name": "uq_classes_auto_named", "column_names": ["tenant_id", "grade", "section", "academic_year"]}],
        indexes=[
            {"name": "uq_classes_auto_named", "column_names": ["tenant_id", "grade", "section", "academic_year"], "unique": True, "duplicates_constraint": "uq_classes_auto_named"},
            {"name": "uq_classes_unique_index", "column_names": ["academic_year", "section", "grade", "tenant_id"], "unique": True},
        ],
    )

    migration._drop_legacy_class_uniqueness(SimpleNamespace())

    assert [call.args[0] for call in op.drop_constraint.call_args_list] == ["uq_classes_auto_named"]
    assert [call.args[0] for call in op.drop_index.call_args_list] == ["uq_classes_unique_index"]


def test_migration_upgrade_aborts_on_duplicate_legacy_class_identities() -> None:
    migration = _load_migration_module()
    op = MagicMock()
    migration.op = op
    migration.sa.inspect = lambda bind: _Inspector(unique_constraints=[], indexes=[])

    bind = SimpleNamespace(execute=MagicMock(return_value=SimpleNamespace(first=lambda: (1,))))
    op.get_bind.return_value = bind

    with pytest.raises(RuntimeError, match="Duplicate legacy class identities must be resolved"):
        migration.upgrade()


def test_migration_downgrade_restores_legacy_constraint_when_missing() -> None:
    migration = _load_migration_module()
    op = MagicMock()
    migration.op = op
    migration.sa.inspect = lambda bind: _Inspector(unique_constraints=[], indexes=[])
    op.get_bind.return_value = SimpleNamespace()

    migration._restore_legacy_class_uniqueness_if_missing(op.get_bind())

    assert op.create_unique_constraint.call_args.args[0] == "uq_class_per_tenant"


def test_migration_downgrade_rejects_equivalent_existing_uniqueness() -> None:
    migration = _load_migration_module()
    op = MagicMock()
    migration.op = op
    migration.sa.inspect = lambda bind: _Inspector(
        unique_constraints=[{"name": "uq_legacy_other", "column_names": ["tenant_id", "grade", "section", "academic_year"]}],
        indexes=[],
    )
    op.get_bind.return_value = SimpleNamespace()

    with pytest.raises(RuntimeError, match="Equivalent legacy class uniqueness already exists"):
        migration._restore_legacy_class_uniqueness_if_missing(op.get_bind())


def test_migration_metadata_and_revision_still_match() -> None:
    migration = _load_migration_module()
    assert migration.revision == "4f2e1d9b7c30"
    assert migration.down_revision == "9a4d3b2c1f00"


def test_single_alembic_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()

    assert len(heads) == 1

    revision_chain = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }

    assert "4f2e1d9b7c30" in revision_chain
