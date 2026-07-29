from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway.routers.pickup import router as pickup_router
from shared.auth.dependencies import (
    resolve_authenticated_leadership,
    resolve_authenticated_parent,
    resolve_authenticated_teacher,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import PickupRequest


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class PickupDbStub:
    def __init__(self):
        self.tenants: dict[uuid.UUID, SimpleNamespace] = {}
        self.students: dict[uuid.UUID, SimpleNamespace] = {}
        self.classes: dict[uuid.UUID, SimpleNamespace] = {}
        self.student_parents: list[SimpleNamespace] = []
        self.pickups: dict[uuid.UUID, PickupRequest] = {}
        self.teachers: list[SimpleNamespace] = []
        self.users: dict[uuid.UUID, SimpleNamespace] = {}

    def begin(self):
        return _Tx()

    def add(self, obj):
        if isinstance(obj, PickupRequest):
            self.pickups[obj.id] = obj

    async def commit(self):
        return None

    async def get(self, model, identifier):
        return self.users.get(identifier)

    async def execute(self, statement):
        compiled = statement.compile()
        text = str(compiled)
        params = compiled.params

        if "FROM teachers" in text:
            tenant_id = params.get("tenant_id_1")
            user_id = params.get("user_id_1")
            teacher = next((t for t in self.teachers if t.tenant_id == tenant_id and t.user_id == user_id), None)
            return _Result(scalar=teacher)

        if "FROM student_parents JOIN students" in text:
            parent_id = params.get("parent_id_1")
            student_id = params.get("student_id_1")
            tenant_id = params.get("tenant_id_1")
            student = self.students.get(student_id)
            if student is None or student.tenant_id != tenant_id:
                return _Result(scalar=None)
            sp = next((x for x in self.student_parents if x.parent_id == parent_id and x.student_id == student_id), None)
            return _Result(scalar=sp)

        if "FROM students" in text and "JOIN" not in text:
            student_id = params.get("id_1")
            tenant_id = params.get("tenant_id_1")
            student = self.students.get(student_id)
            if student and student.tenant_id == tenant_id:
                return _Result(scalar=student)
            return _Result(scalar=None)

        if "FROM classes" in text and "ORDER BY" not in text:
            class_id = params.get("id_1")
            tenant_id = params.get("tenant_id_1")
            klass = self.classes.get(class_id)
            if klass and klass.tenant_id == tenant_id:
                return _Result(scalar=klass)
            return _Result(scalar=None)

        if "FROM pickup_requests" in text and "with_for_update" in text.lower():
            tenant_id = params.get("tenant_id_1")
            pickup_id = params.get("id_1")
            pickup = self.pickups.get(pickup_id)
            if pickup and pickup.tenant_id == tenant_id:
                return _Result(scalar=pickup)
            return _Result(scalar=None)

        if "FROM pickup_requests" in text and "ORDER BY" in text:
            tenant_id = params.get("tenant_id_1")
            parent_id = params.get("parent_id_1")
            rows = [p for p in self.pickups.values() if p.tenant_id == tenant_id]
            if parent_id:
                rows = [p for p in rows if p.parent_id == parent_id]
            teacher_id = params.get("teacher_id_1")
            if teacher_id:
                rows = [p for p in rows if p.teacher_id == teacher_id]
            status = params.get("status_1")
            if status:
                rows = [p for p in rows if p.status == status]
            rows.sort(key=lambda p: p.requested_at or datetime.now(timezone.utc), reverse=True)
            return _Result(rows=rows)

        if "FROM pickup_requests" in text:
            tenant_id = params.get("tenant_id_1")
            pickup_id = params.get("id_1")
            parent_id = params.get("parent_id_1")
            pickup = self.pickups.get(pickup_id)
            if pickup is None or pickup.tenant_id != tenant_id:
                return _Result(scalar=None)
            if parent_id is not None and pickup.parent_id != parent_id:
                return _Result(scalar=None)
            return _Result(scalar=pickup)

        if "FROM classes" in text and "class_teacher_id" in text:
            tenant_id = params.get("tenant_id_1")
            class_id = params.get("id_1")
            teacher_id = params.get("class_teacher_id_1")
            klass = self.classes.get(class_id)
            if klass and klass.tenant_id == tenant_id and klass.class_teacher_id == teacher_id:
                return _Result(scalar=klass)
            return _Result(scalar=None)

        if "FROM families JOIN student_parents" in text:
            parent_id = params.get("parent_id_1")
            tenant_id = params.get("tenant_id_1")
            family = next((sp.family for sp in self.student_parents if sp.parent_id == parent_id and sp.family and sp.family.tenant_id == tenant_id), None)
            return _Result(scalar=family)

        return _Result(scalar=None, rows=[])


def _app_with_overrides(db: PickupDbStub, tenant: SimpleNamespace, parent: SimpleNamespace | None = None, teacher: SimpleNamespace | None = None, leadership: SimpleNamespace | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(pickup_router)

    app.dependency_overrides[resolve_tenant] = lambda: tenant

    async def _get_db():
        return db

    app.dependency_overrides[get_db] = _get_db
    if parent is not None:
        app.dependency_overrides[resolve_authenticated_parent] = lambda: parent
    if teacher is not None:
        app.dependency_overrides[resolve_authenticated_teacher] = lambda: teacher
    if leadership is not None:
        app.dependency_overrides[resolve_authenticated_leadership] = lambda: leadership

    return TestClient(app)


def _seed_parent_context(db: PickupDbStub):
    tenant_id = uuid.uuid4()
    tenant = SimpleNamespace(id=tenant_id, settings={"pickup_radius_m": 150})

    parent = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="parent")
    teacher_user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="teacher")
    leadership = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal")

    teacher_profile = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, user_id=teacher_user.id)
    db.teachers.append(teacher_profile)

    klass = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, class_teacher_id=teacher_profile.id)
    db.classes[klass.id] = klass

    student = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, class_id=klass.id)
    db.students[student.id] = student

    family = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=True)
    db.student_parents.append(SimpleNamespace(parent_id=parent.id, student_id=student.id, can_pickup=True, family=family))

    db.users[parent.id] = SimpleNamespace(id=parent.id, tenant_id=tenant_id, preferred_channel="email", email="p@test.local", phone=None)

    return tenant, parent, teacher_user, leadership, teacher_profile, student, klass


def _patch_side_effects():
    stack = ExitStack()
    stack.enter_context(patch("services.gateway.routers.pickup.log_action", new=AsyncMock()))
    stack.enter_context(patch("services.gateway.routers.pickup.send_to_user", new=AsyncMock()))
    stack.enter_context(patch("services.gateway.routers.pickup.write_timeline_event", new=AsyncMock()))
    return stack


def test_parent_authenticated_creation_and_no_geofence_auto_release():
    db = PickupDbStub()
    tenant, parent, _, _, _, student, _ = _seed_parent_context(db)
    client = _app_with_overrides(db, tenant, parent=parent)

    with _patch_side_effects():
        response = client.post("/parent/pickup-requests", json={"student_id": str(student.id), "command_text": "pickup now"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "requested"


def test_can_pickup_enforcement():
    db = PickupDbStub()
    tenant, parent, _, _, _, student, _ = _seed_parent_context(db)
    db.student_parents[0].can_pickup = False
    client = _app_with_overrides(db, tenant, parent=parent)

    with _patch_side_effects():
        response = client.post("/parent/pickup-requests", json={"student_id": str(student.id), "command_text": "pickup now"})

    assert response.status_code == 403


def test_cross_tenant_denial():
    db = PickupDbStub()
    tenant, parent, _, _, _, _, _ = _seed_parent_context(db)
    other_student = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), class_id=uuid.uuid4())
    db.students[other_student.id] = other_student
    client = _app_with_overrides(db, tenant, parent=parent)

    with _patch_side_effects():
        response = client.post("/parent/pickup-requests", json={"student_id": str(other_student.id), "command_text": "pickup now"})

    assert response.status_code == 404


def test_leadership_tenant_wide_access():
    db = PickupDbStub()
    tenant, parent, _, leadership, teacher_profile, student, klass = _seed_parent_context(db)
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_profile.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup

    leadership_client = _app_with_overrides(db, tenant, leadership=leadership)

    with _patch_side_effects():
        l_resp = leadership_client.get("/leadership/pickup-requests")

    assert l_resp.status_code == 200
    assert len(l_resp.json()["items"]) >= 1


def test_teacher_denied_for_unauthorized_class_student():
    db = PickupDbStub()
    tenant, parent, teacher_user, _, teacher_profile, student, _ = _seed_parent_context(db)

    other_teacher = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, user_id=uuid.uuid4())
    other_class = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, class_teacher_id=other_teacher.id)
    db.classes[other_class.id] = other_class
    db.students[student.id] = SimpleNamespace(id=student.id, tenant_id=tenant.id, class_id=other_class.id)

    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=other_class.id,
        teacher_id=other_teacher.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup
    db.teachers.append(teacher_profile)

    client = _app_with_overrides(db, tenant, teacher=teacher_user)
    with _patch_side_effects():
        response = client.get(f"/teacher/pickup-requests/{pickup.id}")

    assert response.status_code == 403


def test_legal_lifecycle_and_skipped_transition_rejection_and_terminal_protection_and_completion_requirements():
    db = PickupDbStub()
    tenant, parent, _, leadership, teacher_profile, student, klass = _seed_parent_context(db)
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_profile.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup

    client = _app_with_overrides(db, tenant, leadership=leadership)

    with _patch_side_effects():
        skip = client.post(f"/leadership/pickup-requests/{pickup.id}/prepare", json={"note": "x"})
        assert skip.status_code == 409

        a = client.post(f"/leadership/pickup-requests/{pickup.id}/acknowledge", json={"note": "ok"})
        c = client.post(f"/leadership/pickup-requests/{pickup.id}/call", json={"note": "ok"})
        p = client.post(f"/leadership/pickup-requests/{pickup.id}/prepare", json={"note": "ok"})

        bad_complete = client.post(
            f"/leadership/pickup-requests/{pickup.id}/complete",
            json={"note": "ok", "verification_method": "", "verification_note": ""},
        )

        good_complete = client.post(
            f"/leadership/pickup-requests/{pickup.id}/complete",
            json={"note": "ok", "verification_method": "id_card", "verification_note": "verified at gate"},
        )

        terminal = client.post(f"/leadership/pickup-requests/{pickup.id}/cancel", json={"note": "late"})

    assert a.status_code == 200
    assert c.status_code == 200
    assert p.status_code == 200
    assert bad_complete.status_code == 409
    assert good_complete.status_code == 200
    assert terminal.status_code == 409
    payload = good_complete.json()
    assert payload["status"] == "completed"
    assert payload["verified_by"] == str(leadership.id)
    assert payload["verified_at"] is not None
    assert payload["verification_method"] == "id_card"
    assert payload["verification_note"] == "verified at gate"


def test_cancellation_rules_and_idempotent_same_target_transition():
    db = PickupDbStub()
    tenant, parent, _, leadership, teacher_profile, student, klass = _seed_parent_context(db)
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_profile.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup

    client = _app_with_overrides(db, tenant, leadership=leadership)

    with _patch_side_effects():
        first = client.post(f"/leadership/pickup-requests/{pickup.id}/cancel", json={"note": "x"})
        second = client.post(f"/leadership/pickup-requests/{pickup.id}/cancel", json={"note": "x"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_legacy_endpoint_cannot_bypass_auth_or_verification():
    db = PickupDbStub()
    tenant, _, _, _, _, _, _ = _seed_parent_context(db)
    app = FastAPI()
    app.include_router(pickup_router)
    app.dependency_overrides[resolve_tenant] = lambda: tenant

    async def _get_db():
        return db

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)

    req = client.post(
        "/pickup/request",
        json={
            "parent_phone": "+10000000",
            "command_text": "pickup",
            "latitude": 1,
            "longitude": 1,
        },
    )
    rel = client.post("/pickup/release", json={"pickup_id": str(uuid.uuid4())})

    assert req.status_code == 410
    assert rel.status_code == 410


def test_tenant_linkage_rejected_for_cross_tenant_authenticated_parent():
    db = PickupDbStub()
    tenant, parent, _, _, _, student, _ = _seed_parent_context(db)
    wrong_parent = SimpleNamespace(id=parent.id, tenant_id=uuid.uuid4(), role="parent")
    client = _app_with_overrides(db, tenant, parent=wrong_parent)

    with _patch_side_effects():
        response = client.post("/parent/pickup-requests", json={"student_id": str(student.id), "command_text": "pickup now"})

    assert response.status_code == 401


def test_complete_restricted_to_principal_or_school_admin_only():
    db = PickupDbStub()
    tenant, parent, _, _, teacher_profile, student, klass = _seed_parent_context(db)
    unauthorized_actor = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, role="teacher")
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_profile.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="prepared",
        requested_at=datetime.now(timezone.utc),
        acknowledged_at=datetime.now(timezone.utc),
        called_at=datetime.now(timezone.utc),
        prepared_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup
    client = _app_with_overrides(db, tenant, leadership=unauthorized_actor)

    with _patch_side_effects():
        response = client.post(
            f"/leadership/pickup-requests/{pickup.id}/complete",
            json={"note": "ok", "verification_method": "id_card", "verification_note": "verified at gate"},
        )

    assert response.status_code == 403


def test_audit_timeline_notification_calls_during_transition():
    db = PickupDbStub()
    tenant, parent, _, leadership, teacher_profile, student, klass = _seed_parent_context(db)
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        parent_id=parent.id,
        student_id=student.id,
        class_id=klass.id,
        teacher_id=teacher_profile.id,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
        requested_at=datetime.now(timezone.utc),
    )
    db.pickups[pickup.id] = pickup
    client = _app_with_overrides(db, tenant, leadership=leadership)

    with (
        patch("services.gateway.routers.pickup.log_action", new=AsyncMock()) as audit_mock,
        patch("services.gateway.routers.pickup.send_to_user", new=AsyncMock()) as notify_mock,
        patch("services.gateway.routers.pickup.write_timeline_event", new=AsyncMock()) as timeline_mock,
    ):
        response = client.post(f"/leadership/pickup-requests/{pickup.id}/acknowledge", json={"note": "ok"})

    assert response.status_code == 200
    assert audit_mock.await_count >= 1
    assert timeline_mock.await_count >= 1
    assert notify_mock.await_count >= 1


def test_pickup_migration_and_orm_parity_for_phase_86a_fields():
    pickup = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        teacher_id=None,
        channel="app",
        command_text="pickup",
        parent_latitude=0.0,
        parent_longitude=0.0,
        distance_meters=0.0,
        geofence_radius_m=150,
        within_geofence=False,
        early_pickup=False,
        status="requested",
    )

    for field_name in (
        "acknowledged_at",
        "called_at",
        "prepared_at",
        "completed_at",
        "cancelled_at",
        "cancelled_by",
        "verified_by",
        "verified_at",
        "verification_method",
        "verification_note",
    ):
        assert hasattr(pickup, field_name)

    migration_text = Path("alembic/versions/e1f4a2c9d113_phase_86a_pickup_secure_lifecycle.py").read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "c85b_announcements"' in migration_text
    assert "acknowledged_at" in migration_text
    assert "verification_note" in migration_text
