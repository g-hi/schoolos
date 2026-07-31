from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.gateway.authorization.student_enrollment_scope import (
    StudentClassResolution,
    list_class_student_ids,
    resolve_student_class,
    student_belongs_to_class,
)
from shared.db.models import AcademicYear, Class, GradeLevel, Student, StudentEnrollment


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if self._rows:
            row = self._rows[0]
            return row[0] if isinstance(row, (tuple, list)) else row
        return None


def _tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_year(tenant_id: uuid.UUID, *, is_active: bool = True) -> AcademicYear:
    return AcademicYear(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
        is_active=is_active,
    )


def _make_grade(tenant_id: uuid.UUID, *, is_active: bool = True) -> GradeLevel:
    return GradeLevel(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Grade 5",
        code="G5",
        sequence=5,
        is_active=is_active,
    )


def _make_canonical_class(
    tenant_id: uuid.UUID,
    year: AcademicYear,
    grade: GradeLevel,
    *,
    is_active: bool = True,
) -> Class:
    return Class(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        grade=grade.name,
        section="A",
        academic_year=year.name,
        class_teacher_id=None,
        campus_id=uuid.uuid4(),
        academic_year_id=year.id,
        grade_level_id=grade.id,
        code="5A",
        is_active=is_active,
    )


def _make_student(tenant_id: uuid.UUID, class_id: uuid.UUID | None = None) -> Student:
    return Student(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        class_id=class_id,
        name="Test Student",
        student_code="S1",
    )


def _make_enrollment(
    tenant_id: uuid.UUID,
    student: Student,
    klass: Class,
    year: AcademicYear,
    grade: GradeLevel,
    *,
    status: str = "active",
    enrolled_on: date = date(2026, 9, 1),
    exited_on: date | None = None,
) -> StudentEnrollment:
    return StudentEnrollment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_year_id=year.id,
        student_id=student.id,
        class_id=klass.id,
        grade_level_id=grade.id,
        status=status,
        enrolled_on=enrolled_on,
        exited_on=exited_on,
        exit_reason=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# resolve_student_class — canonical-first resolution
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_active_canonical_enrollment_resolves_class() -> None:
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    enrollment = _make_enrollment(tenant_id, student, klass, year, grade)

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(enrollment, klass, year, grade)])
    db.scalar.return_value = None  # not reached

    resolution = await resolve_student_class(db=db, tenant_id=tenant_id, student_id=student.id)

    assert resolution.source == "canonical"
    assert resolution.class_id == klass.id
    assert resolution.enrollment_id == enrollment.id
    assert resolution.denied_due_to_canonical_history is False


@pytest.mark.asyncio
async def test_terminal_canonical_history_blocks_legacy_fallback() -> None:
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    transferred = _make_enrollment(tenant_id, student, klass, year, grade, status="transferred", exited_on=date(2026, 10, 1))

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(transferred, klass, year, grade)])
    db.scalar.return_value = None  # not reached

    resolution = await resolve_student_class(db=db, tenant_id=tenant_id, student_id=student.id)

    assert resolution.source == "canonical"
    assert resolution.class_id is None
    assert resolution.denied_due_to_canonical_history is True
    assert "canonical_history_exists_but_no_active_enrollment" in resolution.reason


@pytest.mark.asyncio
async def test_withdrawn_history_blocks_legacy_fallback() -> None:
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    withdrawn = _make_enrollment(tenant_id, student, klass, year, grade, status="withdrawn", exited_on=date(2026, 11, 1))

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(withdrawn, klass, year, grade)])
    db.scalar.return_value = None

    resolution = await resolve_student_class(db=db, tenant_id=tenant_id, student_id=student.id)

    assert resolution.denied_due_to_canonical_history is True
    assert resolution.class_id is None


@pytest.mark.asyncio
async def test_no_canonical_history_allows_legacy_fallback() -> None:
    tenant_id = _tenant_id()
    legacy_class_id = uuid.uuid4()
    student = _make_student(tenant_id, legacy_class_id)
    legacy_class = Class(
        id=legacy_class_id, tenant_id=tenant_id, grade="Grade 5", section="A",
        academic_year="2026-2027", class_teacher_id=None,
        campus_id=None, academic_year_id=None, grade_level_id=None,
        code=None, is_active=True,
    )

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[])  # no canonical history
    db.scalar.side_effect = [student, legacy_class]

    resolution = await resolve_student_class(db=db, tenant_id=tenant_id, student_id=student.id)

    assert resolution.source == "legacy"
    assert resolution.class_id == legacy_class_id
    assert resolution.denied_due_to_canonical_history is False
    assert "legacy_student_class_id_fallback" in resolution.reason


@pytest.mark.asyncio
async def test_effective_date_resolution_before_enrollment_start() -> None:
    """Active enrollment enrolled_on AFTER effective_date should not match."""
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    enrollment = _make_enrollment(tenant_id, student, klass, year, grade, enrolled_on=date(2026, 10, 1))

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(enrollment, klass, year, grade)])
    # No scalar calls needed for this case (canonical history exists, denied path)
    db.scalar.return_value = None

    # Effective date is before enrollment start
    resolution = await resolve_student_class(
        db=db, tenant_id=tenant_id, student_id=student.id, effective_date=date(2026, 9, 15)
    )

    assert resolution.denied_due_to_canonical_history is True
    assert resolution.class_id is None


@pytest.mark.asyncio
async def test_effective_date_resolution_after_enrollment_start() -> None:
    """Active enrollment with enrolled_on <= effective_date must match."""
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    enrollment = _make_enrollment(tenant_id, student, klass, year, grade, enrolled_on=date(2026, 9, 1))

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(enrollment, klass, year, grade)])
    db.scalar.return_value = None

    resolution = await resolve_student_class(
        db=db, tenant_id=tenant_id, student_id=student.id, effective_date=date(2026, 10, 1)
    )

    assert resolution.source == "canonical"
    assert resolution.class_id == klass.id


@pytest.mark.asyncio
async def test_tenant_isolation_no_cross_tenant_match() -> None:
    """Resolution must scope queries to tenant_id."""
    tenant_id = _tenant_id()

    db = AsyncMock()
    captured_params = []

    async def execute_side_effect(statement):
        compiled = statement.compile()
        captured_params.append(compiled.params)
        return _Result(rows=[])

    db.execute.side_effect = execute_side_effect
    db.scalar.return_value = None

    student_id = uuid.uuid4()
    await resolve_student_class(db=db, tenant_id=tenant_id, student_id=student_id)

    flattened = {v for params in captured_params for v in params.values()}
    assert tenant_id in flattened


@pytest.mark.asyncio
async def test_student_belongs_to_class_matching() -> None:
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    enrollment = _make_enrollment(tenant_id, student, klass, year, grade)

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(enrollment, klass, year, grade)])
    db.scalar.return_value = None

    result = await student_belongs_to_class(
        db=db, tenant_id=tenant_id, student_id=student.id, class_id=klass.id
    )
    assert result.class_id == klass.id
    assert result.source == "canonical"


@pytest.mark.asyncio
async def test_student_belongs_to_class_mismatch() -> None:
    tenant_id = _tenant_id()
    year = _make_year(tenant_id)
    grade = _make_grade(tenant_id)
    klass = _make_canonical_class(tenant_id, year, grade)
    student = _make_student(tenant_id, klass.id)
    enrollment = _make_enrollment(tenant_id, student, klass, year, grade)
    wrong_class_id = uuid.uuid4()

    db = AsyncMock()
    db.execute.return_value = _Result(rows=[(enrollment, klass, year, grade)])
    db.scalar.return_value = None

    result = await student_belongs_to_class(
        db=db, tenant_id=tenant_id, student_id=student.id, class_id=wrong_class_id
    )
    assert result.class_id is None
    assert result.source == "none"
    assert "class_mismatch" in result.reason


# ─────────────────────────────────────────────────────────────────────────────
# list_class_student_ids
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_class_student_ids_canonical_counts() -> None:
    tenant_id = _tenant_id()
    class_id = uuid.uuid4()
    student_id_a = uuid.uuid4()
    student_id_b = uuid.uuid4()

    db = AsyncMock()
    db.execute.side_effect = [
        # canonical active enrollments for class
        _Result(rows=[(student_id_a,), (student_id_b,)]),
        # any canonical history (all tenants)
        _Result(rows=[(student_id_a,), (student_id_b,)]),
        # legacy fallback (all have canonical history, so empty)
        _Result(rows=[]),
    ]

    result = await list_class_student_ids(db=db, tenant_id=tenant_id, class_id=class_id)

    assert result["canonical_student_ids"] == {student_id_a, student_id_b}
    assert result["legacy_student_ids"] == set()
    assert result["all_student_ids"] == {student_id_a, student_id_b}


@pytest.mark.asyncio
async def test_list_class_student_ids_deduplicates_legacy_with_canonical() -> None:
    tenant_id = _tenant_id()
    class_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    legacy_only_id = uuid.uuid4()

    db = AsyncMock()
    db.execute.side_effect = [
        # canonical active enrollments
        _Result(rows=[(canonical_id,)]),
        # any canonical history
        _Result(rows=[(canonical_id,)]),
        # legacy students without canonical history
        _Result(rows=[(legacy_only_id,)]),
    ]

    result = await list_class_student_ids(db=db, tenant_id=tenant_id, class_id=class_id)

    assert canonical_id in result["canonical_student_ids"]
    assert legacy_only_id in result["legacy_student_ids"]
    # No duplication: canonical_id is NOT in legacy_student_ids
    assert canonical_id not in result["legacy_student_ids"]
    assert len(result["all_student_ids"]) == 2


@pytest.mark.asyncio
async def test_list_class_student_ids_transferred_students_excluded() -> None:
    """Transferred/withdrawn students should not appear in canonical_student_ids."""
    tenant_id = _tenant_id()
    class_id = uuid.uuid4()

    db = AsyncMock()
    db.execute.side_effect = [
        # No active canonical enrollments (status='transferred' excluded by query filter)
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
    ]

    result = await list_class_student_ids(db=db, tenant_id=tenant_id, class_id=class_id)

    assert result["canonical_student_ids"] == set()
    assert result["all_student_ids"] == set()


# ─────────────────────────────────────────────────────────────────────────────
# appointment enrollment integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_appointment_uses_scheduled_date_enrollment(monkeypatch) -> None:
    from services.gateway.routers import appointments as appt_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    student_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    class_id = uuid.uuid4()
    scheduled_date = date(2026, 10, 5)

    teacher = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id)

    # Teacher and User result
    class FakeExecResult:
        def scalar_one_or_none(self):
            return teacher

    resolution = StudentClassResolution(
        class_id=class_id,
        enrollment_id=uuid.uuid4(),
        source="canonical",
        status="active",
        denied_due_to_canonical_history=False,
        reason="matched_active_canonical_enrollment",
    )

    klass = SimpleNamespace(
        id=class_id, tenant_id=tenant.id, grade="Grade 5", section="A",
        academic_year="2026-2027", class_teacher_id=None,
        campus_id=uuid.uuid4(), academic_year_id=uuid.uuid4(),
        grade_level_id=uuid.uuid4(), code="5A", is_active=True,
    )
    student = SimpleNamespace(id=student_id, tenant_id=tenant.id, class_id=class_id)

    captured_effective_dates = []

    async def mock_resolve(db, tenant_id, student_id, effective_date=None, academic_year_id=None):
        captured_effective_dates.append(effective_date)
        return resolution

    monkeypatch.setattr(appt_router, "resolve_student_class", mock_resolve)

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[(student,)]),  # student select
        _Result(rows=[(klass,)]),    # class select
        FakeExecResult(),            # teacher select
    ]
    db.scalar.return_value = None

    # Mock teacher scope
    from services.gateway.authorization import teacher_scope as ts

    async def mock_homeroom_scope(**kwargs):
        return SimpleNamespace(authorized=False, source="none", canonical_history_exists=False, reason="test")

    monkeypatch.setattr(appt_router, "teacher_has_homeroom_scope", mock_homeroom_scope)

    # We don't need to finish the full call — test that effective_date flows correctly
    try:
        await appt_router._validate_teacher_subject_option(
            db=db,
            tenant=tenant,
            student_id=student_id,
            teacher_id=teacher_id,
            subject_id=None,
            timetable_entry_id=None,
            effective_date=scheduled_date,
        )
    except Exception:
        pass  # We only care that resolve_student_class was called with the right date

    assert scheduled_date in captured_effective_dates


# ─────────────────────────────────────────────────────────────────────────────
# pickup enrollment integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pickup_blocked_when_canonical_terminal_history_exists(monkeypatch) -> None:
    from services.gateway.routers import pickup as pickup_router
    from fastapi import HTTPException

    tenant = SimpleNamespace(id=uuid.uuid4(), settings={})
    parent = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id)
    student_id = uuid.uuid4()
    student = SimpleNamespace(id=student_id, tenant_id=tenant.id, class_id=uuid.uuid4())

    # resolve_student_class returns denied due to canonical history
    async def mock_denied_resolve(db, tenant_id, student_id, effective_date=None, **kwargs):
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="canonical",
            status=None,
            denied_due_to_canonical_history=True,
            reason="canonical_history_exists_but_no_active_enrollment",
        )

    monkeypatch.setattr(pickup_router, "resolve_student_class", mock_denied_resolve)

    db = AsyncMock()

    async def mock_student_access(**kwargs):
        return SimpleNamespace(can_pickup=True)

    monkeypatch.setattr(pickup_router, "_parent_student_pickup_access", mock_student_access)
    db.execute.return_value = _Result(rows=[(student,)])
    db.scalar.return_value = student

    with pytest.raises(Exception) as exc_info:
        await pickup_router._parent_create_pickup(
            body=SimpleNamespace(
                student_id=student_id,
                command_text="pickup",
                channel=None,
                latitude=None,
                longitude=None,
            ),
            tenant=tenant,
            parent=parent,
            db=db,
        )

    assert "403" in str(exc_info.value.status_code) or exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_pickup_uses_action_date_resolution(monkeypatch) -> None:
    from services.gateway.routers import pickup as pickup_router

    tenant = SimpleNamespace(id=uuid.uuid4(), settings={})
    parent = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id)
    student_id = uuid.uuid4()
    class_id = uuid.uuid4()
    student = SimpleNamespace(id=student_id, tenant_id=tenant.id, class_id=class_id)
    klass = SimpleNamespace(id=class_id, tenant_id=tenant.id, class_teacher_id=None)

    captured_dates = []

    async def mock_resolve(db, tenant_id, student_id, effective_date=None, **kwargs):
        captured_dates.append(effective_date)
        return StudentClassResolution(
            class_id=class_id,
            enrollment_id=uuid.uuid4(),
            source="canonical",
            status="active",
            denied_due_to_canonical_history=False,
            reason="matched_active_canonical_enrollment",
        )

    monkeypatch.setattr(pickup_router, "resolve_student_class", mock_resolve)

    db = AsyncMock()

    async def mock_student_access(**kwargs):
        return SimpleNamespace(can_pickup=True)

    monkeypatch.setattr(pickup_router, "_parent_student_pickup_access", mock_student_access)
    db.scalar.return_value = student
    db.execute.side_effect = [
        _Result(rows=[(student,)]),
        _Result(rows=[(klass,)]),
    ]
    db.add = MagicMock()
    db.commit = AsyncMock()

    monkeypatch.setattr(pickup_router, "log_action", AsyncMock())
    monkeypatch.setattr(pickup_router, "_write_pickup_timeline", AsyncMock())

    await pickup_router._parent_create_pickup(
        body=SimpleNamespace(
            student_id=student_id,
            command_text="pickup",
            channel=None,
            latitude=None,
            longitude=None,
        ),
        tenant=tenant,
        parent=parent,
        db=db,
    )

    assert len(captured_dates) == 1
    today = datetime.now(timezone.utc).date()
    assert captured_dates[0] == today


# ─────────────────────────────────────────────────────────────────────────────
# weekly report enrollment integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_report_canonical_terminal_blocks_access(monkeypatch) -> None:
    from services.gateway.weekly_reports import authorization as wr_auth
    from fastapi import HTTPException

    tenant_id = _tenant_id()
    actor = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="teacher")
    student_id = uuid.uuid4()

    async def mock_denied_resolve(db, tenant_id, student_id, effective_date=None, **kwargs):
        return StudentClassResolution(
            class_id=None,
            enrollment_id=None,
            source="canonical",
            status=None,
            denied_due_to_canonical_history=True,
            reason="canonical_history_exists_but_no_active_enrollment",
        )

    monkeypatch.setattr(wr_auth, "resolve_student_class", mock_denied_resolve)

    db = AsyncMock()
    student = SimpleNamespace(id=student_id, tenant_id=tenant_id)
    db.execute.return_value = _Result(rows=[(student,)])
    db.scalar.return_value = None

    with pytest.raises(Exception) as exc_info:
        await wr_auth.authorize_staff_for_student_action(
            db=db,
            tenant_id=tenant_id,
            actor=actor,
            student_id=student_id,
            action="write_report",
        )

    assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Teacher My Classes student count integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_teacher_class_count_uses_canonical_first_resolution(monkeypatch) -> None:
    from services.gateway.routers import teacher_classes

    tenant = SimpleNamespace(id=uuid.uuid4(), slug="school")
    teacher_user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="teacher", is_active=True, name="T")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)
    class_id = uuid.uuid4()
    academic_year_id = uuid.uuid4()
    campus_id = uuid.uuid4()

    klass = SimpleNamespace(
        id=class_id, tenant_id=tenant.id, code="5A", grade="Grade 5", section="A",
        academic_year="2026-2027", academic_year_id=academic_year_id, campus_id=campus_id,
        class_teacher_id=None, grade_level_id=uuid.uuid4(), is_active=True,
    )
    ay = SimpleNamespace(id=academic_year_id, name="2026-2027", is_active=True)
    campus = SimpleNamespace(id=campus_id, name="Main")
    assignment = SimpleNamespace(assignment_type="homeroom", start_date=date(2026, 9, 1), end_date=None)

    canonical_counts_called = []

    async def mock_list_class_student_ids(db, tenant_id, class_id, effective_date=None):
        canonical_counts_called.append(class_id)
        return {
            "canonical_student_ids": {uuid.uuid4(), uuid.uuid4()},
            "legacy_student_ids": {uuid.uuid4()},
            "all_student_ids": {uuid.uuid4(), uuid.uuid4(), uuid.uuid4()},
        }

    monkeypatch.setattr(teacher_classes, "list_class_student_ids", mock_list_class_student_ids)
    monkeypatch.setattr(teacher_classes, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.scalar.return_value = teacher_profile

    class FakeRows:
        def all(self):
            return []

    db.execute.side_effect = [
        FakeRows(),  # canonical_history_rows
        type("R", (), {"all": lambda self: [(assignment, klass, ay, campus, None)]})(),  # canonical rows
        FakeRows(),  # legacy_homeroom_rows
        FakeRows(),  # legacy_timetable_rows
        FakeRows(),  # weekly_period_counts
    ]

    response = await teacher_classes.get_teacher_my_classes(
        effective_date=None,
        tenant=tenant,
        teacher_user=teacher_user,
        db=db,
    )

    assert len(canonical_counts_called) == 1
    assert canonical_counts_called[0] == class_id
    assert response["classes"][0]["student_count"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion dual-write
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_canonical_import_creates_enrollment(monkeypatch) -> None:
    from services.gateway.routers import ingest as ingest_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    year = _make_year(tenant.id)
    grade = _make_grade(tenant.id)
    klass = Class(
        id=uuid.uuid4(), tenant_id=tenant.id, grade="Grade 5", section="A",
        academic_year="2026-2027", class_teacher_id=None, campus_id=uuid.uuid4(),
        academic_year_id=year.id, grade_level_id=grade.id, code="5A", is_active=True,
    )

    monkeypatch.setattr(ingest_router, "set_tenant_context", AsyncMock())

    added_objects = []
    db = AsyncMock()
    db.add = lambda obj: added_objects.append(obj)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    db.scalar.side_effect = [klass, None, year]

    import io as _io
    csv_content = b"name,student_code,grade,section,academic_year\nAhmed Ali,S01,Grade 5,A,2026-2027\n"

    file = AsyncMock()
    file.read = AsyncMock(return_value=csv_content)

    result = await ingest_router.ingest_students(file=file, tenant=tenant, db=db)

    assert result["inserted"] == 1
    assert result["errors"] == []
    enrollment_objects = [o for o in added_objects if isinstance(o, StudentEnrollment)]
    assert len(enrollment_objects) == 1
    assert enrollment_objects[0].status == "active"
    assert enrollment_objects[0].enrolled_on == year.start_date


@pytest.mark.asyncio
async def test_legacy_class_import_does_not_create_enrollment(monkeypatch) -> None:
    from services.gateway.routers import ingest as ingest_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    # Legacy class — no canonical scope fields
    klass = Class(
        id=uuid.uuid4(), tenant_id=tenant.id, grade="Grade 5", section="B",
        academic_year="2026-2027", class_teacher_id=None,
        campus_id=None, academic_year_id=None, grade_level_id=None,
        code=None, is_active=True,
    )

    monkeypatch.setattr(ingest_router, "set_tenant_context", AsyncMock())

    added_objects = []
    db = AsyncMock()
    db.add = lambda obj: added_objects.append(obj)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar.side_effect = [klass, None]  # klass for class lookup, None for new student check

    csv_content = b"name,student_code,grade,section,academic_year\nSara Khan,S02,Grade 5,B,2026-2027\n"
    file = AsyncMock()
    file.read = AsyncMock(return_value=csv_content)

    result = await ingest_router.ingest_students(file=file, tenant=tenant, db=db)

    assert result["inserted"] == 1
    enrollment_objects = [o for o in added_objects if isinstance(o, StudentEnrollment)]
    assert len(enrollment_objects) == 0


@pytest.mark.asyncio
async def test_repeated_canonical_import_is_idempotent(monkeypatch) -> None:
    from services.gateway.routers import ingest as ingest_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    year = _make_year(tenant.id)
    grade = _make_grade(tenant.id)
    klass = Class(
        id=uuid.uuid4(), tenant_id=tenant.id, grade="Grade 5", section="A",
        academic_year="2026-2027", class_teacher_id=None, campus_id=uuid.uuid4(),
        academic_year_id=year.id, grade_level_id=grade.id, code="5A", is_active=True,
    )
    existing_student = Student(id=uuid.uuid4(), tenant_id=tenant.id, class_id=klass.id, name="Ahmed", student_code="S01")
    existing_enrollment_id = uuid.uuid4()

    monkeypatch.setattr(ingest_router, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    # klass, existing_student found, same_class_active returns enrollment id
    db.scalar.side_effect = [klass, existing_student, year, existing_enrollment_id]

    csv_content = b"name,student_code,grade,section,academic_year\nAhmed Ali,S01,Grade 5,A,2026-2027\n"
    file = AsyncMock()
    file.read = AsyncMock(return_value=csv_content)

    result = await ingest_router.ingest_students(file=file, tenant=tenant, db=db)

    assert result["inserted"] == 0
    assert result["skipped"] == 1
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_conflicting_canonical_import_produces_row_error(monkeypatch) -> None:
    from services.gateway.routers import ingest as ingest_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    year = _make_year(tenant.id)
    grade = _make_grade(tenant.id)
    klass = Class(
        id=uuid.uuid4(), tenant_id=tenant.id, grade="Grade 5", section="A",
        academic_year="2026-2027", class_teacher_id=None, campus_id=uuid.uuid4(),
        academic_year_id=year.id, grade_level_id=grade.id, code="5A", is_active=True,
    )
    existing_student = Student(id=uuid.uuid4(), tenant_id=tenant.id, class_id=uuid.uuid4(), name="Ahmed", student_code="S01")

    monkeypatch.setattr(ingest_router, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    # klass, existing_student, year loaded, same_class_active=None, conflict=uuid (different class enrollment)
    db.scalar.side_effect = [klass, existing_student, year, None, uuid.uuid4()]

    csv_content = b"name,student_code,grade,section,academic_year\nAhmed Ali,S01,Grade 5,A,2026-2027\n"
    file = AsyncMock()
    file.read = AsyncMock(return_value=csv_content)

    result = await ingest_router.ingest_students(file=file, tenant=tenant, db=db)

    assert result["errors"]
    assert "transfer" in result["errors"][0]["error"].lower()
    assert result["inserted"] == 0


@pytest.mark.asyncio
async def test_ingest_does_not_transfer_automatically(monkeypatch) -> None:
    """Repeated canonical import for a student already in a DIFFERENT class in the same year
    must NOT modify the student's enrollment — just produce a row error."""
    from services.gateway.routers import ingest as ingest_router

    tenant = SimpleNamespace(id=uuid.uuid4())
    year = _make_year(tenant.id)
    grade = _make_grade(tenant.id)
    new_class = Class(
        id=uuid.uuid4(), tenant_id=tenant.id, grade="Grade 5", section="B",
        academic_year="2026-2027", class_teacher_id=None, campus_id=uuid.uuid4(),
        academic_year_id=year.id, grade_level_id=grade.id, code="5B", is_active=True,
    )
    existing_student = Student(id=uuid.uuid4(), tenant_id=tenant.id, class_id=uuid.uuid4(), name="Ahmed", student_code="S01")
    original_class_id = existing_student.class_id  # must not change

    monkeypatch.setattr(ingest_router, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar.side_effect = [new_class, existing_student, year, None, uuid.uuid4()]

    csv_content = b"name,student_code,grade,section,academic_year\nAhmed Ali,S01,Grade 5,B,2026-2027\n"
    file = AsyncMock()
    file.read = AsyncMock(return_value=csv_content)

    await ingest_router.ingest_students(file=file, tenant=tenant, db=db)

    # class_id must NOT have been changed
    assert existing_student.class_id == original_class_id


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics / summary
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_summary_returns_stale_pointer_issue(monkeypatch) -> None:
    from services.gateway.routers import student_enrollments as se

    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="principal")

    student_id = uuid.uuid4()
    legacy_class_id = uuid.uuid4()

    # Terminal enrollment exists for this student
    terminal_enrollment_id = uuid.uuid4()

    class _FakeExecResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.execute.side_effect = [
        # all_students_rows: (student_id, display_name, legacy_class_id)
        _FakeExecResult([(student_id, "Ahmed Ali", legacy_class_id)]),
        # active_enrollment_rows: none active
        _FakeExecResult([]),
        # any canonical history: terminal row exists
        _FakeExecResult([(student_id,)]),
        # multi_active_rows: none
        _FakeExecResult([]),
    ]

    result = await se.student_enrollment_reconciliation(tenant=tenant, actor=actor, db=db)

    assert result["total_issues"] == 1
    issue = result["issues"][0]
    assert issue["issue_code"] == "terminal_canonical_history_stale_class_id"
    assert issue["student_id"] == str(student_id)
    assert issue["legacy_class_id"] == str(legacy_class_id)
    assert "canonical_active_class_id" in issue
    assert issue["canonical_active_class_id"] is None


@pytest.mark.asyncio
async def test_reconciliation_summary_identifies_class_id_conflict(monkeypatch) -> None:
    from services.gateway.routers import student_enrollments as se

    tenant = SimpleNamespace(id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="principal")

    student_id = uuid.uuid4()
    legacy_class_id = uuid.uuid4()
    active_enrollment_class_id = uuid.uuid4()  # different from legacy_class_id
    enrollment_id = uuid.uuid4()

    class _FakeExecResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    monkeypatch.setattr(se, "set_tenant_context", AsyncMock())

    db = AsyncMock()
    db.execute.side_effect = [
        _FakeExecResult([(student_id, "Ahmed Ali", legacy_class_id)]),
        _FakeExecResult([(student_id, active_enrollment_class_id, enrollment_id)]),
        _FakeExecResult([(student_id,)]),
        _FakeExecResult([]),  # no multi-active
    ]

    result = await se.student_enrollment_reconciliation(tenant=tenant, actor=actor, db=db)

    assert result["total_issues"] == 1
    assert result["issues"][0]["issue_code"] == "class_id_conflicts_with_active_enrollment"
    assert result["issues"][0]["canonical_active_class_id"] == str(active_enrollment_class_id)


def test_no_schema_migration_added() -> None:
    """Alembic must remain at head 8c3f2b1e9d77 — no new migration file for this phase."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "8c3f2b1e9d77"
