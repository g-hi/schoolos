"""Phase 10D - Operational Daily Sessions API."""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.timetable_setup.daily_sessions import (
    DailySessionError,
    MaterializationOutcome,
    load_operational_day_with_sessions,
    materialize_operational_day,
    operational_day_to_dict,
    session_to_dict,
)
from services.timetable.attendance_registers import (
    AttendanceError,
    AttendanceRecord,
    AttendanceRegister,
    bulk_mark_attendance,
    correct_attendance_register,
    ensure_attendance_register,
    finalize_attendance_register,
    mark_all_present,
    submit_attendance_register,
)
from shared.auth.dependencies import resolve_authenticated_leadership, resolve_authenticated_teacher
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import Class, DailySession, GradeLevel, OperationalSchoolDay, Student, Subject, Teacher, Tenant, User


router = APIRouter(prefix="/leadership/operations/daily-sessions", tags=["Daily Sessions"])
teacher_router = APIRouter(prefix="/teacher/operations/attendance", tags=["Teacher Attendance"])
leadership_router = APIRouter(prefix="/leadership/operations/attendance", tags=["Leadership Attendance"])


def _ensure_principal(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if actor.role != "principal":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only principals can access daily session operations.",
        )


def _ensure_teacher(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if actor.role != "teacher":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only teachers can access teacher attendance operations.",
        )


def _map_attendance_error(exc: AttendanceError) -> tuple[int, dict]:
    code = exc.code
    if code == "attendance_authorization_denied":
        return http_status.HTTP_403_FORBIDDEN, {"code": code, "message": "You are not authorized for this attendance operation."}
    if code in {"attendance_register_not_found", "session_not_found"}:
        return http_status.HTTP_404_NOT_FOUND, {"code": code, "message": "The requested attendance resource was not found."}
    if code in {"attendance_register_not_open", "attendance_register_not_submitted", "attendance_register_not_submit_or_finalized", "attendance_incomplete"}:
        return http_status.HTTP_409_CONFLICT, {"code": code, "message": exc.detail or code}
    if code in {"attendance_not_available_for_session", "attendance_roster_stale", "parallel_roster_membership_unresolved"}:
        return http_status.HTTP_409_CONFLICT, {"code": code, "message": exc.detail or code}
    if code in {"attendance_unknown_student"}:
        return http_status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": code, "message": exc.detail or code}
    if code in {"attendance_status_unknown", "attendance_late_minutes_invalid", "attendance_correction_reason_required"}:
        return http_status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": code, "message": exc.detail or code}
    return http_status.HTTP_400_BAD_REQUEST, {"code": code, "message": exc.detail or code}


async def _resolve_teacher_profile(*, db: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> Teacher | None:
    return await db.scalar(select(Teacher).where(Teacher.tenant_id == tenant_id, Teacher.user_id == actor_id))


async def teacher_attendance_view_for_date(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    school_date: date_type,
) -> list[dict]:
    """Read-only teacher-facing attendance roster list for a tenant date."""
    teacher = await _resolve_teacher_profile(db=db, tenant_id=tenant_id, actor_id=actor_id)
    if teacher is None:
        raise AttendanceError("attendance_authorization_denied")

    rows = await db.execute(
        select(DailySession)
        .where(
            DailySession.tenant_id == tenant_id,
            DailySession.school_date == school_date,
            DailySession.teacher_id == str(teacher.id),
        )
    )
    sessions = rows.scalars().all()

    class_ids = {session.class_id for session in sessions if session.class_id}
    subject_ids = {session.subject_id for session in sessions if session.subject_id}
    class_rows = await db.execute(
        select(Class, GradeLevel)
        .outerjoin(GradeLevel, GradeLevel.id == Class.grade_level_id)
        .where(Class.tenant_id == tenant_id, Class.id.in_(class_ids))
    ) if class_ids else None
    subject_rows = await db.execute(
        select(Subject)
        .where(Subject.tenant_id == tenant_id, Subject.id.in_(subject_ids))
    ) if subject_ids else None
    class_metadata: dict[object, dict[str, str | None]] = {}
    subject_metadata: dict[object, str] = {}
    if class_rows is not None:
        for klass, grade_level in class_rows.all():
            class_metadata[str(klass.id)] = {
                "class_code": klass.code,
                "grade_level": grade_level.name if grade_level else klass.grade,
                "section": klass.section,
            }
    if subject_rows is not None:
        for subject in subject_rows.scalars().all():
            subject_metadata[str(subject.id)] = subject.name

    # Deduplicate on class_facing_session_key because parallel children or multi-
    # period materializations may surface multiple DailySession rows for one class-facing slot.
    seen_keys: set[str] = set()
    payload = []
    for session in sessions:
        key = session.class_facing_session_key or session.session_key
        if key in seen_keys:
            continue
        seen_keys.add(key)

        class_info = class_metadata.get(str(session.class_id), {})
        grade_level = class_info.get("grade_level")
        section = class_info.get("section")
        class_display_name = " ".join(part for part in (grade_level, section) if part) or "Class"

        if session.parallel_block_id is not None:
            status = "parallel_unresolved"
            eligible = False
        else:
            eligible = bool(
                session.is_active
                and session.session_status != "cancelled"
                and session.override_reason != "logical_period_unavailable"
            )
            status = "unavailable" if not eligible else "not_started"

        register = await db.scalar(
            select(AttendanceRegister).where(
                AttendanceRegister.tenant_id == tenant_id,
                AttendanceRegister.operational_school_day_id == session.operational_school_day_id,
                AttendanceRegister.class_facing_session_key == session.class_facing_session_key,
            )
        )
        if register is not None:
            status = {
                "open": "open",
                "submitted": "submitted",
                "finalized": "finalized",
            }.get(register.register_status, "not_started")
            if register.roster_resolution_status == "parallel_unresolved":
                status = "parallel_unresolved"
            record_rows = await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.attendance_register_id == register.id,
                )
            )
            records = record_rows.scalars().all()
            expected_count = register.expected_student_count or len(records)
            marked_count = sum(1 for r in records if r.attendance_status != "unmarked")
            unmarked_count = sum(1 for r in records if r.attendance_status == "unmarked")
            if register.register_status == "open" and marked_count and marked_count < expected_count:
                status = "incomplete"
        else:
            expected_count = 0
            marked_count = 0
            unmarked_count = 0

        payload.append(
            {
                "daily_session_id": str(session.id),
                "class_facing_session_key": session.class_facing_session_key,
                "school_date": school_date.isoformat(),
                "class_id": session.class_id,
                "subject_id": session.subject_id,
                "class_code": class_info.get("class_code"),
                "grade_level": grade_level,
                "section": section,
                "class_display_name": class_display_name,
                "subject_name": subject_metadata.get(str(session.subject_id)) if session.subject_id else None,
                "teacher_id": session.teacher_id,
                "start_time": session.period_start_time,
                "end_time": session.period_end_time,
                "session_status": session.session_status,
                "attendance_eligible": eligible,
                "attendance_register_id": str(register.id) if register else None,
                "attendance_status": status,
                "expected_count": expected_count,
                "marked_count": marked_count,
                "unmarked_count": unmarked_count,
            }
        )

    return payload


async def teacher_attendance_register_detail(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    register_id: uuid.UUID,
) -> dict:
    """Read-only teacher detail view of a single register."""
    register = await db.scalar(
        select(AttendanceRegister).where(
            AttendanceRegister.id == register_id,
            AttendanceRegister.tenant_id == tenant_id,
        )
    )
    if register is None:
        raise AttendanceError("attendance_register_not_found")

    teacher = await _resolve_teacher_profile(db=db, tenant_id=tenant_id, actor_id=actor_id)
    if teacher is None:
        raise AttendanceError("attendance_authorization_denied")

    record_rows = await db.execute(
        select(AttendanceRecord)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.attendance_register_id == register.id,
        )
    )
    records = []
    for row in record_rows.scalars().all():
        student = await db.scalar(select(Student).where(Student.id == row.student_id, Student.tenant_id == tenant_id))
        records.append(
            {
                "student_id": str(row.student_id),
                "student_name": getattr(student, "name", None) or getattr(student, "display_name", None) or str(row.student_id),
                "student_identifier": student.student_code if student else None,
                "attendance_status": row.attendance_status,
                "minutes_late": row.minutes_late,
                "marked_at": row.marked_at.isoformat() if row.marked_at else None,
            }
        )

    return {
        "register_id": str(register.id),
        "class_facing_session_key": register.class_facing_session_key,
        "school_date": register.school_date.isoformat(),
        "register_status": register.register_status,
        "roster_resolution_status": register.roster_resolution_status,
        "expected_count": register.expected_student_count,
        "marked_count": sum(1 for r in records if r["attendance_status"] != "unmarked"),
        "unmarked_count": sum(1 for r in records if r["attendance_status"] == "unmarked"),
        "records": records,
    }


async def leadership_daily_attendance_summary(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    school_date: date_type,
) -> dict:
    """Leadership-only deterministic daily summary read model."""
    rows = await db.execute(
        select(DailySession)
        .where(
            DailySession.tenant_id == tenant_id,
            DailySession.school_date == school_date,
        )
    )
    sessions = rows.scalars().all()
    seen_keys: set[str] = set()
    eligible = 0
    not_started = 0
    open_count = 0
    submitted = 0
    finalized = 0
    parallel = 0
    expected_students = 0
    present = 0
    absent = 0
    late = 0
    excused = 0
    unmarked = 0

    for session in sessions:
        key = session.class_facing_session_key or session.session_key
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if session.parallel_block_id is not None:
            parallel += 1
            continue

        if session.is_active and session.session_status != "cancelled" and session.override_reason != "logical_period_unavailable":
            eligible += 1

        register = await db.scalar(
            select(AttendanceRegister).where(
                AttendanceRegister.tenant_id == tenant_id,
                AttendanceRegister.operational_school_day_id == session.operational_school_day_id,
                AttendanceRegister.class_facing_session_key == session.class_facing_session_key,
            )
        )
        if register is None:
            if session.is_active and session.session_status != "cancelled" and session.override_reason != "logical_period_unavailable":
                not_started += 1
            continue

        if register.roster_resolution_status == "parallel_unresolved":
            parallel += 1
            continue

        expected_students += register.expected_student_count or 0
        record_rows = await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.attendance_register_id == register.id,
            )
        )
        records = record_rows.scalars().all()
        if register.register_status == "open":
            open_count += 1
        elif register.register_status == "submitted":
            submitted += 1
        elif register.register_status == "finalized":
            finalized += 1

        for row in records:
            if row.attendance_status == "present":
                present += 1
            elif row.attendance_status == "absent":
                absent += 1
            elif row.attendance_status == "late":
                late += 1
            elif row.attendance_status == "excused":
                excused += 1
            elif row.attendance_status == "unmarked":
                unmarked += 1

    return {
        "school_date": school_date.isoformat(),
        "eligible_sessions": eligible,
        "not_started": not_started,
        "open": open_count,
        "submitted": submitted,
        "finalized": finalized,
        "parallel_unresolved": parallel,
        "expected_students": expected_students,
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "unmarked": unmarked,
    }


async def leadership_attendance_register_list(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    school_date: date_type,
) -> list[dict]:
    rows = await db.execute(
        select(AttendanceRegister).where(
            AttendanceRegister.tenant_id == tenant_id,
            AttendanceRegister.school_date == school_date,
        )
    )
    registers = rows.scalars().all()

    if not registers:
        return []

    class_ids = {
    register.class_id
    for register in registers
    if register.class_id
                 }
    session_keys = {
        register.class_facing_session_key
        for register in registers
        if register.class_facing_session_key
    }

    # Resolve the class-facing session so leadership sees useful operational
    # metadata instead of raw IDs.
    session_rows = await db.execute(
        select(DailySession).where(
            DailySession.tenant_id == tenant_id,
            DailySession.school_date == school_date,
            DailySession.class_facing_session_key.in_(session_keys),
        )
    ) if session_keys else None

    sessions_by_key: dict[str, DailySession] = {}
    if session_rows is not None:
        for session in session_rows.scalars().all():
            key = session.class_facing_session_key or session.session_key
            if key and key not in sessions_by_key:
                sessions_by_key[key] = session

    resolved_class_ids = set(class_ids)
    subject_ids = set()
    teacher_ids = set()

    for session in sessions_by_key.values():
        if session.class_id:
            resolved_class_ids.add(session.class_id)
        if session.subject_id:
            subject_ids.add(session.subject_id)
        if session.teacher_id:
            teacher_ids.add(session.teacher_id)

    class_rows = await db.execute(
        select(Class, GradeLevel)
        .outerjoin(GradeLevel, GradeLevel.id == Class.grade_level_id)
        .where(
            Class.tenant_id == tenant_id,
            Class.id.in_(resolved_class_ids),
        )
    ) if resolved_class_ids else None

    class_metadata: dict[str, dict[str, str | None]] = {}
    if class_rows is not None:
        for klass, grade_level in class_rows.all():
            class_metadata[str(klass.id)] = {
                "class_code": klass.code,
                "grade_level": grade_level.name if grade_level else klass.grade,
                "section": klass.section,
            }

    subject_rows = await db.execute(
        select(Subject).where(
            Subject.tenant_id == tenant_id,
            Subject.id.in_(subject_ids),
        )
    ) if subject_ids else None

    subject_metadata: dict[str, str] = {}
    if subject_rows is not None:
        for subject in subject_rows.scalars().all():
            subject_metadata[str(subject.id)] = subject.name


    teacher_rows = await db.execute(
        select(Teacher).where(
            Teacher.tenant_id == tenant_id,
            Teacher.id.in_(teacher_ids),
     )
    ) if teacher_ids else None

    teacher_metadata: dict[str, str] = {}
    if teacher_rows is not None:
        for teacher in teacher_rows.scalars().all():
            teacher_metadata[str(teacher.id)] = (
                teacher.user.name
                if getattr(teacher, "user", None) is not None
                else str(teacher.id)
            )
    payload = []

    for register in registers:
        record_rows = await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.attendance_register_id == register.id,
            )
        )
        records = record_rows.scalars().all()

        session = sessions_by_key.get(register.class_facing_session_key)
        class_id = str(register.class_id)
        if session is not None and session.class_id:
            class_id = str(session.class_id)

        class_info = class_metadata.get(class_id, {})
        grade_level = class_info.get("grade_level")
        section = class_info.get("section")
        class_display_name = (
            " ".join(part for part in (grade_level, section) if part)
            or class_info.get("class_code")
            or "Class"
        )

        payload.append(
            {
                "register_id": str(register.id),
                "class_id": register.class_id,
                "class_facing_session_key": register.class_facing_session_key,
                "class_code": class_info.get("class_code"),
                "grade_level": grade_level,
                "section": section,
                "class_display_name": class_display_name,
                "subject_name": (
                    subject_metadata.get(str(session.subject_id))
                    if session is not None and session.subject_id
                    else None
                ),
                "teacher_name": (
                    teacher_metadata.get(str(session.teacher_id))
                    if session is not None and session.teacher_id
                    else None
                ),
                "start_time": session.period_start_time if session is not None else None,
                "end_time": session.period_end_time if session is not None else None,
                "status": register.register_status,
                "roster_resolution_status": register.roster_resolution_status,
                "expected": register.expected_student_count,
                "marked": sum(
                    1 for record in records
                    if record.attendance_status != "unmarked"
                ),
                "unmarked": sum(
                    1 for record in records
                    if record.attendance_status == "unmarked"
                ),
                "present": sum(
                    1 for record in records
                    if record.attendance_status == "present"
                ),
                "absent": sum(
                    1 for record in records
                    if record.attendance_status == "absent"
                ),
                "late": sum(
                    1 for record in records
                    if record.attendance_status == "late"
                ),
                "excused": sum(
                    1 for record in records
                    if record.attendance_status == "excused"
                ),
            }
        )

    return payload


async def leadership_attendance_register_detail(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    register_id: uuid.UUID,
) -> dict:
    register = await db.scalar(
        select(AttendanceRegister).where(
            AttendanceRegister.id == register_id,
            AttendanceRegister.tenant_id == tenant_id,
        )
    )
    if register is None:
        raise AttendanceError("attendance_register_not_found")

    record_rows = await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.attendance_register_id == register.id,
        )
    )
    attendance_records = record_rows.scalars().all()

    student_ids = {
        record.student_id
        for record in attendance_records
        if record.student_id
    }

    student_rows = await db.execute(
        select(Student).where(
            Student.tenant_id == tenant_id,
            Student.id.in_(student_ids),
        )
    ) if student_ids else None

    students_by_id: dict[uuid.UUID, Student] = {}
    if student_rows is not None:
        students_by_id = {
            student.id: student
            for student in student_rows.scalars().all()
        }

    records = []

    for record in attendance_records:
        student = students_by_id.get(record.student_id)

        records.append(
            {
                "student_id": str(record.student_id),
                "student_name": (
                    student.name
                    if student is not None
                    else str(record.student_id)
                ),
                "student_identifier": (
                    student.student_code
                    if student is not None
                    else None
                ),
                "status": record.attendance_status,
                "minutes_late": record.minutes_late,
                "marked_by": (
                    str(record.marked_by)
                    if record.marked_by
                    else None
                ),
                "marked_at": (
                    record.marked_at.isoformat()
                    if record.marked_at
                    else None
                ),
            }
        )

    return {
        "register_id": str(register.id),
        "school_date": register.school_date.isoformat(),
        "class_id": register.class_id,
        "class_facing_session_key": register.class_facing_session_key,
        "register_status": register.register_status,
        "roster_resolution_status": register.roster_resolution_status,
        "expected_count": register.expected_student_count,
        "marked_count": sum(
            1 for record in records
            if record["status"] != "unmarked"
        ),
        "unmarked_count": sum(
            1 for record in records
            if record["status"] == "unmarked"
        ),
        "records": records,
    }


class MaterializeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timetable_id: uuid.UUID = Field(
        ...,
        description=(
            "UUID of the Timetable (scope entity). The effective published version "
            "for the target date is resolved automatically."
        ),
    )
    school_date: date_type = Field(..., description="Calendar date to materialize (YYYY-MM-DD).")


@router.post("/materialize", status_code=http_status.HTTP_200_OK)
async def materialize_daily_sessions(
    body: MaterializeRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Materialize OperationalSchoolDay and DailySession records for a specific date.

    The effective published timetable version is selected automatically by date
    using Phase 10C effective-version semantics. The caller provides the Timetable
    scope, not a specific version.

    Immutability contract:
    - First call: creates snapshot; returns status="created".
    - Same canonical inputs: returns existing snapshot; status="already_materialized".
    - Changed canonical inputs: returns 409 code="school_day_stale".
    """
    _ensure_principal(actor, tenant)
    await set_tenant_context(db, tenant.id)

    try:
        outcome: MaterializationOutcome = await materialize_operational_day(
            db,
            tenant_id=tenant.id,
            timetable_id=body.timetable_id,
            school_date=body.school_date,
        )
    except DailySessionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )

    if outcome.status == "created":
        await log_action(
            db,
            tenant_id=tenant.id,
            user_id=actor.id,
            action="materialize_daily_sessions",
            entity_type="operational_school_day",
            entity_id=str(outcome.osd.id),
            details={
                "timetable_id": str(body.timetable_id),
                "timetable_version_id": str(outcome.osd.timetable_version_id),
                "school_date": body.school_date.isoformat(),
                "session_count": outcome.session_count,
            },
        )

    response = operational_day_to_dict(outcome.osd, session_count=outcome.session_count)
    response["status"] = outcome.status
    return response


@router.get("", status_code=http_status.HTTP_200_OK)
async def get_daily_sessions(
    timetable_id: uuid.UUID = Query(..., description="UUID of the Timetable (scope entity)."),
    school_date: date_type = Query(..., description="Calendar date (YYYY-MM-DD)."),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retrieve the materialized OperationalSchoolDay and DailySession list.

    Returns 404 when the day has not yet been materialized.
    """
    _ensure_principal(actor, tenant)
    await set_tenant_context(db, tenant.id)

    result = await load_operational_day_with_sessions(
        db,
        tenant_id=tenant.id,
        timetable_id=timetable_id,
        school_date=school_date,
    )
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "code": "operational_day_not_found",
                "message": (
                    f"No materialized daily sessions found for timetable "
                    f"{timetable_id} on {school_date.isoformat()}. "
                    "Call POST /materialize to generate them."
                ),
            },
        )

    osd, sessions = result
    return {
        "operational_school_day": operational_day_to_dict(osd, session_count=len(sessions)),
        "sessions": [session_to_dict(s) for s in sessions],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Teacher Attendance API surface
# ─────────────────────────────────────────────────────────────────────────────

@teacher_router.get("/today", summary="Teacher attendance sessions for today")
async def get_teacher_attendance_today(
    school_date: date_type | None = Query(None, description="requested date (YYYY-MM-DD)"),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Teacher read-only list, defaulting to the current local date when omitted."""
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    ref_date = school_date or datetime.now().date()
    items = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant.id,
        actor_id=actor.id,
        school_date=ref_date,
    )
    return {"school_date": ref_date.isoformat(), "items": items}


@teacher_router.get("/sessions", summary="Teacher attendance sessions for a requested date")
async def get_teacher_attendance_sessions(
    school_date: date_type = Query(..., description="requested date (YYYY-MM-DD)"),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Teacher read-only list for a requested operational date."""
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    items = await teacher_attendance_view_for_date(
        db,
        tenant_id=tenant.id,
        actor_id=actor.id,
        school_date=school_date,
    )
    return {"school_date": school_date.isoformat(), "items": items}


@teacher_router.post("/registers/ensure", summary="Ensure an attendance register for a teacher session")
async def teacher_ensure_register(
    body: dict,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    daily_session_id = body.get("daily_session_id") if isinstance(body, dict) else body.daily_session_id
    try:
        register = await ensure_attendance_register(
            db,
            tenant_id=tenant.id,
            daily_session_id=uuid.UUID(str(daily_session_id)),
        )
        return {"register_id": str(register.id), "register_status": register.register_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@teacher_router.get("/registers/{register_id}", summary="Teacher register detail")
async def teacher_register_detail(
    register_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    try:
        return await teacher_attendance_register_detail(
            db,
            tenant_id=tenant.id,
            actor_id=actor.id,
            register_id=register_id,
        )
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@teacher_router.post("/registers/{register_id}/bulk-mark", summary="Bulk mark attendance")
async def teacher_bulk_mark(
    register_id: uuid.UUID,
    body: dict,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    try:
        register = await bulk_mark_attendance(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
            actor_id=actor.id,
            marks=body.get("marks", []) if isinstance(body, dict) else body.marks,
        )
        return {"register_id": str(register.id), "register_status": register.register_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@teacher_router.post("/registers/{register_id}/mark-all-present", summary="Mark all present")
async def teacher_mark_all_present(
    register_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    try:
        register = await mark_all_present(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
            actor_id=actor.id,
        )
        return {"register_id": str(register.id), "register_status": register.register_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@teacher_router.post("/registers/{register_id}/submit", summary="Submit attendance register")
async def teacher_submit(
    register_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_teacher),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_teacher(actor, tenant)
    try:
        register = await submit_attendance_register(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
            actor_id=actor.id,
        )
        return {"register_id": str(register.id), "register_status": register.register_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


# ─────────────────────────────────────────────────────────────────────────────
# Leadership Attendance API surface
# ─────────────────────────────────────────────────────────────────────────────

@leadership_router.get("/daily-summary", summary="Leadership daily attendance summary")
async def get_leadership_daily_attendance_summary(
    school_date: date_type = Query(..., description="Date to summarize"),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await set_tenant_context(db, tenant.id)
    _ensure_principal(actor, tenant)
    return await leadership_daily_attendance_summary(
        db,
        tenant_id=tenant.id,
        school_date=school_date,
    )


@leadership_router.get("/registers", summary="Leadership register inventory for a date")
async def get_leadership_attendance_registers(
    school_date: date_type = Query(..., description="Date to summarize"),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await set_tenant_context(db, tenant.id)
    _ensure_principal(actor, tenant)
    return await leadership_attendance_register_list(
        db,
        tenant_id=tenant.id,
        school_date=school_date,
    )


@leadership_router.get("/registers/{register_id}", summary="Leadership register detail")
async def get_leadership_attendance_register_detail(
    register_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await set_tenant_context(db, tenant.id)
    _ensure_principal(actor, tenant)
    try:
        return await leadership_attendance_register_detail(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
        )
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@leadership_router.post("/registers/{register_id}/finalize", summary="Finalize attendance register")
async def leadership_finalize(
    register_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_principal(actor, tenant)
    try:
        register = await finalize_attendance_register(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
            actor_id=actor.id,
        )
        return {"register_id": str(register.id), "register_status": register.register_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)


@leadership_router.post("/registers/{register_id}/correct", summary="Correct a submitted/finalized attendance register")
async def leadership_correction(
    register_id: uuid.UUID,
    body: dict,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    _ensure_principal(actor, tenant)
    try:
        record = await correct_attendance_register(
            db,
            tenant_id=tenant.id,
            register_id=register_id,
            actor_id=actor.id,
            student_id=body.get("student_id") if isinstance(body, dict) else body.student_id,
            new_status=body.get("new_status") if isinstance(body, dict) else body.new_status,
            correction_reason=body.get("correction_reason") if isinstance(body, dict) else body.correction_reason,
        )
        return {"student_id": str(record.student_id), "attendance_status": record.attendance_status}
    except AttendanceError as exc:
        code, payload = _map_attendance_error(exc)
        raise HTTPException(status_code=code, detail=payload)
