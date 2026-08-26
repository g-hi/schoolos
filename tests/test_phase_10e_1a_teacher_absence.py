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

from shared.db.models import TeacherAbsence


MIGRATION_FILE = Path("alembic/versions/a1b2c3d4e5f6_phase_10e_1a_teacher_absence_foundation.py")
REVISION_ID = "a1b2c3d4e5f6"
DOWN_REVISION = "9a2e3d7c04b1"


def test_teacher_absence_model_columns_and_relationships() -> None:
    columns = {column.name for column in TeacherAbsence.__table__.columns}
    assert columns == {
        "id", "tenant_id", "teacher_id", "start_date", "end_date", "scope_type",
        "selected_periods", "reason_code", "private_note", "status", "source_type",
        "reported_by_user_id", "confirmed_by_user_id", "cancelled_by_user_id",
        "reported_at", "confirmed_at", "cancelled_at", "created_at", "updated_at",
    }
    assert {"tenant", "teacher", "reported_by_user", "confirmed_by_user", "cancelled_by_user"} <= set(TeacherAbsence.__mapper__.relationships.keys())


def test_teacher_absence_constraints_and_indexes() -> None:
    constraints = [constraint for constraint in TeacherAbsence.__table__.constraints if isinstance(constraint, CheckConstraint)]
    expressions = " ".join(str(constraint.sqltext) for constraint in constraints)
    assert "end_date >= start_date" in expressions
    assert "reported" in expressions and "closed" in expressions
    assert "whole_day" in expressions and "selected_periods" in expressions
    assert "selected_periods IS NULL" in expressions
    foreign_keys = {
        column.name
        for constraint in TeacherAbsence.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for column in constraint.columns
    }
    assert {"tenant_id", "teacher_id", "reported_by_user_id", "confirmed_by_user_id", "cancelled_by_user_id"} <= foreign_keys
    assert TeacherAbsence.__table__.c.reported_by_user_id.nullable is True
    reported_fk = next(iter(TeacherAbsence.__table__.c.reported_by_user_id.foreign_keys))
    assert reported_fk.ondelete == "SET NULL"
    assert {index.name for index in TeacherAbsence.__table__.indexes} == {
        "ix_teacher_absences_tenant_id", "ix_teacher_absences_teacher_id",
        "ix_teacher_absences_tenant_date", "ix_teacher_absences_tenant_teacher_date",
    }
    referenced_tables = {
        foreign_key.target_fullname.split(".")[0]
        for column in TeacherAbsence.__table__.columns
        for foreign_key in column.foreign_keys
    }
    assert referenced_tables == {"tenants", "teachers", "users"}


def _test_table() -> tuple[object, Table]:
    metadata = MetaData()
    for table_name in ("tenants", "teachers", "users"):
        Table(table_name, metadata, Column("id", String(36), primary_key=True))
    absence_table = TeacherAbsence.__table__.to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return engine, absence_table


def _absence_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "teacher_id": uuid.uuid4(),
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 2),
        "scope_type": "whole_day",
        "selected_periods": None,
        "reason_code": "sick",
        "status": "reported",
        "source_type": "teacher",
        "reported_by_user_id": uuid.uuid4(),
    }
    values.update(overrides)
    return values


def _assert_rejected(**overrides: object) -> None:
    engine, table = _test_table()
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(table.insert().values(**_absence_values(**overrides)))
    engine.dispose()


def test_valid_statuses_and_scopes_are_accepted() -> None:
    engine, table = _test_table()
    with engine.begin() as connection:
        for status in ("reported", "confirmed", "cancelled", "closed"):
            connection.execute(table.insert().values(**_absence_values(id=uuid.uuid4(), status=status)))
        connection.execute(table.insert().values(**_absence_values(id=uuid.uuid4(), scope_type="selected_periods", selected_periods=[1, 3])))
    engine.dispose()


def test_invalid_status_scope_and_date_range_are_rejected() -> None:
    _assert_rejected(status="pending")
    _assert_rejected(scope_type="partial_day")
    _assert_rejected(scope_type="whole_day", selected_periods=[1])
    _assert_rejected(scope_type="selected_periods", selected_periods=None)
    _assert_rejected(start_date=date(2026, 9, 3), end_date=date(2026, 9, 2))


def test_teacher_absence_migration_structure_and_single_head() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION_ID}"' in text
    assert f'down_revision: Union[str, None] = "{DOWN_REVISION}"' in text
    assert "teacher_absences" in text
    assert "def upgrade()" in text and "def downgrade()" in text
    identifiers = re.findall(r'(?:name|create_index|drop_index)=[("\']([^"\']+)', text)
    assert all(len(identifier) <= 63 for identifier in identifiers)

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION_ID]
    revision = script.get_revision(REVISION_ID)
    assert revision is not None and revision.down_revision == DOWN_REVISION
