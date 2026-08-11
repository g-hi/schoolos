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
from datetime import date as date_type

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    AttendanceRecord,
    AttendanceRegister,
    DailySession,
    OperationalSchoolDay,
    StudentEnrollment,
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
