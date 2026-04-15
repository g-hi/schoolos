"""
Phase 3 – Substitution Router
==============================
Handles teacher absences and automatic substitute assignment.

Endpoints
---------
POST /substitution/report   – report absent teachers, get back a substitution plan
GET  /substitution/         – list substitutions for a date (admin record view)

HOW THE SUBSTITUTION ALGORITHM WORKS
──────────────────────────────────────
1. Receive: date + list of absent teacher names + academic_year.
2. Detect day_of_week from date.
3. For each absent teacher → find their timetable slots for that day.
4. For each slot → find the best available substitute:
     Priority 1: qualified for the same subject AND not busy AND within limits
     Priority 2: any free teacher (not subject-matched) AND within limits
5. Limits that disqualify a teacher from substituting:
     a. Already teaching a lesson in the same period on that day (timetable)
     b. Already assigned as substitute in that period on that date
     c. Their weekly regular sessions >= max_weekly_hours (fully booked teacher)
     d. Their substitutions this week >= max_substitutions_per_week
6. Save each result as a Substitution row.
7. Email assigned substitute teachers via SendGrid.
8. Schedule a 5-min-before SMS reminder for each.
"""

import asyncio
import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    Student,
    StudentParent,
    Subject,
    Substitution,
    Teacher,
    TeacherSubject,
    Tenant,
    TimetableEntry,
    User,
)

router = APIRouter(prefix="/substitution", tags=["Substitution"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class ReportAbsentRequest(BaseModel):
    date: str                           # "YYYY-MM-DD" e.g. "2025-04-14"
    absent_teachers: list[str]          # full names e.g. ["John Smith", "Sara Jones"]
    academic_year: str = "2025-2026"


# ─────────────────────────────────────────────────────────────────────────────
# POST /substitution/report
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/report", summary="Report absent teachers and get substitution plan")
async def report_absent(
    body: ReportAbsentRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    The admin reports who is absent today. The system:
    1. Finds their timetable slots for that day.
    2. Assigns the best available substitute for each slot.
    3. Sends SMS to the assigned substitutes.
    4. Schedules a 5-min SMS reminder for each.
    5. Returns a full substitution plan for the admin to review.

    Example request:
        {
          "date": "2025-04-14",
          "absent_teachers": ["John Smith", "Sara Jones"],
          "academic_year": "2025-2026"
        }
    """
    await set_tenant_context(db, tenant.id)

    # Validate date
    try:
        report_date = date_type.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    day_of_week = report_date.weekday()   # 0=Monday … 4=Friday
    if day_of_week > 4:
        raise HTTPException(status_code=400, detail="Cannot report absences on weekends.")

    # Week range for counting substitutions this week
    week_start = report_date - timedelta(days=day_of_week)
    week_end   = week_start + timedelta(days=6)

    results = []

    for teacher_name in body.absent_teachers:
        # ── Resolve name → teacher record ────────────────────────────────────
        user_q = await db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                func.lower(User.name) == teacher_name.strip().lower(),
            )
        )
        user = user_q.scalar_one_or_none()

        if not user:
            results.append({
                "absent_teacher": teacher_name,
                "error": f"Teacher '{teacher_name}' not found in the system.",
                "slots": [],
            })
            continue

        teacher_q = await db.execute(
            select(Teacher)
            .where(Teacher.tenant_id == tenant.id, Teacher.user_id == user.id)
        )
        absent_teacher = teacher_q.scalar_one_or_none()

        if not absent_teacher:
            results.append({
                "absent_teacher": teacher_name,
                "error": f"'{teacher_name}' is not registered as a teacher.",
                "slots": [],
            })
            continue

        # ── Find their timetable slots for this day ───────────────────────────
        entries_q = await db.execute(
            select(TimetableEntry)
            .where(
                TimetableEntry.tenant_id == tenant.id,
                TimetableEntry.teacher_id == absent_teacher.id,
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.academic_year == body.academic_year,
                TimetableEntry.is_active.is_(True),
            )
            .options(
                selectinload(TimetableEntry.period),
                selectinload(TimetableEntry.klass),
                selectinload(TimetableEntry.subject),
            )
        )
        entries = entries_q.scalars().all()

        if not entries:
            results.append({
                "absent_teacher": teacher_name,
                "error": None,
                "slots": [],
                "note": f"No timetable slots found for {teacher_name} on {body.date}.",
            })
            continue

        # ── For each slot, find a substitute ─────────────────────────────────
        slot_results = []

        for entry in entries:
            substitute, reason, confidence, confidence_reasons = await _find_substitute(
                db, tenant, entry, absent_teacher.id,
                body.date, body.academic_year,
                week_start, week_end,
            )

            # Save substitution record
            sub_status = "assigned" if substitute else "no_substitute_found"
            substitution = Substitution(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                date=report_date,
                academic_year=body.academic_year,
                timetable_entry_id=entry.id,
                absent_teacher_id=absent_teacher.id,
                substitute_teacher_id=substitute.id if substitute else None,
                status=sub_status,
                email_sent=False,
                reminder_sent=False,
                confidence_score=confidence if substitute else None,
                confidence_reasons=confidence_reasons if substitute else None,
            )
            db.add(substitution)
            await db.flush()   # get the substitution.id without committing

            # ── Audit trail ──────────────────────────────────────────────────
            await log_action(
                db=db,
                tenant_id=tenant.id,
                action=f"substitution.{sub_status}",
                entity_type="Substitution",
                entity_id=substitution.id,
                details={
                    "absent_teacher": teacher_name,
                    "substitute": substitute.user.name if substitute and substitute.user else None,
                    "date": body.date,
                    "period": entry.period.name,
                    "class": f"{entry.klass.grade} {entry.klass.section}",
                    "subject": entry.subject.name,
                },
            )

            email_sent = False
            sms_sent = False
            reminder_scheduled = False
            parents_notified = 0
            sub_user = None

            if substitute:
                # Load substitute's user for email
                sub_user_q = await db.execute(
                    select(User).where(User.id == substitute.user_id)
                )
                sub_user = sub_user_q.scalar_one_or_none()

                if sub_user and (sub_user.email or sub_user.phone):
                    # Send notification via both email + SMS (blocking I/O)
                    from services.gateway.ai.notifier import (
                        send_substitution_notification,
                        schedule_reminder,
                    )

                    email_sent, sms_sent = await asyncio.get_event_loop().run_in_executor(
                        None,
                        send_substitution_notification,
                        sub_user.email,
                        sub_user.phone,
                        sub_user.name,
                        teacher_name,
                        entry.klass.grade,
                        entry.klass.section,
                        entry.subject.name,
                        entry.period.name,
                        entry.period.start_time,
                        body.date,
                    )

                    # Schedule reminder (non-blocking background task)
                    reminder_scheduled = schedule_reminder(
                        sub_user.email,
                        sub_user.phone,
                        sub_user.name,
                        entry.subject.name,
                        entry.period.name,
                        entry.period.start_time,
                        body.date,
                    )

                # Update flags on substitution record
                substitution.email_sent = email_sent
                substitution.sms_sent = sms_sent

            # ── Notify parents of students in the affected class ──────────────
            parents_notified = 0
            if substitute and sub_user:
                from services.gateway.ai.messenger import send_to_users

                students_q = await db.execute(
                    select(Student)
                    .where(
                        Student.tenant_id == tenant.id,
                        Student.class_id == entry.class_id,
                    )
                    .options(
                        selectinload(Student.parents).selectinload(StudentParent.parent)
                    )
                )
                students = students_q.scalars().all()

                parent_users: list = []
                seen_ids: set = set()
                for student in students:
                    for sp in student.parents:
                        if sp.parent and sp.parent.id not in seen_ids:
                            seen_ids.add(sp.parent.id)
                            parent_users.append((sp.parent, student))

                parent_msg = (
                    f"[SchoolOS] Dear Parent, {teacher_name} is absent on {body.date}. "
                    f"Your child's {entry.subject.name} class ({entry.klass.grade} {entry.klass.section}, "
                    f"{entry.period.name} at {entry.period.start_time}) will be covered by {sub_user.name}."
                )
                for parent_user, student in parent_users:
                    await send_to_users(
                        [parent_user],
                        parent_msg,
                        "substitution_alert",
                        db,
                        student_id=student.id,
                        email_subject=f"[SchoolOS] Class Coverage Notice - {body.date}",
                    )
                    parents_notified += 1

            slot_results.append({
                "period":           {"name": entry.period.name, "start_time": entry.period.start_time},
                "class":            {"grade": entry.klass.grade, "section": entry.klass.section},
                "subject":          entry.subject.name,
                "absent_teacher":   teacher_name,
                "substitute":       sub_user.name if substitute and sub_user else None,
                "substitute_email": sub_user.email if substitute and sub_user else None,
                "substitute_phone": sub_user.phone if substitute and sub_user else None,
                "status":           sub_status,
                "confidence_score": confidence if substitute else None,
                "confidence_reasons": confidence_reasons if substitute else None,
                "email_sent":       email_sent,
                "sms_sent":         sms_sent,
                "parents_notified": parents_notified,
                "reminder_scheduled": reminder_scheduled,
                "substitution_id":  str(substitution.id),
                "skip_reason":      reason,
            })

        results.append({
            "absent_teacher": teacher_name,
            "error": None,
            "slots": slot_results,
        })

    await db.commit()

    # Summary counts
    all_slots = [s for r in results for s in r.get("slots", [])]
    assigned  = sum(1 for s in all_slots if s["status"] == "assigned")
    unassigned = sum(1 for s in all_slots if s["status"] == "no_substitute_found")

    return {
        "date":            body.date,
        "day":             ["Monday","Tuesday","Wednesday","Thursday","Friday"][day_of_week],
        "academic_year":   body.academic_year,
        "substitutions":   results,
        "summary": {
            "total_slots": len(all_slots),
            "assigned":    assigned,
            "unassigned":  unassigned,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /substitution/
# Admin record view — all substitutions for a date
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", summary="List substitutions for a date")
async def list_substitutions(
    date: str,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all substitution records for the given date.
    Used by the admin to see the full coverage picture for the day.

    Query param: ?date=2025-04-14
    """
    await set_tenant_context(db, tenant.id)

    try:
        query_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    q = await db.execute(
        select(Substitution)
        .where(
            Substitution.tenant_id == tenant.id,
            Substitution.date == query_date,
        )
        .options(
            selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.period),
            selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.klass),
            selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.subject),
            selectinload(Substitution.absent_teacher).selectinload(Teacher.user),
            selectinload(Substitution.substitute_teacher).selectinload(Teacher.user),
        )
        .order_by(Substitution.created_at)
    )
    subs = q.scalars().all()

    return [_format_substitution(s) for s in subs]


# ─────────────────────────────────────────────────────────────────────────────
# Substitute finder algorithm
# ─────────────────────────────────────────────────────────────────────────────

async def _find_substitute(
    db: AsyncSession,
    tenant: Tenant,
    entry: TimetableEntry,
    absent_teacher_id: uuid.UUID,
    date_str: str,
    academic_year: str,
    week_start: date_type,
    week_end: date_type,
) -> tuple[Teacher | None, str | None, int, dict]:
    """
    Finds the best available substitute for a timetable slot.
    Returns (teacher, skip_reason, confidence_score, confidence_reasons).

    Confidence scoring (0-100):
      - Free in the period:       20 pts  (baseline for all candidates)
      - Subject-qualified:        35 pts  (teaches the exact subject)
      - Load headroom:         0-25 pts   (how far below max_weekly_hours)
      - Sub limit headroom:    0-20 pts   (how far below max_substitutions_per_week)

    Priority: highest confidence score first.
    """
    report_date = date_type.fromisoformat(date_str)

    # ── Who is already busy in this period on this day? ──────────────────────

    # Busy via regular timetable
    busy_timetable_q = await db.execute(
        select(TimetableEntry.teacher_id).where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.period_id == entry.period_id,
            TimetableEntry.day_of_week == entry.day_of_week,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.is_active.is_(True),
        )
    )
    busy_ids: set[uuid.UUID] = set(busy_timetable_q.scalars().all())

    # Busy via already-assigned substitutions on this date in this period
    busy_sub_q = await db.execute(
        select(Substitution.substitute_teacher_id).where(
            Substitution.tenant_id == tenant.id,
            Substitution.date == report_date,
            Substitution.substitute_teacher_id.isnot(None),
            Substitution.timetable_entry_id.in_(
                select(TimetableEntry.id).where(
                    TimetableEntry.period_id == entry.period_id,
                    TimetableEntry.academic_year == academic_year,
                )
            ),
        )
    )
    busy_ids.update(busy_sub_q.scalars().all())

    # Also exclude the absent teacher themselves
    busy_ids.add(absent_teacher_id)

    # ── Get all teachers qualified for this subject ───────────────────────────
    same_subject_q = await db.execute(
        select(Teacher)
        .join(TeacherSubject, TeacherSubject.teacher_id == Teacher.id)
        .where(
            TeacherSubject.subject_id == entry.subject_id,
            Teacher.tenant_id == tenant.id,
            Teacher.id.notin_(busy_ids),
        )
        .options(selectinload(Teacher.user))
    )
    same_subject = same_subject_q.scalars().all()
    same_subject_ids = {t.id for t in same_subject}

    # ── Get all other teachers (lower priority) ───────────────────────────────
    other_q = await db.execute(
        select(Teacher)
        .where(
            Teacher.tenant_id == tenant.id,
            Teacher.id.notin_(busy_ids),
            Teacher.id.notin_([t.id for t in same_subject]),
        )
        .options(selectinload(Teacher.user))
    )
    other_teachers = other_q.scalars().all()

    # All candidates
    candidates = same_subject + other_teachers

    if not candidates:
        return None, "All teachers are busy in this period.", 0, {}

    # ── Score each candidate ─────────────────────────────────────────────────
    scored: list[tuple[Teacher, int, dict]] = []

    for teacher in candidates:
        reasons = {}
        score = 0

        # Baseline: free in the period (always true for candidates)
        score += 20
        reasons["free_in_period"] = 20

        # Subject match
        if teacher.id in same_subject_ids:
            score += 35
            reasons["subject_qualified"] = 35
        else:
            reasons["subject_qualified"] = 0

        # Load headroom: (max - assigned) / max * 25
        weekly_sessions = await db.scalar(
            select(func.count()).where(
                TimetableEntry.teacher_id == teacher.id,
                TimetableEntry.academic_year == academic_year,
                TimetableEntry.is_active.is_(True),
            )
        ) or 0
        max_h = teacher.max_weekly_hours or 20
        if weekly_sessions >= max_h:
            continue  # full schedule — skip entirely
        load_ratio = (max_h - weekly_sessions) / max_h
        load_pts = round(load_ratio * 25)
        score += load_pts
        reasons["load_headroom"] = load_pts
        reasons["load_detail"] = f"{weekly_sessions}/{max_h} periods used"

        # Sub limit headroom: (max - used) / max * 20
        subs_this_week = await db.scalar(
            select(func.count()).where(
                Substitution.substitute_teacher_id == teacher.id,
                Substitution.tenant_id == tenant.id,
                Substitution.date >= week_start,
                Substitution.date <= week_end,
                Substitution.status == "assigned",
            )
        ) or 0
        max_subs = teacher.max_substitutions_per_week or 2
        if subs_this_week >= max_subs:
            continue  # reached sub cap — skip entirely
        sub_ratio = (max_subs - subs_this_week) / max_subs
        sub_pts = round(sub_ratio * 20)
        score += sub_pts
        reasons["sub_headroom"] = sub_pts
        reasons["sub_detail"] = f"{subs_this_week}/{max_subs} subs this week"

        scored.append((teacher, score, reasons))

    if not scored:
        return None, "All available teachers have reached their session or substitution limits.", 0, {}

    # Sort by score descending — pick the best
    scored.sort(key=lambda x: x[1], reverse=True)
    best_teacher, best_score, best_reasons = scored[0]

    return best_teacher, None, best_score, best_reasons


# ─────────────────────────────────────────────────────────────────────────────
# Formatter
# ─────────────────────────────────────────────────────────────────────────────

def _format_substitution(s: Substitution) -> dict:
    entry = s.timetable_entry
    return {
        "id":             str(s.id),
        "date":           str(s.date),
        "status":         s.status,
        "period":         {
            "name":       entry.period.name if entry else None,
            "start_time": entry.period.start_time if entry else None,
        },
        "class":          {
            "grade":   entry.klass.grade if entry else None,
            "section": entry.klass.section if entry else None,
        },
        "subject":        entry.subject.name if entry else None,
        "absent_teacher": s.absent_teacher.user.name if s.absent_teacher and s.absent_teacher.user else None,
        "substitute":     s.substitute_teacher.user.name if s.substitute_teacher and s.substitute_teacher.user else None,
        "confidence_score": s.confidence_score,
        "confidence_reasons": s.confidence_reasons,
        "email_sent":     s.email_sent,
        "sms_sent":       s.sms_sent,
        "reminder_sent":  s.reminder_sent,
        "created_at":     str(s.created_at),
    }
