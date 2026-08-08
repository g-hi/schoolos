from __future__ import annotations

import json
import uuid
from datetime import date as date_type, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.gateway.routers import timetable_generation as tg
from services.gateway.timetable_setup import timetable_versions as tv
from services.gateway.timetable_setup.problem_builder import _build_from_sources
from shared.db.models import TimetableVersion


class _FakeDb:
    def __init__(self, *, scalar_result=None, execute_result=None):
        self.scalar_result = scalar_result
        self.execute_result = execute_result
        self.scalar = AsyncMock(return_value=scalar_result)
        self.execute = AsyncMock(return_value=execute_result)
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()
        self.add = Mock()
        self.add_all = Mock()

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _actor(*, tenant_id: uuid.UUID, role: str = "principal", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active)


@pytest.mark.asyncio
async def test_lifecycle_happy_path_transitions_direct_service() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")
    version = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=uuid.uuid4(),
        lifecycle_status="candidate",
        submitted_at=None,
        approved_at=None,
        published_at=None,
        effective_from=None,
        effective_until=None,
        published_by_user_id=None,
        approved_by_user_id=None,
        submitted_by_user_id=None,
        superseded_at=None,
        superseded_by_version_id=None,
    )
    db = _FakeDb(scalar_result=1)

    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        submitted = await tv.transition_submit(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
        assert submitted.lifecycle_status == "under_review"
        approved = await tv.transition_approve(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
        assert approved.lifecycle_status == "approved"
        published = await tv.transition_publish(db, tenant_id=tenant.id, version_id=version.id, actor=actor, effective_from=date_type(2026, 9, 1))
        assert published.lifecycle_status == "published"
        assert published.effective_from == date_type(2026, 9, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transition_name", "start_status", "target_status"),
    [
        ("submit", "under_review", "approved"),
        ("submit", "approved", "published"),
        ("cancel", "cancelled", "published"),
        ("approve", "published", "under_review"),
        ("approve", "superseded", "approved"),
        ("publish", "superseded", "published"),
    ],
)
async def test_invalid_lifecycle_transitions_raise_controlled_conflict(transition_name: str, start_status: str, target_status: str) -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")
    version = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=uuid.uuid4(),
        lifecycle_status=start_status,
        submitted_at=None,
        approved_at=None,
        published_at=None,
        effective_from=None,
        effective_until=None,
        published_by_user_id=None,
        approved_by_user_id=None,
        submitted_by_user_id=None,
        superseded_at=None,
        superseded_by_version_id=None,
    )
    db = _FakeDb(scalar_result=1)

    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        with pytest.raises(tv.TimetableVersionError) as exc:
            if transition_name == "submit":
                await tv.transition_submit(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
            elif transition_name == "cancel":
                await tv.transition_cancel(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
            elif transition_name == "approve":
                await tv.transition_approve(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
            else:
                await tv.transition_publish(db, tenant_id=tenant.id, version_id=version.id, actor=actor, effective_from=date_type(2026, 9, 1))

    assert exc.value.status_code == 409
    assert exc.value.code == "invalid_transition"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["school_admin", "teacher", "agent"])
async def test_non_principal_roles_cannot_approve_or_publish(role: str) -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role=role)
    version = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=uuid.uuid4(),
        lifecycle_status="under_review",
        submitted_at=None,
        approved_at=None,
        published_at=None,
        effective_from=None,
        effective_until=None,
        published_by_user_id=None,
        approved_by_user_id=None,
        submitted_by_user_id=None,
        superseded_at=None,
        superseded_by_version_id=None,
    )
    db = _FakeDb(scalar_result=1)

    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        with pytest.raises(tv.TimetableVersionError) as approve_exc:
            await tv.transition_approve(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
        assert approve_exc.value.code == "principal_required"
        assert approve_exc.value.status_code == 403

    version.lifecycle_status = "approved"
    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        with pytest.raises(tv.TimetableVersionError) as publish_exc:
            await tv.transition_publish(db, tenant_id=tenant.id, version_id=version.id, actor=actor, effective_from=date_type(2026, 9, 1))
        assert publish_exc.value.code == "principal_required"
        assert publish_exc.value.status_code == 403


@pytest.mark.asyncio
async def test_publication_rollback_restores_previous_state() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")
    previous = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=uuid.uuid4(),
        lifecycle_status="published",
        effective_from=date_type(2026, 8, 20),
        effective_until=None,
        superseded_by_version_id=None,
        superseded_at=None,
        published_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        published_by_user_id=uuid.uuid4(),
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=previous.timetable_id,
        lifecycle_status="approved",
        effective_from=None,
        effective_until=None,
        superseded_by_version_id=None,
        superseded_at=None,
        published_at=None,
        published_by_user_id=None,
    )
    db = _FakeDb(scalar_result=1)
    db.execute = AsyncMock(return_value=_FakeResult([previous]))
    db.flush = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        with pytest.raises(RuntimeError):
            await tv.transition_publish(db, tenant_id=tenant.id, version_id=version.id, actor=actor, effective_from=date_type(2026, 10, 1))

    assert previous.lifecycle_status == "published"
    assert previous.effective_until is None
    assert previous.superseded_by_version_id is None
    assert version.lifecycle_status == "approved"
    assert version.published_at is None
    assert version.published_by_user_id is None
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_effective_date_lookup_uses_half_open_semantics() -> None:
    tenant_id = uuid.uuid4()
    timetable_id = uuid.uuid4()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(TimetableVersion.__table__.create)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            v1 = TimetableVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                timetable_id=timetable_id,
                version_number=1,
                generation_mode="standard",
                lifecycle_status="published",
                effective_from=date_type(2026, 8, 20),
                effective_until=date_type(2026, 10, 1),
            )
            v2 = TimetableVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                timetable_id=timetable_id,
                version_number=2,
                generation_mode="standard",
                lifecycle_status="published",
                effective_from=date_type(2026, 10, 1),
                effective_until=None,
            )
            future = TimetableVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                timetable_id=timetable_id,
                version_number=3,
                generation_mode="standard",
                lifecycle_status="published",
                effective_from=date_type(2026, 10, 15),
                effective_until=None,
            )
            session.add_all([v1, v2, future])
            await session.commit()

            resolved_sep = await tv.resolve_effective_version(db=session, tenant_id=tenant_id, timetable_id=timetable_id, on_date=date_type(2026, 9, 30))
            assert resolved_sep is not None and resolved_sep.id == v1.id

            resolved_oct = await tv.resolve_effective_version(db=session, tenant_id=tenant_id, timetable_id=timetable_id, on_date=date_type(2026, 10, 1))
            assert resolved_oct is not None and resolved_oct.id == v2.id

            resolved_later = await tv.resolve_effective_version(db=session, tenant_id=tenant_id, timetable_id=timetable_id, on_date=date_type(2026, 11, 10))
            assert resolved_later is not None and resolved_later.id == v2.id

            future_only = await tv.resolve_effective_version(db=session, tenant_id=tenant_id, timetable_id=timetable_id, on_date=date_type(2026, 10, 5))
            assert future_only is not None and future_only.id == v2.id

            no_match = await tv.resolve_effective_version(db=session, tenant_id=tenant_id, timetable_id=timetable_id, on_date=date_type(2026, 7, 1))
            assert no_match is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repair_impact_classification_stays_minimal_and_manual_lock_is_preserved() -> None:
    tenant = _tenant()
    configuration = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, stability_mode="balanced", baseline_timetable_version_id=uuid.uuid4())
    baseline_version = SimpleNamespace(id=configuration.baseline_timetable_version_id)
    assignments = [
        SimpleNamespace(
            assignment_key="direct-math",
            occurrence_id="occ-direct",
            requirement_id="req-math",
            class_id="class-8a",
            subject_id="subject-math",
            teacher_id="teacher-a",
            room_id="room-1",
            day_key="d1",
            period_key="d1:p3",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p3"],
            parallel_block_id=None,
            parallel_child_id=None,
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
        SimpleNamespace(
            assignment_key="protected-math",
            occurrence_id="occ-protected",
            requirement_id="req-math-2",
            class_id="class-8a",
            subject_id="subject-math",
            teacher_id="teacher-b",
            room_id="room-2",
            day_key="d1",
            period_key="d1:p4",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p4"],
            parallel_block_id=None,
            parallel_child_id=None,
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
        SimpleNamespace(
            assignment_key="manual-lock",
            occurrence_id="occ-lock",
            requirement_id="req-math-3",
            class_id="class-8a",
            subject_id="subject-math",
            teacher_id="teacher-c",
            room_id="room-3",
            day_key="d1",
            period_key="d1:p5",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p5"],
            parallel_block_id=None,
            parallel_child_id=None,
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
    ]
    db = _FakeDb()
    db.execute = AsyncMock(return_value=_FakeResult([SimpleNamespace(target_reference_code="manual-lock", is_manual_hard_lock=True)]))

    with (
        patch.object(tv, "_get_configuration", new=AsyncMock(return_value=configuration)),
        patch.object(tv, "_get_version", new=AsyncMock(return_value=baseline_version)),
        patch.object(tv, "load_version_assignments", new=AsyncMock(return_value=assignments)),
        patch.object(tv, "build_scheduling_problem", new=AsyncMock(return_value=SimpleNamespace(problem=SimpleNamespace(classes=[SimpleNamespace(class_id="class-8a", grade_reference="Grade 8")])))),
    ):
        payload = await tv.repair_impact_preview(
            db,
            tenant_id=tenant.id,
            configuration_id=configuration.id,
            repair_reason="teacher_replacement",
            scope_level="minimum",
            trigger_teacher_ids=("teacher-a",),
            trigger_class_ids=(),
            trigger_room_ids=(),
            trigger_requirement_ids=(),
            trigger_occurrence_ids=(),
            trigger_parallel_block_ids=(),
        )

    assert payload["direct_count"] == 1
    assert payload["direct_assignments"][0]["occurrence_id"] == "occ-direct"
    assert payload["protected_count"] == 1
    assert payload["manual_lock_count"] == 1
    assert payload["blockers"] == [{"code": "direct_assignment_manually_locked", "count": 1}]
    assert payload["suggested_next_scope"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope_level", "expected_direct", "expected_conditional", "expected_protected"),
    [
        ("minimum", 1, 0, 2),
        ("affected_entities", 1, 1, 1),
        ("grade", 1, 1, 1),
        ("whole_school", 1, 2, 0),
    ],
)
async def test_repair_scope_levels_follow_documented_semantics(scope_level: str, expected_direct: int, expected_conditional: int, expected_protected: int) -> None:
    tenant = _tenant()
    configuration = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, stability_mode="balanced", baseline_timetable_version_id=uuid.uuid4())
    baseline_version = SimpleNamespace(id=configuration.baseline_timetable_version_id)
    assignments = [
        SimpleNamespace(
            assignment_key="direct-a",
            occurrence_id="occ-direct",
            requirement_id="req-a",
            class_id="class-8a",
            subject_id="subj-a",
            teacher_id="teacher-a",
            room_id="room-1",
            day_key="d1",
            period_key="d1:p3",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p3"],
            parallel_block_id=None,
            parallel_child_id=None,
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
        SimpleNamespace(
            assignment_key="protected-b",
            occurrence_id="occ-protected",
            requirement_id="req-b",
            class_id="class-8b",
            subject_id="subj-b",
            teacher_id="teacher-b",
            room_id="room-2",
            day_key="d1",
            period_key="d1:p4",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p4"],
            parallel_block_id=None,
            parallel_child_id=None,
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
    ]
    db = _FakeDb()
    db.execute = AsyncMock(return_value=_FakeResult([]))

    with (
        patch.object(tv, "_get_configuration", new=AsyncMock(return_value=configuration)),
        patch.object(tv, "_get_version", new=AsyncMock(return_value=baseline_version)),
        patch.object(tv, "load_version_assignments", new=AsyncMock(return_value=assignments)),
        patch.object(tv, "build_scheduling_problem", new=AsyncMock(return_value=SimpleNamespace(problem=SimpleNamespace(classes=[SimpleNamespace(class_id="class-8a", grade_reference="Grade 8"), SimpleNamespace(class_id="class-8b", grade_reference="Grade 9")])))),
    ):
        payload = await tv.repair_impact_preview(
            db,
            tenant_id=tenant.id,
            configuration_id=configuration.id,
            repair_reason="teacher_replacement",
            scope_level=scope_level,
            trigger_teacher_ids=("teacher-a",),
            trigger_class_ids=(),
            trigger_room_ids=(),
            trigger_requirement_ids=(),
            trigger_occurrence_ids=(),
            trigger_parallel_block_ids=(),
        )

    assert payload["direct_count"] == expected_direct
    assert payload["conditionally_movable_count"] == expected_conditional
    assert payload["protected_count"] == expected_protected


@pytest.mark.asyncio
async def test_department_scope_is_not_supported() -> None:
    tenant = _tenant()
    configuration = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, stability_mode="balanced", baseline_timetable_version_id=uuid.uuid4())
    baseline_version = SimpleNamespace(id=configuration.baseline_timetable_version_id)
    db = _FakeDb()

    with (
        patch.object(tv, "_get_configuration", new=AsyncMock(return_value=configuration)),
        patch.object(tv, "_get_version", new=AsyncMock(return_value=baseline_version)),
        patch.object(tv, "load_version_assignments", new=AsyncMock(return_value=[])),
    ):
        with pytest.raises(tv.TimetableVersionError) as exc:
            await tv.repair_impact_preview(
                db,
                tenant_id=tenant.id,
                configuration_id=configuration.id,
                repair_reason="teacher_replacement",
                scope_level="department",
                trigger_teacher_ids=(),
                trigger_class_ids=(),
                trigger_room_ids=(),
                trigger_requirement_ids=(),
                trigger_occurrence_ids=(),
                trigger_parallel_block_ids=(),
            )

    assert exc.value.code == "repair_scope_invalid"


@pytest.mark.asyncio
async def test_foreign_language_repair_marks_only_the_replaced_child_direct() -> None:
    tenant = _tenant()
    configuration = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id, stability_mode="balanced", baseline_timetable_version_id=uuid.uuid4())
    baseline_version = SimpleNamespace(id=configuration.baseline_timetable_version_id)
    assignments = [
        SimpleNamespace(
            assignment_key="french-child",
            occurrence_id="occ-french",
            requirement_id="req-french",
            class_id="class-8a",
            subject_id="subject-fr",
            teacher_id="teacher-f",
            room_id="room-1",
            day_key="d1",
            period_key="d1:p3",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p3"],
            parallel_block_id="block-foreign-language",
            parallel_child_id="child-french",
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
        SimpleNamespace(
            assignment_key="german-child",
            occurrence_id="occ-german",
            requirement_id="req-german",
            class_id="class-8a",
            subject_id="subject-de",
            teacher_id="teacher-g",
            room_id="room-1",
            day_key="d1",
            period_key="d1:p3",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p3"],
            parallel_block_id="block-foreign-language",
            parallel_child_id="child-german",
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
        SimpleNamespace(
            assignment_key="spanish-child",
            occurrence_id="occ-spanish",
            requirement_id="req-spanish",
            class_id="class-8a",
            subject_id="subject-es",
            teacher_id="teacher-s",
            room_id="room-1",
            day_key="d1",
            period_key="d1:p3",
            periods_per_session=1,
            occupied_period_keys_json=["d1:p3"],
            parallel_block_id="block-foreign-language",
            parallel_child_id="child-spanish",
            fixed=False,
            lock_state=None,
            protection_snapshot_json={},
            provenance_json={},
        ),
    ]
    db = _FakeDb()
    db.execute = AsyncMock(return_value=_FakeResult([]))

    with (
        patch.object(tv, "_get_configuration", new=AsyncMock(return_value=configuration)),
        patch.object(tv, "_get_version", new=AsyncMock(return_value=baseline_version)),
        patch.object(tv, "load_version_assignments", new=AsyncMock(return_value=assignments)),
        patch.object(tv, "build_scheduling_problem", new=AsyncMock(return_value=SimpleNamespace(problem=SimpleNamespace(classes=[SimpleNamespace(class_id="class-8a", grade_reference="Grade 8")])))),
    ):
        payload = await tv.repair_impact_preview(
            db,
            tenant_id=tenant.id,
            configuration_id=configuration.id,
            repair_reason="teacher_replacement",
            scope_level="minimum",
            trigger_teacher_ids=("teacher-g",),
            trigger_class_ids=(),
            trigger_room_ids=(),
            trigger_requirement_ids=(),
            trigger_occurrence_ids=(),
            trigger_parallel_block_ids=(),
        )

    direct_ids = [item["occurrence_id"] for item in payload["direct_assignments"]]
    assert direct_ids == ["occ-german"]
    assert payload["protected_count"] == 2
    assert payload["direct_assignments"][0]["parallel_block_id"] == "block-foreign-language"


@pytest.mark.asyncio
async def test_multiperiod_diff_counts_as_one_move() -> None:
    left = [
        {
            "assignment_key": "science-block",
            "occurrence_id": "occ-science",
            "requirement_id": "req-science",
            "class_id": "class-8a",
            "subject_id": "subj-science",
            "teacher_id": "teacher-a",
            "room_id": "room-1",
            "day_key": "d1",
            "period_key": "d1:p3",
            "periods_per_session": 2,
            "occupied_period_keys": ["d1:p3", "d1:p4"],
            "parallel_block_id": None,
            "parallel_child_id": None,
            "fixed": False,
            "lock_state": None,
            "protection_snapshot": {},
            "provenance": {},
        }
    ]
    right = [
        {
            "assignment_key": "science-block",
            "occurrence_id": "occ-science",
            "requirement_id": "req-science",
            "class_id": "class-8a",
            "subject_id": "subj-science",
            "teacher_id": "teacher-a",
            "room_id": "room-1",
            "day_key": "d1",
            "period_key": "d1:p4",
            "periods_per_session": 2,
            "occupied_period_keys": ["d1:p4", "d1:p5"],
            "parallel_block_id": None,
            "parallel_child_id": None,
            "fixed": False,
            "lock_state": None,
            "protection_snapshot": {},
            "provenance": {},
        }
    ]
    diff = tv.compute_version_diff(left, right)
    assert diff["moved"] == 1
    assert diff["teacher_changes"] == 0
    assert diff["room_changes"] == 0
    assert diff["details"] == [{"kind": "moved", "assignment_key": "science-block"}]


def test_problem_builder_preserves_baseline_fields_and_excludes_private_notes() -> None:
    configuration = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        campus_id=uuid.uuid4(),
        generation_mode="repair",
        stability_mode="balanced",
        baseline_reference_type="timetable_version",
        baseline_reference_id=uuid.uuid4(),
        baseline_timetable_version_id=uuid.uuid4(),
        lifecycle_status="approved",
        repair_scope_json={"scope_level": "minimum"},
        validation_summary_json={"is_valid": True},
    )
    rows = {
        "school_week": SimpleNamespace(id=uuid.uuid4(), name="Week", operational_weekdays=[0, 1, 2, 3, 4]),
        "bell_schedule": SimpleNamespace(id=uuid.uuid4(), name="Main", schedule_type="normal"),
        "bell_periods": [
            SimpleNamespace(id=uuid.uuid4(), period_number=1, label="P1", start_time="08:00", end_time="08:40", is_teaching_period=True),
            SimpleNamespace(id=uuid.uuid4(), period_number=2, label="P2", start_time="08:45", end_time="09:25", is_teaching_period=True),
        ],
        "baseline_version": SimpleNamespace(
            id=configuration.baseline_timetable_version_id,
            tenant_id=configuration.tenant_id,
            generation_mode="repair",
            lifecycle_status="published",
            timetable_id=uuid.uuid4(),
        ),
        "baseline_assignments": [
            SimpleNamespace(
                assignment_key="req_math_8a#occ1|",
                occurrence_id="req_math_8a#occ1",
                requirement_id="req_math_8a",
                class_id=str(uuid.uuid4()),
                subject_id=str(uuid.uuid4()),
                teacher_id=str(uuid.uuid4()),
                room_id=str(uuid.uuid4()),
                day_key="d0",
                period_key="d0:p1",
                periods_per_session=1,
                occupied_period_keys_json=["d0:p1"],
                parallel_block_id=None,
                parallel_child_id=None,
                fixed=True,
                lock_state="locked",
                timetable_version_id=configuration.baseline_timetable_version_id,
            )
        ],
        "teachers": [SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), max_weekly_hours=20)],
        "users": [SimpleNamespace(id=uuid.uuid4(), is_active=True)],
        "teacher_subjects": [SimpleNamespace(teacher_id=uuid.uuid4(), subject_id=uuid.uuid4())],
        "classes": [SimpleNamespace(id=uuid.uuid4(), is_active=True, code="8A", grade_level_id=uuid.uuid4(), grade="Grade 8", campus_id=uuid.uuid4())],
        "subjects": [SimpleNamespace(id=uuid.uuid4(), code="FR", name="French")],
        "rooms": [SimpleNamespace(id=uuid.uuid4(), room_code="R101", room_name="Room 101", room_type="standard_classroom", capacity=30, campus_id=uuid.uuid4(), specialist_capabilities=["audio"])],
        "requirements": [
            SimpleNamespace(
                id=uuid.uuid4(),
                class_id=uuid.uuid4(),
                subject_id=uuid.uuid4(),
                teacher_id=uuid.uuid4(),
                sessions_per_week=3,
                periods_per_session=1,
                min_daily_sessions=0,
                max_daily_sessions=2,
                specialist_room_type=None,
                preferred_period_numbers=[1],
                forbidden_period_numbers=[],
                has_fixed_sessions=True,
                fixed_session_rules=[{"day_of_week": 0, "period_number": 1, "room_id": str(uuid.uuid4())}],
                source_type="manual",
            )
        ],
        "assignments": [SimpleNamespace(id=uuid.uuid4(), teacher_id=uuid.uuid4())],
        "preferences": [
            SimpleNamespace(
                id=uuid.uuid4(),
                teacher_id=uuid.uuid4(),
                preference_type="avoid_selected_periods",
                strength="strong",
                weekdays_json=[0],
                period_numbers_json=[2],
                effective_start_date=None,
                effective_end_date=None,
                source_type="manual",
                provenance_json={"source": "principal"},
                temporary_accommodation_text="internal private note",
                leadership_note="confidential note",
            )
        ],
        "overrides": [],
        "locks": [],
        "objectives": [],
        "parallel_blocks": [],
        "parallel_children": [],
        "policy_constraints": [],
    }
    policy_payload = {"generation_allowed": True, "effective_constraints": []}

    build = _build_from_sources(configuration=configuration, rows=rows, policy_payload=policy_payload)
    baseline = build.problem.baseline.assignments[0]

    assert baseline.periods_per_session == 1
    assert baseline.occupied_period_keys == ["d0:p1"]
    assert baseline.parallel_block_id is None
    assert baseline.parallel_child_id is None
    assert baseline.teacher_id is not None
    assert baseline.class_id is not None
    assert baseline.subject_id is not None
    assert baseline.room_id is not None
    payload = build.problem.to_dict()
    private_text = "internal private note"
    assert private_text not in json.dumps(payload)


@pytest.mark.asyncio
async def test_assignment_routes_are_not_mutable_and_lifecycle_does_not_change_assignment_semantics() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id, role="principal")
    version = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        timetable_id=uuid.uuid4(),
        lifecycle_status="candidate",
        submitted_at=None,
        approved_at=None,
        published_at=None,
        effective_from=None,
        effective_until=None,
        published_by_user_id=None,
        approved_by_user_id=None,
        submitted_by_user_id=None,
        superseded_at=None,
        superseded_by_version_id=None,
    )
    assignment = SimpleNamespace(
        teacher_id="teacher-a",
        room_id="room-1",
        period_key="d1:p3",
        occupied_period_keys=["d1:p3"],
        subject_id="subject-math",
        class_id="class-8a",
    )
    version.assignments = [assignment]
    db = _FakeDb(scalar_result=1)

    with patch.object(tv, "_get_version", new=AsyncMock(return_value=version)):
        submitted = await tv.transition_submit(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
        approved = await tv.transition_approve(db, tenant_id=tenant.id, version_id=version.id, actor=actor)
        published = await tv.transition_publish(db, tenant_id=tenant.id, version_id=version.id, actor=actor, effective_from=date_type(2026, 9, 1))

    assert submitted.lifecycle_status == "under_review"
    assert approved.lifecycle_status == "approved"
    assert published.lifecycle_status == "published"
    assert assignment.teacher_id == "teacher-a"
    assert assignment.room_id == "room-1"
    assert assignment.period_key == "d1:p3"

    mutable_routes = {
        route.path for route in tg.router.routes if getattr(route, "methods", set()) & {"PATCH", "PUT"} and "assignments" in route.path
    }
    assert mutable_routes == set()
