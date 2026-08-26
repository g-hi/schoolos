from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, MetaData, String, Table, create_engine
from sqlalchemy.exc import IntegrityError

from shared.db.models import OperationalAssignmentOverride, OperationalAssignmentRequest


MIGRATION_FILE = Path("alembic/versions/d4e5f6a7b8c9_phase_10e_3a_operational_assignment_contract.py")
REVISION_ID = "d4e5f6a7b8c9"
DOWN_REVISION = "a1b2c3d4e5f6"


def test_operational_assignment_models_declared() -> None:
    assert OperationalAssignmentRequest.__tablename__ == "operational_assignment_requests"
    assert OperationalAssignmentOverride.__tablename__ == "operational_assignment_overrides"
    assert {"tenant_id", "original_teacher_id", "teacher_absence", "daily_session", "duty_assignment", "overrides"} <= (
        set(OperationalAssignmentRequest.__table__.columns.keys())
        | set(OperationalAssignmentRequest.__mapper__.relationships.keys())
    )
    assert {"tenant_id", "assignment_request_id", "replacement_teacher_id"} <= set(
        OperationalAssignmentOverride.__table__.columns.keys()
    )
    assert "assignment_request" in OperationalAssignmentOverride.__mapper__.relationships.keys()


def _foreign_key_targets(model) -> set[str]:
    return {
        foreign_key.target_fullname.split(".")[0]
        for column in model.__table__.columns
        for foreign_key in column.foreign_keys
    }


def test_tenant_and_baseline_foreign_keys_are_correct() -> None:
    assert _foreign_key_targets(OperationalAssignmentRequest) == {
        "tenants", "teacher_absences", "teachers", "daily_sessions", "duty_assignments", "users",
    }
    assert _foreign_key_targets(OperationalAssignmentOverride) == {
        "tenants", "operational_assignment_requests", "daily_sessions", "duty_assignments", "teachers", "users",
    }


def _sqltext(model) -> str:
    constraints = [c for c in model.__table__.constraints if isinstance(c, CheckConstraint)]
    return " ".join(str(c.sqltext) for c in constraints)


def test_assignment_type_and_status_constraints_present() -> None:
    request_text = _sqltext(OperationalAssignmentRequest)
    assert "teaching_substitution" in request_text and "duty_reassignment" in request_text
    assert "pending" in request_text and "completed" in request_text

    override_text = _sqltext(OperationalAssignmentOverride)
    assert "teaching_substitution" in override_text and "duty_reassignment" in override_text
    assert "active" in override_text and "superseded" in override_text


def test_expected_indexes_exist() -> None:
    assert {i.name for i in OperationalAssignmentRequest.__table__.indexes} == {
        "ix_oar_tenant_school_date",
        "ix_oar_tenant_type_date", "ix_oar_daily_session", "ix_oar_duty_assignment", "ix_oar_teacher_date",
    }
    assert {i.name for i in OperationalAssignmentOverride.__table__.indexes} == {
        "ix_oao_tenant_school_date", "ix_oao_request_id",
        "ix_oao_daily_session", "ix_oao_duty_assignment", "ix_oao_teacher_date",
    }


def _ondelete(model, column_name: str) -> str | None:
    column = model.__table__.columns[column_name]
    return next(iter(column.foreign_keys)).ondelete


def test_target_fk_delete_behavior_is_restrict() -> None:
    assert _ondelete(OperationalAssignmentRequest, "daily_session_id") == "RESTRICT"
    assert _ondelete(OperationalAssignmentRequest, "duty_assignment_id") == "RESTRICT"
    assert _ondelete(OperationalAssignmentOverride, "daily_session_id") == "RESTRICT"
    assert _ondelete(OperationalAssignmentOverride, "duty_assignment_id") == "RESTRICT"


def test_actor_and_absence_fk_delete_behavior_remains_set_null() -> None:
    assert _ondelete(OperationalAssignmentRequest, "teacher_absence_id") == "SET NULL"
    assert _ondelete(OperationalAssignmentRequest, "created_by_user_id") == "SET NULL"
    assert _ondelete(OperationalAssignmentOverride, "approved_by_user_id") == "SET NULL"


def test_no_destructive_uniqueness_constraint_blocks_reassignment_history() -> None:
    for model in (OperationalAssignmentRequest, OperationalAssignmentOverride):
        unique_column_sets = {
            tuple(sorted(col.name for col in constraint.columns))
            for constraint in model.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert unique_column_sets == set()


def _reference_table(name: str) -> Table:
    return Table(name, MetaData(), Column("id", String(36), primary_key=True))


def _request_table():
    metadata = MetaData()
    for name in ("tenants", "teacher_absences", "teachers", "daily_sessions", "duty_assignments", "users"):
        Table(name, metadata, Column("id", String(36), primary_key=True))
    table = OperationalAssignmentRequest.__table__.to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return engine, table


def _request_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "assignment_type": "teaching_substitution",
        "school_date": date(2026, 9, 1),
        "original_teacher_id": uuid.uuid4(),
        "daily_session_id": uuid.uuid4(),
        "duty_assignment_id": None,
        "status": "pending",
    }
    values.update(overrides)
    return values


def _assert_request_rejected(**overrides: object) -> None:
    engine, table = _request_table()
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(table.insert().values(**_request_values(**overrides)))
    engine.dispose()


def test_valid_request_target_combinations_are_accepted() -> None:
    engine, table = _request_table()
    with engine.begin() as connection:
        connection.execute(table.insert().values(**_request_values()))
        connection.execute(table.insert().values(**_request_values(
            id=uuid.uuid4(),
            assignment_type="duty_reassignment",
            daily_session_id=None,
            duty_assignment_id=uuid.uuid4(),
        )))
    engine.dispose()


def test_teaching_request_requires_daily_session_and_rejects_duty_target() -> None:
    _assert_request_rejected(daily_session_id=None)
    _assert_request_rejected(duty_assignment_id=uuid.uuid4())


def test_duty_request_requires_duty_assignment_and_rejects_daily_session_target() -> None:
    _assert_request_rejected(assignment_type="duty_reassignment", daily_session_id=uuid.uuid4(), duty_assignment_id=None)
    _assert_request_rejected(assignment_type="duty_reassignment", daily_session_id=None, duty_assignment_id=None)


def test_invalid_assignment_type_and_status_are_rejected() -> None:
    _assert_request_rejected(assignment_type="ad_hoc_swap")
    _assert_request_rejected(status="in_progress")


def test_original_teacher_id_required() -> None:
    _assert_request_rejected(original_teacher_id=None)


def _override_table():
    metadata = MetaData()
    for name in ("tenants", "operational_assignment_requests", "daily_sessions", "duty_assignments", "teachers", "users"):
        Table(name, metadata, Column("id", String(36), primary_key=True))
    table = OperationalAssignmentOverride.__table__.to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return engine, table


def _override_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "assignment_request_id": uuid.uuid4(),
        "school_date": date(2026, 9, 1),
        "assignment_type": "teaching_substitution",
        "daily_session_id": uuid.uuid4(),
        "duty_assignment_id": None,
        "replacement_teacher_id": uuid.uuid4(),
        "status": "active",
    }
    values.update(overrides)
    return values


def _assert_override_rejected(**overrides: object) -> None:
    engine, table = _override_table()
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(table.insert().values(**_override_values(**overrides)))
    engine.dispose()


def test_override_target_consistency_follows_assignment_type() -> None:
    _assert_override_rejected(daily_session_id=None)
    _assert_override_rejected(duty_assignment_id=uuid.uuid4())
    _assert_override_rejected(assignment_type="duty_reassignment", daily_session_id=uuid.uuid4(), duty_assignment_id=None)


def test_override_replacement_teacher_id_required() -> None:
    _assert_override_rejected(replacement_teacher_id=None)


def test_override_history_preserves_multiple_rows_for_same_request() -> None:
    engine, table = _override_table()
    request_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(table.insert().values(**_override_values(id=uuid.uuid4(), assignment_request_id=request_id, status="superseded")))
        connection.execute(table.insert().values(**_override_values(id=uuid.uuid4(), assignment_request_id=request_id, status="active")))
        rows = connection.execute(table.select()).fetchall()
    assert len(rows) == 2
    engine.dispose()


def test_migration_structure_and_single_head() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION_ID}"' in text
    assert f'down_revision: Union[str, None] = "{DOWN_REVISION}"' in text
    assert "operational_assignment_requests" in text
    assert "operational_assignment_overrides" in text
    assert "def upgrade()" in text and "def downgrade()" in text

    identifiers = re.findall(r'(?:name|create_index|drop_index)=?[("\']([^"\']+)', text)
    assert all(len(identifier) <= 63 for identifier in identifiers)

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION_ID]
    revision = script.get_revision(REVISION_ID)
    assert revision is not None and revision.down_revision == DOWN_REVISION


def test_migration_does_not_touch_unrelated_tables() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "alter_column" not in text
    assert "op.execute" not in text
    for forbidden_table in ("daily_sessions\", sa.Column", "duty_assignments\", sa.Column", "timetable_version_assignments\", sa.Column", "substitutions\", sa.Column"):
        assert forbidden_table not in text
