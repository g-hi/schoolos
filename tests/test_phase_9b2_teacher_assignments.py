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
from pydantic import ValidationError

from services.gateway.routers import teacher_assignments as ta
from shared.auth.dependencies import require_role
from shared.db.models import AcademicYear, Campus, Class, GradeLevel, Subject, SubjectOffering, Teacher, TeacherAssignment, TeacherSubject, User


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, first=None, scalar=None, rows=None):
        self._first = first
        self._scalar = scalar
        self._rows = rows or []

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _Rows(self._rows)

    def all(self):
        return self._rows


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _load_migration_module():
    path = Path("alembic/versions/7d1b8a5c4e10_phase_9b2_teacher_assignment_schema.py")
    spec = importlib.util.spec_from_file_location("phase_9b2_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(tenant: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="principal")


def _teacher_context(tenant: SimpleNamespace, *, active_user: bool = True) -> tuple[Teacher, User]:
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Teacher One",
        email="teacher@example.test",
        phone=None,
        role="teacher",
        password_hash=None,
        is_active=active_user,
        preferred_channel="email",
    )
    teacher = Teacher(id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id, employee_id="T1", max_weekly_hours=20, max_substitutions_per_week=2)
    return teacher, user


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


def _campus(tenant: SimpleNamespace, *, is_active: bool = True) -> Campus:
    return Campus(id=uuid.uuid4(), tenant_id=tenant.id, name="Main", code="MAIN", is_active=is_active)


def _canonical_class(tenant: SimpleNamespace, *, academic_year: AcademicYear, grade_level: GradeLevel, campus: Campus, is_active: bool = True, class_teacher_id=None, code: str = "5A") -> Class:
    return Class(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        grade=grade_level.name,
        section="A",
        academic_year=academic_year.name,
        class_teacher_id=class_teacher_id,
        campus_id=campus.id,
        academic_year_id=academic_year.id,
        grade_level_id=grade_level.id,
        code=code,
        is_active=is_active,
    )


def _subject(tenant: SimpleNamespace) -> Subject:
    return Subject(id=uuid.uuid4(), tenant_id=tenant.id, name="Mathematics", code="MATH")


def _offering(tenant: SimpleNamespace, *, campus: Campus, year: AcademicYear, grade_level: GradeLevel, subject: Subject, is_active: bool = True) -> SubjectOffering:
    return SubjectOffering(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campus_id=campus.id,
        academic_year_id=year.id,
        grade_level_id=grade_level.id,
        subject_id=subject.id,
        is_active=is_active,
    )


def _assignment(tenant: SimpleNamespace, *, year: AcademicYear, teacher: Teacher, klass: Class, assignment_type: str, subject_offering_id=None, start_date=date(2026, 9, 1), end_date=date(2027, 6, 1), is_active: bool = True) -> TeacherAssignment:
    return TeacherAssignment(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=year.id,
        teacher_id=teacher.id,
        class_id=klass.id,
        subject_offering_id=subject_offering_id,
        assignment_type=assignment_type,
        start_date=start_date,
        end_date=end_date,
        is_active=is_active,
    )


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
async def test_homeroom_assignment_creation_dual_writes_class_teacher_id(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus, class_teacher_id=None)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(ta, "log_action", audit)

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, klass, grade_level, None]

    result = await ta.create_teacher_assignment(
        ta.TeacherAssignmentCreateRequest(
            academic_year_id=year.id,
            teacher_id=teacher.id,
            class_id=klass.id,
            assignment_type="homeroom",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )

    assert result["assignment_type"] == "homeroom"
    assert result["subject_offering_id"] is None
    assert klass.class_teacher_id == teacher.id
    assert any(call.kwargs.get("action") == "teacher_assignment.created" for call in audit.await_args_list)


@pytest.mark.asyncio
async def test_existing_different_class_teacher_returns_409(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    other_teacher = SimpleNamespace(id=uuid.uuid4())
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus, class_teacher_id=other_teacher.id)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, klass, grade_level]

    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_subject_teacher_assignment_creation(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus, class_teacher_id=None)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(ta, "log_action", audit)

    db.execute.side_effect = [
        _Result(first=(teacher, user)),
        _Result(first=(offering, subject)),
    ]
    db.scalar.side_effect = [year, klass, grade_level, TeacherSubject(teacher_id=teacher.id, subject_id=subject.id), None]

    result = await ta.create_teacher_assignment(
        ta.TeacherAssignmentCreateRequest(
            academic_year_id=year.id,
            teacher_id=teacher.id,
            class_id=klass.id,
            subject_offering_id=offering.id,
            assignment_type="subject_teacher",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )

    assert result["assignment_type"] == "subject_teacher"
    assert result["subject_offering_id"] == str(offering.id)
    assert result["subject_id"] == str(subject.id)
    assert klass.class_teacher_id is None


@pytest.mark.asyncio
async def test_homeroom_forbids_subject_offering_and_teacher_subject_qualification_required(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=offering.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    db.execute.side_effect = [
        _Result(first=(teacher, user)),
        _Result(first=(offering, subject)),
    ]
    db.scalar.side_effect = [year, klass, grade_level, None]
    with pytest.raises(HTTPException) as exc2:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=offering.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 422


@pytest.mark.asyncio
async def test_subject_teacher_requires_offering_and_tenant_validation(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=None)]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 404

    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=None)]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc2:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=offering.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 404


@pytest.mark.asyncio
async def test_canonical_class_and_scope_mismatches_rejected(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    other_campus = _campus(tenant)
    other_year = _year(tenant)
    other_grade_level = _grade_level(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    inactive_class = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus, is_active=False)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, Class(id=uuid.uuid4(), tenant_id=tenant.id, grade=grade_level.name, section="A", academic_year=year.name, class_teacher_id=None, campus_id=None, academic_year_id=None, grade_level_id=None, code="5A", is_active=True)]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(offering, subject))]
    db.scalar.side_effect = [other_year, klass, grade_level]
    with pytest.raises(HTTPException) as exc2:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=other_year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=offering.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 422

    bad_offering_year = _offering(tenant, campus=campus, year=other_year, grade_level=grade_level, subject=subject)
    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(bad_offering_year, subject))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc3:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=bad_offering_year.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc3.value.status_code == 422

    bad_offering_campus = _offering(tenant, campus=other_campus, year=year, grade_level=grade_level, subject=subject)
    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(bad_offering_campus, subject))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc4:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=bad_offering_campus.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc4.value.status_code == 422

    bad_offering_grade = _offering(tenant, campus=campus, year=year, grade_level=other_grade_level, subject=subject)
    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(bad_offering_grade, subject))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc5:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=bad_offering_grade.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc5.value.status_code == 422

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, inactive_class, grade_level]
    with pytest.raises(HTTPException) as exc6:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=inactive_class.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc6.value.status_code == 422


@pytest.mark.asyncio
async def test_inactive_master_data_and_cross_tenant_records_rejected(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant, is_active=False)
    active_year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=active_year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    active_offering = _offering(tenant, campus=campus, year=active_year, grade_level=grade_level, subject=subject)
    inactive_offering = _offering(tenant, campus=campus, year=active_year, grade_level=grade_level, subject=subject, is_active=False)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(inactive_offering, subject))]
    db.scalar.side_effect = [active_year, klass, grade_level]
    with pytest.raises(HTTPException) as exc2:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=active_year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=inactive_offering.id,
                assignment_type="subject_teacher",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 422

    db.execute.side_effect = [_Result(first=None)]
    with pytest.raises(HTTPException) as exc3:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=active_year.id,
                teacher_id=uuid.uuid4(),
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc3.value.status_code == 404


@pytest.mark.asyncio
async def test_invalid_date_range_and_outside_year_rejected(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2027, 7, 1),
                end_date=date(2027, 6, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 422

    db.execute.side_effect = [_Result(first=(teacher, user)), _Result(first=(offering, subject))]
    db.scalar.side_effect = [year, klass, grade_level]
    with pytest.raises(HTTPException) as exc2:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher.id,
                class_id=klass.id,
                subject_offering_id=offering.id,
                assignment_type="subject_teacher",
                start_date=date(2025, 8, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc2.value.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_active_assignments_and_shared_offering_across_teachers(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher1, user1 = _teacher_context(tenant)
    teacher2, user2 = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(ta, "log_action", AsyncMock())

    db.execute.side_effect = [_Result(first=(teacher1, user1))]
    db.scalar.side_effect = [year, klass, grade_level, None]
    first = await ta.create_teacher_assignment(
        ta.TeacherAssignmentCreateRequest(
            academic_year_id=year.id,
            teacher_id=teacher1.id,
            class_id=klass.id,
            assignment_type="homeroom",
            start_date=date(2026, 9, 1),
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert first["assignment_type"] == "homeroom"

    db.execute.side_effect = [_Result(first=(teacher2, user2))]
    db.scalar.side_effect = [year, klass, grade_level, uuid.uuid4()]
    with pytest.raises(HTTPException) as exc:
        await ta.create_teacher_assignment(
            ta.TeacherAssignmentCreateRequest(
                academic_year_id=year.id,
                teacher_id=teacher2.id,
                class_id=klass.id,
                assignment_type="homeroom",
                start_date=date(2026, 9, 1),
                is_active=True,
            ),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 409

    db.execute.side_effect = [
        _Result(first=(teacher1, user1)),
        _Result(first=(offering, subject)),
    ]
    db.scalar.side_effect = [year, klass, grade_level, TeacherSubject(teacher_id=teacher1.id, subject_id=subject.id), None]
    first_subject = await ta.create_teacher_assignment(
        ta.TeacherAssignmentCreateRequest(
            academic_year_id=year.id,
            teacher_id=teacher1.id,
            class_id=klass.id,
            subject_offering_id=offering.id,
            assignment_type="subject_teacher",
            start_date=date(2026, 9, 1),
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert first_subject["subject_offering_id"] == str(offering.id)

    db.execute.side_effect = [
        _Result(first=(teacher2, user2)),
        _Result(first=(offering, subject)),
    ]
    db.scalar.side_effect = [year, klass, grade_level, TeacherSubject(teacher_id=teacher2.id, subject_id=subject.id), None]
    second_subject = await ta.create_teacher_assignment(
        ta.TeacherAssignmentCreateRequest(
            academic_year_id=year.id,
            teacher_id=teacher2.id,
            class_id=klass.id,
            subject_offering_id=offering.id,
            assignment_type="subject_teacher",
            start_date=date(2026, 9, 1),
            is_active=True,
        ),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert second_subject["teacher_id"] == str(teacher2.id)


@pytest.mark.asyncio
async def test_patch_updates_dates_and_homeroom_compatibility(monkeypatch) -> None:
    tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    other_teacher = SimpleNamespace(id=uuid.uuid4())
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus, class_teacher_id=teacher.id)
    assignment = _assignment(tenant, year=year, teacher=teacher, klass=klass, assignment_type="homeroom", is_active=True)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(ta, "log_action", audit)

    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [assignment, year, klass, grade_level, None]
    updated = await ta.update_teacher_assignment(
        assignment.id,
        ta.TeacherAssignmentUpdateRequest(start_date=date(2026, 9, 2), end_date=date(2027, 5, 30)),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert updated["start_date"] == date(2026, 9, 2)
    assert updated["end_date"] == date(2027, 5, 30)
    assert klass.class_teacher_id == teacher.id
    assert any(call.kwargs.get("action") == "teacher_assignment.updated" for call in audit.await_args_list)

    klass.class_teacher_id = teacher.id
    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [assignment, year, klass, grade_level]
    deactivated = await ta.update_teacher_assignment(
        assignment.id,
        ta.TeacherAssignmentUpdateRequest(is_active=False),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert deactivated["is_active"] is False
    assert klass.class_teacher_id is None
    assert any(call.kwargs.get("action") == "teacher_assignment.deactivated" for call in audit.await_args_list)

    klass.class_teacher_id = None
    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [assignment, year, klass, grade_level, None]
    reactivated = await ta.update_teacher_assignment(
        assignment.id,
        ta.TeacherAssignmentUpdateRequest(is_active=True),
        tenant=tenant,
        actor=actor,
        db=db,
    )
    assert reactivated["is_active"] is True
    assert klass.class_teacher_id == teacher.id

    klass.class_teacher_id = other_teacher.id
    db.execute.side_effect = [_Result(first=(teacher, user))]
    db.scalar.side_effect = [assignment, year, klass, grade_level]
    with pytest.raises(HTTPException) as exc:
        await ta.update_teacher_assignment(
            assignment.id,
            ta.TeacherAssignmentUpdateRequest(is_active=True),
            tenant=tenant,
            actor=actor,
            db=db,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_patch_rejects_structural_fields_and_tenant_scoped_list_and_summary(monkeypatch) -> None:
    tenant = _tenant()
    other_tenant = _tenant()
    actor = _actor(tenant)
    teacher, user = _teacher_context(tenant)
    year = _year(tenant)
    grade_level = _grade_level(tenant)
    campus = _campus(tenant)
    klass = _canonical_class(tenant, academic_year=year, grade_level=grade_level, campus=campus)
    subject = _subject(tenant)
    offering = _offering(tenant, campus=campus, year=year, grade_level=grade_level, subject=subject)
    assignment = _assignment(tenant, year=year, teacher=teacher, klass=klass, assignment_type="subject_teacher", subject_offering_id=offering.id, is_active=True)
    db = _db()

    monkeypatch.setattr(ta, "set_tenant_context", AsyncMock())

    with pytest.raises(ValidationError):
        ta.TeacherAssignmentUpdateRequest(teacher_id=uuid.uuid4())  # type: ignore[call-arg]

    db.execute.side_effect = [
        _Result(rows=[(assignment, teacher, user, klass, grade_level, year, offering, subject)]),
    ]
    rows = await ta.list_teacher_assignments(tenant=tenant, actor=actor, db=db)
    assert rows[0]["tenant_id"] == str(tenant.id)
    assert rows[0]["assignment_type"] == "subject_teacher"
    assert rows[0]["subject_offering_id"] == str(offering.id)

    db.scalar.side_effect = [1, 1, 0, 1, 0, 1, 1]
    summary = await ta.teacher_assignment_summary(tenant=tenant, actor=actor, db=db)
    assert summary["counts"]["total_assignments"] == 1
    assert summary["counts"]["active_assignments"] == 1
    assert summary["counts"]["inactive_assignments"] == 0

    db.execute.side_effect = [
        _Result(rows=[(assignment, teacher, user, klass, grade_level, year, offering, subject)]),
    ]
    payload = await ta.list_teacher_assignments(academic_year_id=year.id, teacher_id=teacher.id, class_id=klass.id, assignment_type="subject_teacher", is_active=True, tenant=tenant, actor=actor, db=db)
    assert len(payload) == 1

    db.execute.side_effect = [_Result(rows=[])]
    payload_other = await ta.list_teacher_assignments(tenant=other_tenant, actor=actor, db=db)
    assert payload_other == []


@pytest.mark.asyncio
async def test_migration_parity_and_single_head() -> None:
    migration = _load_migration_module()
    assert migration.revision == "7d1b8a5c4e10"
    assert migration.down_revision == "4f2e1d9b7c30"

    op = MagicMock()
    migration.op = op
    migration.upgrade()
    migration.downgrade()

    created_tables = {call.args[0] for call in op.create_table.call_args_list}
    assert created_tables == {"teacher_assignments"}

    index_names = {call.args[0] for call in op.create_index.call_args_list if call.args}
    assert "uq_teacher_assignments_active_homeroom_class" in index_names
    assert "uq_teacher_assignments_active_subject_teacher" in index_names
    assert "ix_teacher_assignments_tenant_id" in index_names

    drop_order = [call.args[0] for call in op.drop_index.call_args_list]
    assert drop_order[-1] == "uq_teacher_assignments_active_homeroom_class"
    assert op.drop_table.call_args_list[0].args[0] == "teacher_assignments"

    class_columns = {c.name for c in TeacherAssignment.__table__.columns}
    assert {"tenant_id", "academic_year_id", "teacher_id", "class_id", "subject_offering_id", "assignment_type", "start_date", "end_date", "is_active", "created_at", "updated_at"} <= class_columns

    constraint_names = {getattr(c, "name", None) for c in TeacherAssignment.__table__.constraints}
    assert any(name and name.endswith("ck_teacher_assignments_type") for name in constraint_names)
    assert any(name and name.endswith("ck_teacher_assignments_subject_scope") for name in constraint_names)
    assert any(name and name.endswith("ck_teacher_assignments_date_range") for name in constraint_names)

    index_names_model = {idx.name for idx in TeacherAssignment.__table__.indexes}
    assert {"uq_teacher_assignments_active_homeroom_class", "uq_teacher_assignments_active_subject_teacher", "ix_teacher_assignments_tenant_id", "ix_teacher_assignments_academic_year_id", "ix_teacher_assignments_teacher_id", "ix_teacher_assignments_class_id", "ix_teacher_assignments_subject_offering_id", "ix_teacher_assignments_assignment_type", "ix_teacher_assignments_is_active"} <= index_names_model

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "7d1b8a5c4e10"
