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

from services.gateway.routers import student_enrollments as se
from shared.db.models import AcademicYear, Class, GradeLevel, Student, StudentEnrollment


class _Result:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def all(self):
        return self._rows


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _load_migration_module():
    path = Path("alembic/versions/8c3f2b1e9d77_phase_9b3_student_enrollments.py")
    spec = importlib.util.spec_from_file_location("phase_9b3_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(tenant: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="principal")


def _year(tenant: SimpleNamespace, *, is_active: bool = True) -> AcademicYear:
    return AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=is_active,
    )


def _grade_level(tenant: SimpleNamespace, *, is_active: bool = True) -> GradeLevel:
    return GradeLevel(id=uuid.uuid4(), tenant_id=tenant.id, name="Grade 5", code="G5", sequence=5, is_active=is_active)


def _canonical_class(
    tenant: SimpleNamespace,
    *,
    year: AcademicYear,
    grade_level: GradeLevel,
    code: str = "5A",
    section: str = "A",
    is_active: bool = True,
) -> Class:
    return Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=grade_level.name,
        section=section,
        academic_year=year.name,
        class_teacher_id=None,
        campus_id=uuid.uuid4(),
        academic_year_id=year.id,
        grade_level_id=grade_level.id,
        code=code,
        is_active=is_active,
    )


def _student(tenant: SimpleNamespace, klass: Class) -> Student:
    return Student(id=uuid.uuid4(), tenant_id=tenant.id, class_id=klass.id, name="Student One", student_code="S1")


def _enrollment(
    tenant: SimpleNamespace,
    *,
    student: Student,
    klass: Class,
    year: AcademicYear,
    grade_level: GradeLevel,
    status: str = "active",
    enrolled_on: date = date(2026, 9, 1),
    exited_on: date | None = None,
) -> StudentEnrollment:
    return StudentEnrollment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=year.id,
        student_id=student.id,
        class_id=klass.id,
        grade_level_id=grade_level.id,
        status=status,
        enrolled_on=enrolled_on,
        exited_on=exited_on,
        exit_reason=None,
    )


@pytest.mark.asyncio
async def test_create_enrollment_dual_writes_student_class_id(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    db = _db()

    year = _year(tenant)
    grade_level = _grade_level(tenant)
    klass = _canonical_class(tenant, year=year, grade_level=grade_level)
    student = _student(tenant, klass)
    target_class = _canonical_class(tenant, year=year, grade_level=grade_level, code="5B", section="B")

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(se, "log_action", audit)

    db.scalar.side_effect = [student, target_class, year, grade_level, None]

    payload = await se.create_student_enrollment(
        se.StudentEnrollmentCreateRequest(
            student_id=student.id,
            class_id=target_class.id,
            enrolled_on=date(2026, 9, 2),
            status="active",
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )

    assert payload["status"] == "active"
    assert payload["class_id"] == str(target_class.id)
    assert student.class_id == target_class.id
    assert any(call.kwargs.get("action") == "student_enrollment.created" for call in audit.await_args_list)


@pytest.mark.asyncio
async def test_create_enrollment_rejects_non_active_status(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    db = _db()

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await se.create_student_enrollment(
            se.StudentEnrollmentCreateRequest(
                student_id=uuid.uuid4(),
                class_id=uuid.uuid4(),
                enrolled_on=date(2026, 9, 2),
                status="completed",
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_withdrawn_requires_exited_on(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    db = _db()

    year = _year(tenant)
    grade_level = _grade_level(tenant)
    klass = _canonical_class(tenant, year=year, grade_level=grade_level)
    student = _student(tenant, klass)
    enrollment = _enrollment(tenant, student=student, klass=klass, year=year, grade_level=grade_level)

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())

    db.scalar.side_effect = [enrollment]
    db.execute.side_effect = [_Result(first=(student, klass, year, grade_level))]

    with pytest.raises(HTTPException) as exc:
        await se.update_student_enrollment(
            enrollment.id,
            se.StudentEnrollmentUpdateRequest(status="withdrawn"),
            tenant=tenant,
            actor=actor,
            db=db,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_transfer_closes_source_creates_destination_and_updates_student_pointer(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    db = _db()

    year = _year(tenant)
    grade_5 = _grade_level(tenant)
    grade_6 = GradeLevel(id=uuid.uuid4(), tenant_id=tenant.id, name="Grade 6", code="G6", sequence=6, is_active=True)
    source_class = _canonical_class(tenant, year=year, grade_level=grade_5, code="5A", section="A")
    destination_class = _canonical_class(tenant, year=year, grade_level=grade_6, code="6A", section="A")
    student = _student(tenant, source_class)
    source_enrollment = _enrollment(tenant, student=student, klass=source_class, year=year, grade_level=grade_5)

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(se, "log_action", audit)

    db.scalar.side_effect = [
        source_enrollment,
        student,
        source_class,
        year,
        destination_class,
        grade_6,
        None,
        grade_5,
    ]

    payload = await se.transfer_student_enrollment(
        source_enrollment.id,
        se.StudentEnrollmentTransferRequest(
            new_class_id=destination_class.id,
            transfer_date=date(2026, 10, 1),
            reason="Promoted to next stream",
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )

    assert payload["source_enrollment"]["status"] == "transferred"
    assert payload["source_enrollment"]["class_id"] == str(source_class.id)
    assert payload["destination_enrollment"]["status"] == "active"
    assert payload["destination_enrollment"]["class_id"] == str(destination_class.id)
    assert student.class_id == destination_class.id

    actions = [call.kwargs.get("action") for call in audit.await_args_list]
    assert "student_enrollment.transferred" in actions
    assert "student_enrollment.transfer_destination_created" in actions


@pytest.mark.asyncio
async def test_summary_returns_expected_shape(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    db = _db()

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())

    active_student_id = uuid.uuid4()
    class_id = uuid.uuid4()
    grade_level_id = uuid.uuid4()

    db.scalar.side_effect = [7, 3, 2, 1, 1, 4]
    db.execute.side_effect = [
        _Result(rows=[(active_student_id,)]),
        _Result(rows=[(class_id, "5A", "A", 3)]),
        _Result(rows=[(grade_level_id, "Grade 5", 3)]),
    ]

    payload = await se.student_enrollment_summary(tenant=tenant, actor=actor, db=db)

    assert payload["total_enrollments"] == 7
    assert payload["active_enrollments"] == 3
    assert payload["students_with_active_canonical_enrollment"] == 1
    assert payload["students_with_legacy_class_id_but_no_canonical_enrollment"] == 4
    assert payload["active_enrollments_by_class"][0]["class_id"] == str(class_id)
    assert payload["active_enrollments_by_grade_level"][0]["grade_level_id"] == str(grade_level_id)


def test_router_exposes_required_routes_and_no_delete_surface() -> None:
    route_map = {
        (method, route.path)
        for route in se.router.routes
        for method in route.methods or set()
    }

    assert ("GET", "/leadership/student-enrollments") in route_map
    assert ("POST", "/leadership/student-enrollments") in route_map
    assert ("PATCH", "/leadership/student-enrollments/{enrollment_id}") in route_map
    assert ("POST", "/leadership/student-enrollments/{enrollment_id}/transfer") in route_map
    assert ("GET", "/leadership/student-enrollments/summary") in route_map
    assert all(method != "DELETE" for method, path in route_map if path.startswith("/leadership/student-enrollments"))


def test_migration_parity_and_single_head() -> None:
    migration = _load_migration_module()
    assert migration.revision == "8c3f2b1e9d77"
    assert migration.down_revision == "7d1b8a5c4e10"

    op = MagicMock()
    migration.op = op
    migration.upgrade()
    migration.downgrade()

    created_tables = {call.args[0] for call in op.create_table.call_args_list}
    assert created_tables == {"student_enrollments"}

    index_names = {call.args[0] for call in op.create_index.call_args_list if call.args}
    assert "uq_student_enrollments_active_student_year" in index_names
    assert "ix_student_enrollments_tenant_id" in index_names
    assert "ix_student_enrollments_status" in index_names

    assert op.drop_table.call_args_list[0].args[0] == "student_enrollments"

    model_columns = {column.name for column in StudentEnrollment.__table__.columns}
    assert {
        "tenant_id",
        "academic_year_id",
        "student_id",
        "class_id",
        "grade_level_id",
        "status",
        "enrolled_on",
        "exited_on",
        "exit_reason",
        "created_at",
        "updated_at",
    } <= model_columns

    constraint_names = {getattr(c, "name", None) for c in StudentEnrollment.__table__.constraints}
    assert any(name and name.endswith("ck_student_enrollments_status") for name in constraint_names)
    assert any(name and name.endswith("ck_student_enrollments_exit_presence") for name in constraint_names)
    assert any(name and name.endswith("ck_student_enrollments_date_range") for name in constraint_names)

    model_indexes = {index.name for index in StudentEnrollment.__table__.indexes}
    assert {
        "uq_student_enrollments_active_student_year",
        "ix_student_enrollments_tenant_id",
        "ix_student_enrollments_academic_year_id",
        "ix_student_enrollments_student_id",
        "ix_student_enrollments_class_id",
        "ix_student_enrollments_grade_level_id",
        "ix_student_enrollments_status",
    } <= model_indexes

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "8c3f2b1e9d77"
