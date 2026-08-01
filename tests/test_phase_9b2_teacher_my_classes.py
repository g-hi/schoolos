from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway.routers.dashboard import teacher_assignment_coverage
from services.gateway.routers.teacher_classes import get_teacher_my_classes
from shared.auth.jwt import create_access_token
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _Rows(self._rows)


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", settings={})


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        name=f"{role.title()} User",
        email=f"{role}@school.test",
    )


def _mock_auth_db(user: SimpleNamespace) -> AsyncMock:
    session = AsyncMock()
    result = _Result(scalar=user)
    session.execute = AsyncMock(return_value=result)
    return session


def _auth_headers(user: SimpleNamespace, tenant_slug: str, *, jwt_role: str | None = None) -> dict[str, str]:
    token = create_access_token(user_id=str(user.id), role=jwt_role or user.role, tenant_slug=tenant_slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": tenant_slug}


def _teacher_class(
    *,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    code: str,
    grade: str = "Grade 5",
    section: str = "A",
    academic_year: str = "2026-2027",
    academic_year_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
    class_teacher_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=class_id,
        tenant_id=tenant_id,
        code=code,
        grade=grade,
        section=section,
        academic_year=academic_year,
        academic_year_id=academic_year_id,
        campus_id=campus_id,
        class_teacher_id=class_teacher_id,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_missing_teacher_profile_returns_controlled_response() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    db = AsyncMock()
    db.scalar.return_value = None
    db.execute.return_value = _Result(rows=[])

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        with pytest.raises(Exception) as exc_info:
            await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert "Teacher profile not found." in str(exc_info.value)


@pytest.mark.asyncio
async def test_inactive_user_denied() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher", is_active=False)
    db = AsyncMock()

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        with pytest.raises(Exception) as exc_info:
            await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert "You do not have access to this resource." in str(exc_info.value)


def test_teacher_only_access_parent_denied() -> None:
    from services.gateway.routers.teacher_classes import router as teacher_classes_router

    tenant = _tenant()
    parent = _user(tenant_id=tenant.id, role="parent")
    db = _mock_auth_db(parent)

    app = FastAPI()
    app.include_router(teacher_classes_router)

    async def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/teacher/my-classes", headers=_auth_headers(parent, tenant.slug, jwt_role="teacher"))

    assert response.status_code == 403


def test_teacher_only_access_leadership_denied() -> None:
    from services.gateway.routers.teacher_classes import router as teacher_classes_router

    tenant = _tenant()
    principal = _user(tenant_id=tenant.id, role="principal")
    db = _mock_auth_db(principal)

    app = FastAPI()
    app.include_router(teacher_classes_router)

    async def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/teacher/my-classes", headers=_auth_headers(principal, tenant.slug, jwt_role="teacher"))

    assert response.status_code == 403


def test_effective_date_validation() -> None:
    from services.gateway.routers.teacher_classes import router as teacher_classes_router

    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_auth_db(teacher)

    app = FastAPI()
    app.include_router(teacher_classes_router)

    async def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/teacher/my-classes?effective_date=bad-date",
            headers=_auth_headers(teacher, tenant.slug),
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_active_canonical_homeroom_and_subject_returned_deduped() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)
    class_id = uuid.uuid4()
    academic_year_id = uuid.uuid4()
    campus_id = uuid.uuid4()
    klass = _teacher_class(
        tenant_id=tenant.id,
        class_id=class_id,
        code="5A",
        academic_year_id=academic_year_id,
        campus_id=campus_id,
    )
    ay = SimpleNamespace(id=academic_year_id, name="2026-2027", is_active=True)
    campus = SimpleNamespace(id=campus_id, name="Main")
    subject = SimpleNamespace(id=uuid.uuid4(), code="MATH", name="Mathematics")

    homeroom = SimpleNamespace(assignment_type="homeroom", start_date=date(2026, 1, 1), end_date=None)
    subject_assignment = SimpleNamespace(assignment_type="subject_teacher", start_date=date(2026, 1, 1), end_date=None)

    s1, s2 = uuid.uuid4(), uuid.uuid4()
    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[(homeroom, klass, ay, campus, None), (subject_assignment, klass, ay, campus, subject)]),
        _Result(rows=[]),
        _Result(rows=[]),
        # list_class_student_ids for class_id
        _Result(rows=[(s1,), (s2,)]),   # canonical active enrollments
        _Result(rows=[(s1,), (s2,)]),   # any canonical history
        _Result(rows=[]),               # legacy fallback (all have canonical history)
        _Result(rows=[(class_id, 6)]),  # weekly_period_counts
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert response["summary"]["total_classes"] == 1
    assert response["summary"]["canonical_classes"] == 1
    assert response["summary"]["homeroom_classes"] == 1
    assert response["summary"]["subject_classes"] == 1
    assert response["classes"][0]["student_count"] == 2
    assert response["classes"][0]["schedule"]["weekly_periods"] == 6
    assert len(response["classes"][0]["assignments"]) == 2


@pytest.mark.asyncio
async def test_expired_or_inactive_canonical_excluded() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)

    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[(uuid.uuid4(),)]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert response["summary"]["total_classes"] == 0


@pytest.mark.asyncio
async def test_canonical_history_blocks_legacy_fallbacks() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)
    class_id = uuid.uuid4()
    klass = _teacher_class(tenant_id=tenant.id, class_id=class_id, code="6B", class_teacher_id=teacher_profile.id)

    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[(class_id,)]),
        _Result(rows=[]),
        _Result(rows=[(klass, None, None)]),
        _Result(rows=[(klass, None, None, SimpleNamespace(id=uuid.uuid4(), code="SCI", name="Science"))]),
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert response["summary"]["total_classes"] == 0


@pytest.mark.asyncio
async def test_no_canonical_history_allows_legacy_class_teacher_and_timetable() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)

    class_home = _teacher_class(tenant_id=tenant.id, class_id=uuid.uuid4(), code="4A", class_teacher_id=teacher_profile.id)
    class_subject = _teacher_class(tenant_id=tenant.id, class_id=uuid.uuid4(), code="4B")
    subject = SimpleNamespace(id=uuid.uuid4(), code="ENG", name="English")

    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[(class_home, None, None)]),
        _Result(rows=[(class_subject, None, None, subject)]),
        # list_class_student_ids for class_home
        _Result(rows=[]),               # canonical active (none)
        _Result(rows=[]),               # any canonical history (none)
        _Result(rows=[(s1,), (s2,)]),   # legacy fallback
        # list_class_student_ids for class_subject
        _Result(rows=[]),               # canonical active (none)
        _Result(rows=[]),               # any canonical history (none)
        _Result(rows=[(s3,)]),          # legacy fallback
        _Result(rows=[(class_home.id, 0), (class_subject.id, 5)]),  # weekly_period_counts
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert response["summary"]["total_classes"] == 2
    assert response["summary"]["legacy_classes"] == 2
    assert response["summary"]["homeroom_classes"] == 1
    assert response["summary"]["subject_classes"] == 1


@pytest.mark.asyncio
async def test_teacher_subject_alone_does_not_include_class() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)

    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert response["classes"] == []


@pytest.mark.asyncio
async def test_assignment_details_remain_distinct_for_multiple_subjects() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)
    class_id = uuid.uuid4()
    klass = _teacher_class(tenant_id=tenant.id, class_id=class_id, code="7A")
    ay = SimpleNamespace(name="2026-2027")

    subject_a = SimpleNamespace(id=uuid.uuid4(), code="BIO", name="Biology")
    subject_b = SimpleNamespace(id=uuid.uuid4(), code="CHEM", name="Chemistry")
    assignment_a = SimpleNamespace(assignment_type="subject_teacher", start_date=date(2026, 1, 1), end_date=None)
    assignment_b = SimpleNamespace(assignment_type="subject_teacher", start_date=date(2026, 1, 1), end_date=None)

    s1 = uuid.uuid4()
    db = AsyncMock()
    db.scalar.return_value = teacher_profile
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[(assignment_a, klass, ay, None, subject_a), (assignment_b, klass, ay, None, subject_b)]),
        _Result(rows=[]),
        _Result(rows=[]),
        # list_class_student_ids for class_id
        _Result(rows=[(s1,)]),   # canonical active enrollments
        _Result(rows=[(s1,)]),   # any canonical history
        _Result(rows=[]),        # legacy fallback
        _Result(rows=[(class_id, 4)]),  # weekly_period_counts
    ]

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        response = await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    assert len(response["classes"]) == 1
    assert len(response["classes"][0]["assignments"]) == 2


@pytest.mark.asyncio
async def test_teacher_my_classes_tenant_scoped_query_filters() -> None:
    tenant = _tenant()
    teacher_user = _user(tenant_id=tenant.id, role="teacher")
    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=teacher_user.id)

    db = AsyncMock()
    db.scalar.return_value = teacher_profile

    calls = []

    async def execute_side_effect(statement):
        compiled = statement.compile()
        calls.append(compiled.params)
        return _Result(rows=[])

    db.execute.side_effect = execute_side_effect

    with patch("services.gateway.routers.teacher_classes.set_tenant_context", new=AsyncMock()):
        await get_teacher_my_classes(tenant=tenant, teacher_user=teacher_user, db=db)

    flattened = {value for params in calls for value in params.values()}
    assert tenant.id in flattened


@pytest.mark.asyncio
async def test_leadership_assignment_coverage_zero_data_state() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(scalar=0),
        _Result(rows=[]),
    ]

    with patch("services.gateway.routers.dashboard.set_tenant_context", new=AsyncMock()):
        response = await teacher_assignment_coverage(tenant=tenant, actor=actor, db=db)

    assert response["summary"]["total_active_teachers"] == 0
    assert response["summary"]["canonical_assignment_coverage_percentage"] == 0.0
    assert response["teachers"] == []


@pytest.mark.asyncio
async def test_leadership_assignment_coverage_classification_and_workload_separation() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")

    t1 = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), tenant_id=tenant.id)
    t2 = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), tenant_id=tenant.id)
    t3 = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), tenant_id=tenant.id)

    u1 = SimpleNamespace(name="Teacher 1")
    u2 = SimpleNamespace(name="Teacher 2")
    u3 = SimpleNamespace(name="Teacher 3")

    class1 = uuid.uuid4()
    class2 = uuid.uuid4()

    canonical_assignment = SimpleNamespace(
        teacher_id=t1.id,
        class_id=class1,
        assignment_type="homeroom",
    )
    subject_assignment = SimpleNamespace(
        teacher_id=t1.id,
        class_id=class1,
        assignment_type="subject_teacher",
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[(t1, u1), (t2, u2), (t3, u3)]),
        _Result(rows=[(t1.id, class1)]),
        _Result(rows=[canonical_assignment, subject_assignment]),
        _Result(rows=[]),
        _Result(rows=[(t2.id, class2)]),
        _Result(scalar=2),
        _Result(rows=[(t1.id, 10), (t2.id, 4)]),
    ]

    with patch("services.gateway.routers.dashboard.set_tenant_context", new=AsyncMock()):
        response = await teacher_assignment_coverage(tenant=tenant, actor=actor, db=db)

    summary = response["summary"]
    assert summary["teachers_with_active_canonical_assignments"] == 1
    assert summary["teachers_with_legacy_only_assignment_evidence"] == 1
    assert summary["teachers_with_no_assignment_evidence"] == 1
    assert summary["active_subject_teacher_assignments"] == 1
    assert summary["canonical_assignment_coverage_percentage"] == 50.0

    teacher_rows = {row["display_name"]: row for row in response["teachers"]}
    assert teacher_rows["Teacher 1"]["assignment_status"] == "canonical"
    assert teacher_rows["Teacher 1"]["canonical_assignment_count"] == 2
    assert teacher_rows["Teacher 1"]["scheduled_weekly_periods"] == 10
    assert teacher_rows["Teacher 2"]["assignment_status"] == "legacy_only"
    assert teacher_rows["Teacher 2"]["canonical_assignment_count"] == 0
    assert teacher_rows["Teacher 2"]["scheduled_weekly_periods"] == 4
    assert teacher_rows["Teacher 3"]["assignment_status"] == "unassigned"


def test_coverage_endpoint_role_restrictions() -> None:
    from services.gateway.routers.dashboard import router as dashboard_router

    tenant = _tenant()
    teacher = _user(tenant_id=tenant.id, role="teacher")
    db = _mock_auth_db(teacher)

    app = FastAPI()
    app.include_router(dashboard_router)

    async def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[resolve_tenant] = lambda: tenant

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/dashboard/teacher-assignment-coverage",
            headers=_auth_headers(teacher, tenant.slug, jwt_role="principal"),
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_assignment_coverage_tenant_isolation_filters_present() -> None:
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id, role="principal")
    db = AsyncMock()

    captured = []

    async def execute_side_effect(statement):
        compiled = statement.compile()
        captured.append(compiled.params)
        if len(captured) == 6:
            return _Result(scalar=0)
        return _Result(rows=[])

    db.execute.side_effect = execute_side_effect

    with patch("services.gateway.routers.dashboard.set_tenant_context", new=AsyncMock()):
        await teacher_assignment_coverage(tenant=tenant, actor=actor, db=db)

    assert any(tenant.id in params.values() for params in captured)
