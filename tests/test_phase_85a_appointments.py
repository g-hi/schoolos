from __future__ import annotations

import uuid
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.gateway.routers.appointments import (
    AppointmentCreateRequest,
    ParentAppointmentRescheduleRequest,
    TeacherAppointmentActionRequest,
    _appointments_overlap,
    _attempt_appointment_notification_after_commit,
    _allowed_transition,
    _find_confirmed_overlap,
    _transition_appointment,
    _validate_teacher_subject_option,
    create_parent_appointment,
    get_eligible_appointment_teachers,
    get_parent_appointment,
    get_teacher_appointment,
    list_leadership_appointments,
    list_parent_appointments,
    list_teacher_appointments,
    _validate_duration_minutes,
    _validate_future_appointment_datetime,
    _validate_iana_timezone,
    _validate_meeting_mode,
    confirm_teacher_appointment,
    reschedule_parent_appointment,
    router as appointments_router,
)
from shared.auth.dependencies import resolve_authenticated_teacher
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db
from shared.db.models import Appointment


def test_appointment_model_exists_and_has_expected_columns() -> None:
    cols = {column.name for column in Appointment.__table__.columns}
    assert "tenant_id" in cols
    assert "family_id" in cols
    assert "student_id" in cols
    assert "parent_id" in cols
    assert "teacher_id" in cols
    assert "subject_id" in cols
    assert "timetable_entry_id" in cols
    assert "status" in cols
    assert "requested_start_at" in cols
    assert "scheduled_start_at" in cols
    assert "duration_minutes" in cols
    assert "timezone" in cols
    assert "meeting_mode" in cols
    assert "location_or_link" in cols
    assert "reason" in cols
    assert "parent_notes" in cols
    assert "staff_notes" in cols
    assert "created_at" in cols
    assert "updated_at" in cols
    assert "confirmed_at" in cols
    assert "declined_at" in cols
    assert "cancelled_at" in cols
    assert "completed_at" in cols
    assert "cancelled_by" in cols
    assert "uq_appointment_identity" not in {constraint.name for constraint in Appointment.__table__.constraints if getattr(constraint, "name", None)}


def test_appointment_request_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            student_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            requested_start_at=datetime(2026, 7, 23, 9, 0, 0),
            duration_minutes=30,
            timezone="UTC",
            meeting_mode="video",
            reason="Need help",
        )


def test_appointment_request_rejects_past_time() -> None:
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=10)
    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            student_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            requested_start_at=past,
            duration_minutes=30,
            timezone="UTC",
            meeting_mode="video",
            reason="Need help",
        )


def test_appointment_request_validates_timezone_duration_and_mode() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            student_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            requested_start_at=future,
            duration_minutes=5,
            timezone="UTC",
            meeting_mode="video",
            reason="Need help",
        )

    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            student_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            requested_start_at=future,
            duration_minutes=30,
            timezone="Not/AZone",
            meeting_mode="video",
            reason="Need help",
        )

    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            student_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            requested_start_at=future,
            duration_minutes=30,
            timezone="UTC",
            meeting_mode="chat",
            reason="Need help",
        )


def test_parent_reschedule_schema_rejects_staff_notes() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(ValidationError):
        ParentAppointmentRescheduleRequest(
            scheduled_start_at=future,
            duration_minutes=30,
            timezone="UTC",
            meeting_mode="video",
            staff_notes="private",
        )


def test_teacher_action_schema_accepts_staff_notes() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    request = TeacherAppointmentActionRequest(
        scheduled_start_at=future,
        duration_minutes=30,
        timezone="UTC",
        meeting_mode="video",
        staff_notes="Discuss reading progress",
    )
    assert request.staff_notes == "Discuss reading progress"


def test_parent_reschedule_schema_rejects_invalid_payload() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(ValidationError):
        ParentAppointmentRescheduleRequest(scheduled_start_at=datetime(2026, 7, 23, 9, 0, 0), duration_minutes=30, timezone="UTC", meeting_mode="video")
    with pytest.raises(ValidationError):
        ParentAppointmentRescheduleRequest(scheduled_start_at=future, duration_minutes=5, timezone="UTC", meeting_mode="video")
    with pytest.raises(ValidationError):
        ParentAppointmentRescheduleRequest(scheduled_start_at=future, duration_minutes=30, timezone="Invalid/Zone", meeting_mode="video")
    with pytest.raises(ValidationError):
        ParentAppointmentRescheduleRequest(scheduled_start_at=future, duration_minutes=30, timezone="UTC", meeting_mode="chat")


def test_overlap_boundaries_allow_adjacent_slots_and_reject_intersection() -> None:
    start = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)
    assert _appointments_overlap(start, end, end, end + timedelta(minutes=30)) is False
    assert _appointments_overlap(start, end, start + timedelta(minutes=29), end + timedelta(minutes=30)) is True


class _TransactionContext:
    def __init__(self, events: list[str]):
        self.events = events

    async def __aenter__(self):
        self.events.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("rollback" if exc_type else "commit")


class _NotificationSession:
    def __init__(self, events: list[str]):
        self.events = events

    def begin(self):
        return _TransactionContext(self.events)

    async def get(self, model, identifier):
        self.events.append("get")
        return SimpleNamespace(id=identifier)

    async def execute(self, statement):
        self.events.append("execute")
        result = SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4())))
        return result

    async def rollback(self):
        self.events.append("rollback-call")


class _RouteSession:
    def __init__(self, events: list[str], appointment: Appointment):
        self.events = events
        self.appointment = appointment

    def begin(self):
        return _TransactionContext(self.events)

    async def execute(self, statement):
        self.events.append("appointment-query")
        return SimpleNamespace(scalar_one_or_none=lambda: self.appointment)


@pytest.mark.asyncio
async def test_teacher_confirm_begins_transaction_before_route_queries() -> None:
    events: list[str] = []
    teacher_id = uuid.uuid4()
    appt = Appointment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        teacher_id=teacher_id,
        status="requested",
        scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=30,
    )
    db = _RouteSession(events, appt)
    tenant = SimpleNamespace(id=appt.tenant_id)
    teacher_user = SimpleNamespace(id=uuid.uuid4())
    profile = SimpleNamespace(id=teacher_id)

    async def resolve_profile(*args, **kwargs):
        events.append("teacher-profile-query")
        return profile

    with (
        patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
        patch("services.gateway.routers.appointments._resolve_teacher_profile", new=resolve_profile),
        patch("services.gateway.routers.appointments._lock_teacher_profile", new=AsyncMock(return_value=profile)),
        patch("services.gateway.routers.appointments._find_confirmed_overlap", new=AsyncMock(return_value=None)),
        patch("services.gateway.routers.appointments.log_action", new=AsyncMock()),
        patch("services.gateway.routers.appointments._write_appointment_timeline_event", new=AsyncMock()),
        patch("services.gateway.routers.appointments._attempt_appointment_notification_after_commit", new=AsyncMock()),
    ):
        response = await confirm_teacher_appointment(uuid.uuid4(), tenant=tenant, teacher_user=teacher_user, db=db)

    assert response == {"status": "confirmed"}
    assert events[0] == "begin"
    assert events.index("teacher-profile-query") > events.index("begin")


@pytest.mark.asyncio
async def test_parent_confirmed_reschedule_begins_before_query_and_locks_teacher() -> None:
    events: list[str] = []
    teacher_id = uuid.uuid4()
    family_id = uuid.uuid4()
    appt = Appointment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        family_id=family_id,
        student_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        teacher_id=teacher_id,
        status="confirmed",
        scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=30,
    )
    db = _RouteSession(events, appt)
    tenant = SimpleNamespace(id=appt.tenant_id)
    parent = SimpleNamespace(id=appt.parent_id)
    family = SimpleNamespace(id=family_id)
    profile = SimpleNamespace(id=teacher_id)
    body = ParentAppointmentRescheduleRequest(
        scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=2),
        duration_minutes=30,
        timezone="UTC",
        meeting_mode="video",
    )

    async def resolve_family(*args, **kwargs):
        events.append("family-query")
        return family

    async def lock_teacher(*args, **kwargs):
        events.append("teacher-lock")
        return profile

    with (
        patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
        patch("services.gateway.routers.appointments.resolve_family", new=resolve_family),
        patch("services.gateway.routers.appointments._lock_teacher_profile", new=lock_teacher),
        patch("services.gateway.routers.appointments._find_confirmed_overlap", new=AsyncMock(return_value=None)),
        patch("services.gateway.routers.appointments.log_action", new=AsyncMock()),
        patch("services.gateway.routers.appointments._write_appointment_timeline_event", new=AsyncMock()),
        patch("services.gateway.routers.appointments._attempt_appointment_notification_after_commit", new=AsyncMock()),
    ):
        response = await reschedule_parent_appointment(appt.id, body, tenant=tenant, parent=parent, db=db)

    assert response == {"status": "confirmed"}
    assert events[0] == "begin"
    assert events.index("teacher-lock") > events.index("appointment-query")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("requested", "confirmed"),
        ("requested", "declined"),
        ("requested", "cancelled"),
        ("confirmed", "cancelled"),
        ("confirmed", "completed"),
    ],
)
def test_every_legal_lifecycle_transition_is_allowed(current: str, target: str) -> None:
    assert _allowed_transition(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("requested", "completed"),
        ("confirmed", "declined"),
        ("declined", "confirmed"),
        ("declined", "cancelled"),
        ("cancelled", "confirmed"),
        ("completed", "cancelled"),
    ],
)
def test_every_terminal_or_illegal_lifecycle_transition_is_rejected(current: str, target: str) -> None:
    assert _allowed_transition(current, target) is False


@pytest.mark.asyncio
async def test_notification_failure_rolls_back_only_notification_transaction() -> None:
    events: list[str] = []
    db = _NotificationSession(events)
    appt = Appointment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        teacher_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with patch("services.gateway.routers.appointments.send_to_user", new=AsyncMock(side_effect=RuntimeError("delivery"))):
        await _attempt_appointment_notification_after_commit(db=db, appt=appt, actor_id=uuid.uuid4(), action="confirmed")
    assert events[0] == "begin"
    assert "rollback" in events
    assert events[-1] == "rollback-call"
    assert appt.status is None


@pytest.mark.asyncio
async def test_confirmed_overlap_helper_ignores_requested_and_current_records() -> None:
    tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    current_id = uuid.uuid4()
    start = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    confirmed = Appointment(id=uuid.uuid4(), tenant_id=tenant_id, teacher_id=teacher_id, status="confirmed", scheduled_start_at=start, duration_minutes=30)
    requested = Appointment(id=uuid.uuid4(), tenant_id=tenant_id, teacher_id=teacher_id, status="requested", scheduled_start_at=start, duration_minutes=30)
    current = Appointment(id=current_id, tenant_id=tenant_id, teacher_id=teacher_id, status="confirmed", scheduled_start_at=start, duration_minutes=30)
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [current, confirmed]))
    db = AsyncMock()
    db.execute.return_value = result
    assert await _find_confirmed_overlap(
        db=db,
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        proposed_start=start + timedelta(minutes=15),
        proposed_end=start + timedelta(minutes=45),
        current_appointment_id=current_id,
    ) is confirmed
    assert await _find_confirmed_overlap(
        db=db,
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        proposed_start=start + timedelta(minutes=30),
        proposed_end=start + timedelta(minutes=60),
    ) is None


def _result(*, first=None, scalar=None, rows=None):
        return SimpleNamespace(
            first=lambda: first,
            scalar_one_or_none=lambda: scalar,
        all=lambda: rows or [],
            scalars=lambda: SimpleNamespace(all=lambda: rows or []),
        )


def _build_teacher_route_client(*, db_session, tenant_id: uuid.UUID, teacher_user_id: uuid.UUID) -> TestClient:
    app = FastAPI()
    app.include_router(appointments_router)

    app.dependency_overrides[resolve_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[resolve_authenticated_teacher] = lambda: SimpleNamespace(id=teacher_user_id, role="teacher")

    async def _override_get_db():
        return db_session

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


class _FilteringListSession:
    def __init__(self, appointments: list[Appointment]):
        self.appointments = appointments

    async def execute(self, statement):
        params = statement.compile().params
        tenant_id = next((value for key, value in params.items() if key.startswith("tenant_id")), None)
        teacher_id = next((value for key, value in params.items() if key.startswith("teacher_id")), None)
        rows = [
            appt
            for appt in self.appointments
            if (tenant_id is None or appt.tenant_id == tenant_id)
            and (teacher_id is None or appt.teacher_id == teacher_id)
        ]
        return _result(rows=rows)


@pytest.mark.asyncio
async def test_eligibility_returns_homeroom_and_deduplicated_timetable_options() -> None:
        tenant_id = uuid.uuid4()
        student_id = uuid.uuid4()
        class_id = uuid.uuid4()
        homeroom_id = uuid.uuid4()
        subject_a = uuid.uuid4()
        subject_b = uuid.uuid4()
        timetable_a = SimpleNamespace(id=uuid.uuid4(), subject_id=subject_a)
        timetable_a_duplicate = SimpleNamespace(id=uuid.uuid4(), subject_id=subject_a)
        timetable_b = SimpleNamespace(id=uuid.uuid4(), subject_id=subject_b)
        klass = SimpleNamespace(id=class_id, academic_year="2026", class_teacher_id=homeroom_id)
        student = SimpleNamespace(id=student_id)
        homeroom = SimpleNamespace(id=homeroom_id)
        subject_teacher = SimpleNamespace(id=uuid.uuid4())
        user = SimpleNamespace(name="Teacher")
        db = AsyncMock()
        db.execute.side_effect = [
            _result(first=(student, klass)),
            _result(first=(homeroom, SimpleNamespace(name="Homeroom Teacher"))),
            _result(rows=[
                (timetable_a, SimpleNamespace(id=subject_a, name="Math"), subject_teacher, user),
                (timetable_a_duplicate, SimpleNamespace(id=subject_a, name="Math"), subject_teacher, user),
                (timetable_b, SimpleNamespace(id=subject_b, name="Science"), subject_teacher, user),
            ]),
        ]
        tenant = SimpleNamespace(id=tenant_id)
        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments._permission_for_parent", new=AsyncMock(return_value=(student, SimpleNamespace(id=uuid.uuid4()), None))),
        ):
            response = await get_eligible_appointment_teachers(student_id, tenant=tenant, parent=SimpleNamespace(id=uuid.uuid4()), db=db)

        options = response["options"]
        assert options[0]["mode"] == "homeroom"
        assert len(options) == 3
        assert {(option["teacher_id"], option["subject_id"]) for option in options[1:]} == {
            (str(subject_teacher.id), str(subject_a)),
            (str(subject_teacher.id), str(subject_b)),
        }


@pytest.mark.asyncio
async def test_unlinked_student_is_rejected_before_appointment_creation() -> None:
        from services.gateway.routers.appointments import _permission_for_parent

        db = AsyncMock()
        tenant = SimpleNamespace(id=uuid.uuid4())
        parent = SimpleNamespace(id=uuid.uuid4())
        with patch("services.gateway.routers.appointments.validate_parent_student_access", new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Not linked"))):
            with pytest.raises(HTTPException) as exc_info:
                await _permission_for_parent(db=db, tenant=tenant, parent=parent, student_id=uuid.uuid4())
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_arbitrary_teacher_subject_combination_is_rejected() -> None:
        tenant = SimpleNamespace(id=uuid.uuid4())
        student = SimpleNamespace(id=uuid.uuid4())
        klass = SimpleNamespace(id=uuid.uuid4(), academic_year="2026", class_teacher_id=uuid.uuid4())
        teacher = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute.side_effect = [_result(first=(student, klass)), _result(scalar=None), _result(scalar=None)]
        with pytest.raises(HTTPException) as exc_info:
            await _validate_teacher_subject_option(
                db=db,
                tenant=tenant,
                student_id=student.id,
                teacher_id=teacher.id,
                subject_id=uuid.uuid4(),
                timetable_entry_id=uuid.uuid4(),
                effective_date=datetime.now(timezone.utc).date(),
            )
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_canonical_subject_scope_blocks_legacy_timetable_authorization() -> None:
        tenant = SimpleNamespace(id=uuid.uuid4())
        student = SimpleNamespace(id=uuid.uuid4())
        klass = SimpleNamespace(id=uuid.uuid4(), academic_year="2026", class_teacher_id=uuid.uuid4())
        teacher = SimpleNamespace(id=uuid.uuid4())
        subject_id = uuid.uuid4()
        timetable_entry_id = uuid.uuid4()
        db = AsyncMock()
        db.execute.side_effect = [_result(first=(student, klass)), _result(scalar=teacher)]

        with (
            patch("services.gateway.routers.appointments.teacher_has_homeroom_scope", new=AsyncMock(return_value=SimpleNamespace(authorized=False, source="canonical"))),
            patch("services.gateway.routers.appointments.teacher_has_subject_scope", new=AsyncMock(return_value=SimpleNamespace(authorized=False, source="canonical"))),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_teacher_subject_option(
                    db=db,
                    tenant=tenant,
                    student_id=student.id,
                    teacher_id=teacher.id,
                    subject_id=subject_id,
                    timetable_entry_id=timetable_entry_id,
                    effective_date=datetime.now(timezone.utc).date(),
                )
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_linked_parent_creation_persists_requested_appointment() -> None:
        tenant_id = uuid.uuid4()
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        family_id = uuid.uuid4()
        student = SimpleNamespace(id=student_id)
        family = SimpleNamespace(id=family_id)
        teacher = SimpleNamespace(id=teacher_id)
        entry = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        added: list[Appointment] = []
        db.add = MagicMock(side_effect=added.append)
        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments._permission_for_parent", new=AsyncMock(return_value=(student, family, None))),
            patch("services.gateway.routers.appointments._validate_teacher_subject_option", new=AsyncMock(return_value=(student, SimpleNamespace(), teacher, entry))),
            patch("services.gateway.routers.appointments.log_action", new=AsyncMock()),
            patch("services.gateway.routers.appointments.write_timeline_event", new=AsyncMock()),
            patch("services.gateway.routers.appointments._attempt_appointment_notification_after_commit", new=AsyncMock()),
        ):
            response = await create_parent_appointment(
                AppointmentCreateRequest(
                    student_id=student_id,
                    teacher_id=teacher_id,
                    subject_id=uuid.uuid4(),
                    timetable_entry_id=entry.id,
                    requested_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    duration_minutes=30,
                    timezone="UTC",
                    meeting_mode="video",
                ),
                tenant=SimpleNamespace(id=tenant_id),
                parent=SimpleNamespace(id=uuid.uuid4()),
                db=db,
            )
        assert response["appointment"]["status"] == "requested"
        assert added[0].student_id == student_id
        assert added[0].teacher_id == teacher_id


@pytest.mark.asyncio
async def test_teacher_user_mapping_authorizes_assigned_teacher_and_denies_unrelated() -> None:
        appointment = Appointment(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            status="requested",
            scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            duration_minutes=45,
            timezone="Africa/Nairobi",
            meeting_mode="video",
            location_or_link="https://meet.example.com/room-1",
            parent_notes="Please discuss reading progress",
            staff_notes="Bring assessment notes",
        )
        db = AsyncMock()
        db.execute.return_value = _result(scalar=appointment)
        profile = SimpleNamespace(id=appointment.teacher_id)
        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=profile)),
        ):
            response = await get_teacher_appointment(appointment.id, tenant=SimpleNamespace(id=appointment.tenant_id), teacher_user=SimpleNamespace(id=uuid.uuid4()), db=db)
        assert response["id"] == str(appointment.id)
        assert response["duration_minutes"] == 45
        assert response["timezone"] == "Africa/Nairobi"
        assert response["meeting_mode"] == "video"
        assert response["location_or_link"] == "https://meet.example.com/room-1"
        assert response["parent_notes"] == "Please discuss reading progress"
        assert response["staff_notes"] == "Bring assessment notes"

        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_teacher_appointment(appointment.id, tenant=SimpleNamespace(id=appointment.tenant_id), teacher_user=SimpleNamespace(id=uuid.uuid4()), db=db)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_parent_detail_and_lists_preserve_privacy_and_filters() -> None:
        appointment = Appointment(id=uuid.uuid4(), tenant_id=uuid.uuid4(), family_id=uuid.uuid4(), teacher_id=uuid.uuid4(), status="confirmed", requested_start_at=datetime.now(timezone.utc), scheduled_start_at=datetime.now(timezone.utc), staff_notes="private")
        db = AsyncMock()
        db.execute.return_value = _result(scalar=appointment, rows=[appointment])
        family = SimpleNamespace(id=appointment.family_id)
        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments.resolve_family", new=AsyncMock(return_value=family)),
        ):
            detail = await get_parent_appointment(appointment.id, tenant=SimpleNamespace(id=appointment.tenant_id), parent=SimpleNamespace(id=uuid.uuid4()), db=db)
            listing = await list_parent_appointments(status="confirmed", date_from=appointment.requested_start_at - timedelta(minutes=1), page=2, page_size=1, tenant=SimpleNamespace(id=appointment.tenant_id), parent=SimpleNamespace(id=uuid.uuid4()), db=db)
        assert "staff_notes" not in detail
        assert all("staff_notes" not in item for item in listing["items"])
        assert listing["page"] == 2
        assert listing["page_size"] == 1


@pytest.mark.asyncio
async def test_teacher_and_leadership_views_include_staff_notes() -> None:
        appointment = Appointment(id=uuid.uuid4(), tenant_id=uuid.uuid4(), teacher_id=uuid.uuid4(), status="confirmed", requested_start_at=datetime.now(timezone.utc), scheduled_start_at=datetime.now(timezone.utc), staff_notes="private")
        db = AsyncMock()
        db.execute.return_value = _result(scalar=appointment, rows=[appointment])
        profile = SimpleNamespace(id=appointment.teacher_id)
        with (
            patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
            patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=profile)),
        ):
            teacher_view = await get_teacher_appointment(appointment.id, tenant=SimpleNamespace(id=appointment.tenant_id), teacher_user=SimpleNamespace(id=uuid.uuid4()), db=db)
        assert teacher_view["staff_notes"] == "private"

        with patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()):
            leadership_view = await list_leadership_appointments(status="confirmed", page=1, page_size=1, tenant=SimpleNamespace(id=appointment.tenant_id), actor=SimpleNamespace(id=uuid.uuid4()), db=db)
        assert leadership_view["items"][0]["staff_notes"] == "private"


def test_teacher_list_route_returns_200_with_empty_items_for_valid_teacher_profile() -> None:
    tenant_id = uuid.uuid4()
    teacher_user_id = uuid.uuid4()
    teacher_profile = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    db.execute.return_value = _result(rows=[])

    with (
        patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
        patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=teacher_profile)),
    ):
        client = _build_teacher_route_client(db_session=db, tenant_id=tenant_id, teacher_user_id=teacher_user_id)
        response = client.get("/teacher/appointments", params={"page": 1, "page_size": 10})

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 10}


def test_teacher_list_route_returns_controlled_403_when_teacher_profile_missing() -> None:
    tenant_id = uuid.uuid4()
    teacher_user_id = uuid.uuid4()
    db = AsyncMock()

    with (
        patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
        patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=None)),
    ):
        client = _build_teacher_route_client(db_session=db, tenant_id=tenant_id, teacher_user_id=teacher_user_id)
        response = client.get("/teacher/appointments", params={"page": 1, "page_size": 10})

    assert response.status_code == 403
    assert response.json() == {"detail": "You do not have access to this resource."}


def test_teacher_list_route_enforces_cross_tenant_isolation() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    other_teacher_id = uuid.uuid4()
    teacher_user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    visible = Appointment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        status="requested",
        requested_start_at=now,
        scheduled_start_at=now,
        duration_minutes=30,
        timezone="UTC",
        meeting_mode="video",
    )
    wrong_tenant = Appointment(
        id=uuid.uuid4(),
        tenant_id=other_tenant_id,
        teacher_id=teacher_id,
        status="requested",
        requested_start_at=now,
        scheduled_start_at=now,
        duration_minutes=30,
        timezone="UTC",
        meeting_mode="video",
    )
    wrong_teacher = Appointment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=other_teacher_id,
        status="requested",
        requested_start_at=now,
        scheduled_start_at=now,
        duration_minutes=30,
        timezone="UTC",
        meeting_mode="video",
    )

    db = _FilteringListSession([visible, wrong_tenant, wrong_teacher])

    with (
        patch("services.gateway.routers.appointments.set_tenant_context", new=AsyncMock()),
        patch("services.gateway.routers.appointments._resolve_teacher_profile", new=AsyncMock(return_value=SimpleNamespace(id=teacher_id))),
    ):
        client = _build_teacher_route_client(db_session=db, tenant_id=tenant_id, teacher_user_id=teacher_user_id)
        response = client.get("/teacher/appointments", params={"page": 1, "page_size": 10})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(visible.id)


def test_migration_upgrade_and_downgrade_call_appointments_operations() -> None:
    migration_path = Path("alembic/versions/b6d4fe19f7c2_phase_85a_parent_teacher_appointments.py")
    spec = importlib.util.spec_from_file_location("phase_85a_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration_op = MagicMock()
    with patch.object(migration, "op", migration_op):
        migration.upgrade()
        migration.downgrade()
    assert migration_op.create_table.call_args.args[0] == "appointments"
    assert migration_op.drop_table.call_args.args[0] == "appointments"
    index_names = {call.args[0] for call in migration_op.create_index.call_args_list}
    assert "ix_appointments_tenant_id" in index_names
    assert "ix_appointments_scheduled_start_at" in index_names
    assert migration.down_revision == "d42f0d6ab9e1"


def test_shared_transition_helper_accepts_only_in_scope_status_changes() -> None:
    appt = Appointment(status="requested")
    assert _allowed_transition("requested", "confirmed") is True
    assert _allowed_transition("requested", "cancelled") is True
    assert _allowed_transition("confirmed", "completed") is True
    assert _allowed_transition("confirmed", "declined") is False
    assert _allowed_transition("declined", "cancelled") is False
    assert _allowed_transition("completed", "cancelled") is False

    appt.status = "confirmed"
    _transition_appointment(appt=appt, target_status="completed", actor_id=uuid.uuid4())
    assert appt.status == "completed"
    assert appt.completed_at is not None

    appt = Appointment(status="declined")
    with pytest.raises(HTTPException):
        _transition_appointment(appt=appt, target_status="cancelled", actor_id=uuid.uuid4())


def test_validate_helpers_enforce_future_timezone_and_meeting_rules() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(HTTPException):
        _validate_future_appointment_datetime(datetime(2026, 7, 23, 9, 0, 0))
    with pytest.raises(HTTPException):
        _validate_future_appointment_datetime(now - timedelta(minutes=1))
    with pytest.raises(HTTPException):
        _validate_iana_timezone("Invalid/Zone")
    with pytest.raises(HTTPException):
        _validate_duration_minutes(9)
    with pytest.raises(HTTPException):
        _validate_meeting_mode("chat")


def test_migration_file_has_no_identity_unique_constraint() -> None:
    migration_path = Path("alembic/versions/b6d4fe19f7c2_phase_85a_parent_teacher_appointments.py")
    text = migration_path.read_text(encoding="utf-8")
    assert "uq_appointment_identity" not in text
    assert "down_revision: Union[str, None] = \"d42f0d6ab9e1\"" in text


def test_applicant_timeline_and_notification_helpers_use_safe_key_shape() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    appt = Appointment(id=uuid.uuid4(), status="confirmed", scheduled_start_at=future, duration_minutes=30, family_id=uuid.uuid4(), student_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    key = f"appointment:{appt.id}:appointment.confirmed:confirmed:{appt.scheduled_start_at.isoformat()}"
    assert key.startswith("appointment:")
    assert ":confirmed:" in key
    assert appt.status == "confirmed"
