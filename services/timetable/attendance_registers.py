"""
Phase 10D-2: Attendance Register roster resolution service.

ensure_attendance_register(db, *, tenant_id, daily_session_id)
  → AttendanceRegister   on first call or same-roster re-call
  → raises AttendanceError on ineligible session, stale roster, or
    unresolved parallel membership

Effective-date semantics (half-open interval):
  Student is in the roster for session_date when:
    enrolled_on <= session_date
    AND (exited_on IS NULL OR session_date < exited_on)
    AND status = 'active'

Fingerprint inputs (deterministic, no runtime values):
  tenant_id, class_id (string), school_date, sorted [(student_id, enrollment_id)]
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date as date_type, datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.db.models import (
    AttendanceRecord,
    AttendanceRegister,
    AuditLog,
    DailySession,
    OperationalSchoolDay,
    StudentEnrollment,
    Teacher,
    User,
)


# ─────────────────────────────────────────────────────────────────────────────
# Controlled error type
# ─────────────────────────────────────────────────────────────────────────────

class AttendanceError(Exception):
    """
    Controlled error raised instead of HTTPException so the service layer
    stays framework-independent. Callers translate to HTTP status codes.

    code values:
      attendance_not_available_for_session  – session not eligible
      attendance_roster_stale               – roster changed after creation
      parallel_roster_membership_unresolved – parallel child, no group model
      session_not_found                     – no matching DailySession for tenant
    """
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_attendance_register(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    daily_session_id: uuid.UUID,
) -> AttendanceRegister:
    """
    Idempotent: create or return the AttendanceRegister for this session.

    First call   → creates register + unmarked AttendanceRecords.
    Re-call (same roster) → returns existing register unchanged.
    Re-call (roster changed) → marks existing as stale, raises attendance_roster_stale.
    """
    # ── 1. Load DailySession (tenant-scoped) ─────────────────────────────────
    session = await db.scalar(
        select(DailySession).where(
            DailySession.id == daily_session_id,
            DailySession.tenant_id == tenant_id,
        )
    )
    if session is None:
        raise AttendanceError("session_not_found")

    # ── 2. Session eligibility ────────────────────────────────────────────────
    if not session.is_active:
        raise AttendanceError(
            "attendance_not_available_for_session", "session_inactive"
        )
    if session.session_status == "cancelled":
        raise AttendanceError(
            "attendance_not_available_for_session", "session_cancelled"
        )
    if session.override_reason == "logical_period_unavailable":
        raise AttendanceError(
            "attendance_not_available_for_session", "logical_period_unavailable"
        )

    # ── 3. Operational school day must be a teaching day ─────────────────────
    osd = await db.scalar(
        select(OperationalSchoolDay).where(
            OperationalSchoolDay.id == session.operational_school_day_id,
            OperationalSchoolDay.tenant_id == tenant_id,
        )
    )
    if osd is None or not osd.is_teaching_day:
        raise AttendanceError(
            "attendance_not_available_for_session", "non_instructional_day"
        )

    # ── 4. Parallel membership guard ─────────────────────────────────────────
    # parallel_block_id set → this is a parallel child session.
    # No authoritative student-to-parallel-child membership model exists.
    # Do NOT assign the full class roster to each parallel child.
    if session.parallel_block_id is not None:
        raise AttendanceError("parallel_roster_membership_unresolved")

    # ── 5. class_facing_session_key must be materialized ─────────────────────
    class_facing_key = session.class_facing_session_key
    if class_facing_key is None:
        raise AttendanceError(
            "attendance_not_available_for_session", "session_key_not_materialized"
        )

    school_date = session.school_date

    # ── 6. Parse class_id (stored as String in DailySession) ─────────────────
    try:
        class_uuid = uuid.UUID(session.class_id)
    except (ValueError, AttributeError) as exc:
        raise AttendanceError(
            "attendance_not_available_for_session", "roster_class_id_invalid"
        ) from exc

    # ── 7. Resolve effective roster ───────────────────────────────────────────
    enrollments = await _resolve_effective_roster(
        db,
        tenant_id=tenant_id,
        class_id=class_uuid,
        school_date=school_date,
    )

    # ── 8. Compute deterministic fingerprint ──────────────────────────────────
    fingerprint = _compute_roster_fingerprint(
        tenant_id=tenant_id,
        class_id=session.class_id,
        school_date=school_date,
        enrollments=enrollments,
    )

    # ── 9. Idempotency check ──────────────────────────────────────────────────
    existing = await db.scalar(
        select(AttendanceRegister).where(
            AttendanceRegister.tenant_id == tenant_id,
            AttendanceRegister.operational_school_day_id == session.operational_school_day_id,
            AttendanceRegister.class_facing_session_key == class_facing_key,
        )
    )

    if existing is not None:
        if existing.roster_source_fingerprint == fingerprint:
            # Roster unchanged — return the existing register without mutation.
            return existing
        # Roster changed after creation: stale is a computed condition during
        # this read-only admission check. We do not mutate the register or any
        # records and we do not touch flush/add/commit.
        raise AttendanceError("attendance_roster_stale")

    # ── 10. Create register ───────────────────────────────────────────────────
    register = AttendanceRegister(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        operational_school_day_id=session.operational_school_day_id,
        class_facing_session_key=class_facing_key,
        class_id=session.class_id,
        school_date=school_date,
        register_status="open",
        roster_resolution_status="resolved",
        roster_source_fingerprint=fingerprint,
        expected_student_count=len(enrollments),
    )
    db.add(register)
    await db.flush()  # populate register.id before creating child records

    # ── 11. Create unmarked AttendanceRecords (one per effective student) ─────
    for student_id, enrollment_id in enrollments:
        db.add(
            AttendanceRecord(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                attendance_register_id=register.id,
                student_id=student_id,
                source_enrollment_id=enrollment_id,
                attendance_status="unmarked",
            )
        )

    await db.flush()
    return register


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_effective_roster(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    school_date: date_type,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """
    Return sorted (student_id, enrollment_id) for all students whose
    canonical StudentEnrollment is effective on school_date.

    Effective-date semantics (half-open):
        enrolled_on <= school_date
        AND (exited_on IS NULL OR school_date < exited_on)
        AND status = 'active'
        AND tenant_id = tenant_id
        AND class_id = class_id
    """
    stmt = (
        select(StudentEnrollment.student_id, StudentEnrollment.id)
        .where(
            StudentEnrollment.tenant_id == tenant_id,
            StudentEnrollment.class_id == class_id,
            StudentEnrollment.status == "active",
            StudentEnrollment.enrolled_on <= school_date,
            or_(
                StudentEnrollment.exited_on.is_(None),
                StudentEnrollment.exited_on > school_date,
            ),
        )
        .order_by(StudentEnrollment.student_id)
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


def _compute_roster_fingerprint(
    *,
    tenant_id: uuid.UUID,
    class_id: str,
    school_date: date_type,
    enrollments: list[tuple[uuid.UUID, uuid.UUID]],
) -> str:
    """
    SHA-256 fingerprint over the canonical effective-roster inputs.

    Inputs:
        tenant_id   – scope guard
        class_id    – the class string as stored in DailySession
        school_date – the session date (ISO string)
        enrollments – sorted list of [student_id_str, enrollment_id_str] pairs

    Excludes: current time, actor, random values, session_key.
    Same effective roster on the same date always produces the same hash.
    """
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "class_id": class_id,
            "school_date": school_date.isoformat(),
            "roster": sorted(
                [str(student_id), str(enrollment_id)]
                for student_id, enrollment_id in enrollments
            ),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 10D-2B marking / submission / finalization API surface
# ─────────────────────────────────────────────────────────────────────────────

VALID_ATTENDANCE_STATUSES = {"unmarked", "present", "absent", "late", "excused"}
LEADERSHIP_ROLES = {"principal", "school_admin"}


async def bulk_mark_attendance(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
    actor_id: uuid.UUID,
    marks: list[dict],
) -> AttendanceRegister:
    """
    Deterministic bulk marking.

    marks: list of dicts like {"student_id": ..., "status": ..., "minutes_late": ...}
    register must be open and actor must be authorized for the register.
    Every target student must already be in the register snapshot.
    """
    register = await _load_register(db, tenant_id=tenant_id, register_id=register_id)
    if register.register_status != "open":
        raise AttendanceError("attendance_register_not_open")
    if register.roster_resolution_status == "parallel_unresolved":
        raise AttendanceError("parallel_roster_membership_unresolved")

    await _authorize_attendance_actor(db, tenant_id=tenant_id, actor_id=actor_id, register=register)

    record_map = await _load_register_records(db, tenant_id=tenant_id, register_id=register.id)
    for mark in marks:
        if "student_id" not in mark:
            raise AttendanceError("attendance_unknown_student")
        student_id = mark["student_id"]
        if student_id not in record_map:
            raise AttendanceError("attendance_unknown_student")
        status = mark.get("status")
        if status not in VALID_ATTENDANCE_STATUSES:
            raise AttendanceError("attendance_status_unknown")
        if status != "late" and mark.get("minutes_late") is not None:
            raise AttendanceError("attendance_late_minutes_invalid")
        if status == "late":
            minutes = mark.get("minutes_late")
            if minutes is None:
                raise AttendanceError("attendance_late_minutes_invalid")
            if int(minutes) < 0:
                raise AttendanceError("attendance_late_minutes_invalid")
            record_map[student_id].minutes_late = int(minutes)
        else:
            record_map[student_id].minutes_late = None
        record_map[student_id].attendance_status = status
        record_map[student_id].marked_at = datetime.now(timezone.utc)
        record_map[student_id].marked_by = actor_id

    await db.flush()
    await log_action(
        db,
        tenant_id=tenant_id,
        action="attendance.bulk_marked",
        entity_type="AttendanceRegister",
        entity_id=register.id,
        actor_id=actor_id,
        details={
            "register_id": str(register.id),
            "count": len(marks),
            "statuses": [m.get("status") for m in marks],
        },
    )
    return register


async def mark_all_present(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> AttendanceRegister:
    """Safe semantics: only currently unmarked records change to present."""
    register = await _load_register(db, tenant_id=tenant_id, register_id=register_id)
    if register.register_status != "open":
        raise AttendanceError("attendance_register_not_open")
    if register.roster_resolution_status == "parallel_unresolved":
        raise AttendanceError("parallel_roster_membership_unresolved")

    await _authorize_attendance_actor(db, tenant_id=tenant_id, actor_id=actor_id, register=register)

    record_map = await _load_register_records(db, tenant_id=tenant_id, register_id=register.id)
    changed = False
    for record in record_map.values():
        if record.attendance_status == "unmarked":
            record.attendance_status = "present"
            record.minutes_late = None
            record.marked_at = datetime.now(timezone.utc)
            record.marked_by = actor_id
            changed = True

    if changed:
        await db.flush()
        await log_action(
            db,
            tenant_id=tenant_id,
            action="attendance.mark_all_present",
            entity_type="AttendanceRegister",
            entity_id=register.id,
            actor_id=actor_id,
            details={"register_id": str(register.id), "only_unmarked_to_present": True},
        )
    return register


async def submit_attendance_register(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> AttendanceRegister:
    """Submit only when all expected AttendanceRecords are marked."""
    register = await _load_register(db, tenant_id=tenant_id, register_id=register_id)
    if register.register_status != "open":
        raise AttendanceError("attendance_register_not_open")
    if register.roster_resolution_status == "parallel_unresolved":
        raise AttendanceError("parallel_roster_membership_unresolved")

    await _authorize_attendance_actor(db, tenant_id=tenant_id, actor_id=actor_id, register=register)

    record_map = await _load_register_records(db, tenant_id=tenant_id, register_id=register.id)
    unmarked = [r for r in record_map.values() if r.attendance_status == "unmarked"]
    if unmarked:
        raise AttendanceError(
            "attendance_incomplete",
            detail=f"{len(unmarked)} unmarked student records remain",
        )

    register.register_status = "submitted"
    register.submitted_at = datetime.now(timezone.utc)
    register.submitted_by = actor_id
    await db.flush()
    await log_action(
        db,
        tenant_id=tenant_id,
        action="attendance.submitted",
        entity_type="AttendanceRegister",
        entity_id=register.id,
        actor_id=actor_id,
        details={"register_id": str(register.id), "submitted": True},
    )
    return register


async def finalize_attendance_register(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> AttendanceRegister:
    """Leadership may finalize only a submitted register."""
    register = await _load_register(db, tenant_id=tenant_id, register_id=register_id)
    if register.register_status != "submitted":
        raise AttendanceError("attendance_register_not_submitted")
    if register.roster_resolution_status == "parallel_unresolved":
        raise AttendanceError("parallel_roster_membership_unresolved")

    if not await _authorize_leadership_actor(db, tenant_id=tenant_id, actor_id=actor_id):
        raise AttendanceError("attendance_authorization_denied")

    register.register_status = "finalized"
    register.finalized_at = datetime.now(timezone.utc)
    register.finalized_by = actor_id
    await db.flush()
    await log_action(
        db,
        tenant_id=tenant_id,
        action="attendance.finalized",
        entity_type="AttendanceRegister",
        entity_id=register.id,
        actor_id=actor_id,
        details={"register_id": str(register.id), "finalized": True},
    )
    return register


async def correct_attendance_register(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
    actor_id: uuid.UUID,
    student_id: uuid.UUID,
    new_status: str,
    correction_reason: str,
) -> AttendanceRecord:
    """Leadership correction after submission/finalization only."""
    if not correction_reason or not correction_reason.strip():
        raise AttendanceError("attendance_correction_reason_required")
    if new_status not in VALID_ATTENDANCE_STATUSES:
        raise AttendanceError("attendance_status_unknown")

    register = await _load_register(db, tenant_id=tenant_id, register_id=register_id)
    if register.register_status not in {"submitted", "finalized"}:
        raise AttendanceError("attendance_register_not_submit_or_finalized")
    if register.roster_resolution_status == "parallel_unresolved":
        raise AttendanceError("parallel_roster_membership_unresolved")

    if not await _authorize_leadership_actor(db, tenant_id=tenant_id, actor_id=actor_id):
        raise AttendanceError("attendance_authorization_denied")

    record_map = await _load_register_records(db, tenant_id=tenant_id, register_id=register.id)
    if student_id not in record_map:
        raise AttendanceError("attendance_unknown_student")

    record = record_map[student_id]
    before = record.attendance_status
    record.attendance_status = new_status
    if new_status != "late":
        record.minutes_late = None
    else:
        if record.minutes_late is None:
            record.minutes_late = 0
    record.marked_at = datetime.now(timezone.utc)
    record.marked_by = actor_id

    await db.flush()
    await log_action(
        db,
        tenant_id=tenant_id,
        action="attendance.corrected",
        entity_type="AttendanceRegister",
        entity_id=register.id,
        actor_id=actor_id,
        details={
            "register_id": str(register.id),
            "student_id": str(student_id),
            "before": before,
            "after": new_status,
            "reason": correction_reason.strip()[:200],
        },
    )
    return record


# ─────────────────────────────────────────────────────────────────────────────
# Internal authority helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _load_register(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
) -> AttendanceRegister:
    register = await db.scalar(
        select(AttendanceRegister).where(
            AttendanceRegister.id == register_id,
            AttendanceRegister.tenant_id == tenant_id,
        )
    )
    if register is None:
        raise AttendanceError("attendance_register_not_found")
    return register


async def _load_register_records(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
) -> dict[uuid.UUID, AttendanceRecord]:
    records = await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.attendance_register_id == register_id,
        )
    )
    rows = records.scalars().all()
    return {row.student_id: row for row in rows}


async def _authorize_attendance_actor(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    register: AttendanceRegister,
) -> None:
    actor = await db.scalar(
        select(User).where(
            User.id == actor_id,
            User.tenant_id == tenant_id,
        )
    )
    if actor is None:
        raise AttendanceError("attendance_authorization_denied")

    if actor.role in LEADERSHIP_ROLES:
        return

    if actor.role != "teacher":
        raise AttendanceError("attendance_authorization_denied")

    teacher = await db.scalar(
        select(Teacher).where(
            Teacher.tenant_id == tenant_id,
            Teacher.user_id == actor_id,
        )
    )
    if teacher is None:
        raise AttendanceError("attendance_authorization_denied")

    # Compare the actor's teacher user mapping against the DailySession teacher_id
    # stored in the source class-facing session. This is the scheduled teacher
    # guard for ordinary sessions; phase 10E may extend by substitute teacher ID.
    session_rows = await db.execute(
        select(DailySession).where(
            DailySession.tenant_id == tenant_id,
            DailySession.operational_school_day_id == register.operational_school_day_id,
            DailySession.class_facing_session_key == register.class_facing_session_key,
        )
    )
    sessions = session_rows.scalars().all()
    if not sessions:
        raise AttendanceError("attendance_authorization_denied")

    teacher_id_matches = [
        True for s in sessions if s.teacher_id is not None and str(s.teacher_id) == str(teacher.id)
    ]
    if not teacher_id_matches:
        raise AttendanceError("attendance_authorization_denied")


async def _authorize_leadership_actor(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> bool:
    actor = await db.scalar(
        select(User).where(
            User.id == actor_id,
            User.tenant_id == tenant_id,
        )
    )
    if actor is None:
        return False
    return actor.role in LEADERSHIP_ROLES
