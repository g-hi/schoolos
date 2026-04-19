"""
Phase 4 - Communication Router
================================
Handles all outbound parent notifications and agent-driven communication.

Endpoints
---------
POST /communication/daily-digest   – send tomorrow's timetable to all parents
POST /communication/broadcast      – admin sends a custom message (holiday, trip, etc.)
GET  /communication/log            – view message history
GET  /communication/stats          – message stats by type and channel
GET  /communication/grades         – list available grades for broadcast filtering
GET  /communication/agents         – list autonomous agent definitions and their status
"""

import uuid
from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Message,
    Period,
    Student,
    StudentParent,
    Subject,
    Teacher,
    Tenant,
    TimetableEntry,
    User,
)

router = APIRouter(prefix="/communication", tags=["Communication"])


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class DailyDigestRequest(BaseModel):
    target_date: str          # "YYYY-MM-DD" — the date parents should prepare for
    academic_year: str = "2025-2026"


class BroadcastRequest(BaseModel):
    message: str | None = None  # the text to send
    body: str | None = None     # alias from frontend
    subject: str | None = None  # optional subject line
    grade: str | None = None    # filter to a specific grade
    section: str | None = None  # combined with grade → specific class
    academic_year: str = "2025-2026"


# ─────────────────────────────────────────────────────────────────────────────
# POST /communication/daily-digest
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/daily-digest", summary="Send tomorrow's schedule to all parents")
async def send_daily_digest(
    body: DailyDigestRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Sends each parent their child's full subject schedule for the target date.

    Example request:
        {
          "target_date": "2025-04-15",
          "academic_year": "2025-2026"
        }

    Each parent receives (via preferred channel):
        "Tomorrow's schedule for Ali Hassan (Grade 1 A):
         Period 1 (08:00): Mathematics
         Period 2 (09:00): English
         ..."
    """
    from services.gateway.ai.messenger import send_to_users

    await set_tenant_context(db, tenant.id)

    try:
        target = date_type.fromisoformat(body.target_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    day_of_week = target.weekday()
    if day_of_week > 4:
        raise HTTPException(status_code=400, detail="Target date is a weekend — no school schedule.")

    day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][day_of_week]

    # Load all timetable entries for that day, ordered by period
    entries_q = await db.execute(
        select(TimetableEntry)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.day_of_week == day_of_week,
            TimetableEntry.academic_year == body.academic_year,
            TimetableEntry.is_active.is_(True),
        )
        .options(
            selectinload(TimetableEntry.period),
            selectinload(TimetableEntry.klass),
            selectinload(TimetableEntry.subject),
        )
        .order_by(TimetableEntry.class_id)
    )
    entries = entries_q.scalars().all()

    if not entries:
        raise HTTPException(
            status_code=404,
            detail=f"No timetable entries found for {day_name} in {body.academic_year}.",
        )

    # Group entries by class_id
    schedule_by_class: dict[uuid.UUID, list[TimetableEntry]] = {}
    for entry in entries:
        schedule_by_class.setdefault(entry.class_id, []).append(entry)

    # Sort each class's entries by period sort_order
    for class_id in schedule_by_class:
        schedule_by_class[class_id].sort(key=lambda e: e.period.sort_order)

    # Load students for all affected classes
    students_q = await db.execute(
        select(Student)
        .where(
            Student.tenant_id == tenant.id,
            Student.class_id.in_(list(schedule_by_class.keys())),
        )
        .options(
            selectinload(Student.parents).selectinload(StudentParent.parent),
        )
    )
    students = students_q.scalars().all()

    total_sent = 0
    total_failed = 0
    total_skipped = 0
    notified_parents: set[uuid.UUID] = set()  # avoid duplicate messages to same parent

    for student in students:
        class_entries = schedule_by_class.get(student.class_id, [])
        if not class_entries:
            continue

        # Build the schedule lines
        klass = class_entries[0].klass
        lines = [
            f"[SchoolOS] Schedule for {student.name} ({klass.grade} {klass.section}) "
            f"on {day_name} {body.target_date}:"
        ]
        for e in class_entries:
            lines.append(f"  {e.period.name} ({e.period.start_time}): {e.subject.name}")
        lines.append("Please prepare the required books. - SchoolOS")
        message_text = "\n".join(lines)

        # Collect unique parents for this student
        parents_to_notify = [
            sp.parent for sp in student.parents
            if sp.parent and sp.parent.id not in notified_parents
        ]

        if not parents_to_notify:
            continue

        msgs = await send_to_users(
            parents_to_notify,
            message_text,
            "daily_digest",
            db,
            student_id=student.id,
            email_subject=f"[SchoolOS] {student.name}'s Schedule for {body.target_date}",
        )

        for msg in msgs:
            notified_parents.add(msg.recipient_id)
            if msg.status == "sent":
                total_sent += 1
            elif msg.status == "failed":
                total_failed += 1
            else:
                total_skipped += 1

    await db.commit()

    return {
        "date": body.target_date,
        "day": day_name,
        "classes_covered": len(schedule_by_class),
        "students_covered": len(students),
        "summary": {
            "sent": total_sent,
            "failed": total_failed,
            "skipped": total_skipped,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /communication/broadcast
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/broadcast", summary="Send a custom announcement to parents")
async def broadcast(
    body: BroadcastRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Sends a free-text announcement to parents.
    Use for: holidays, school trips, early dismissal, events.

    Scope options (mutually exclusive, most specific wins):
      - No filter         → all parents in the school
      - grade only        → all parents of students in that grade
      - grade + section   → parents of one specific class

    Example:
        {
          "message": "School will be closed on Thursday for National Day.",
          "grade": "Grade 1"
        }
    """
    from services.gateway.ai.messenger import send_to_users

    await set_tenant_context(db, tenant.id)

    # Accept message from either 'message' or 'body' field
    text = (body.message or body.body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Resolve target classes
    class_query = select(Class).where(
        Class.tenant_id == tenant.id,
        Class.academic_year == body.academic_year,
    )
    if body.grade:
        class_query = class_query.where(Class.grade == body.grade)
    if body.section:
        class_query = class_query.where(Class.section == body.section)

    classes_q = await db.execute(class_query)
    classes = classes_q.scalars().all()

    if not classes:
        raise HTTPException(status_code=404, detail="No classes found for the given filter.")

    class_ids = [c.id for c in classes]

    # Load students + their parents
    students_q = await db.execute(
        select(Student)
        .where(
            Student.tenant_id == tenant.id,
            Student.class_id.in_(class_ids),
        )
        .options(
            selectinload(Student.parents).selectinload(StudentParent.parent),
        )
    )
    students = students_q.scalars().all()

    # Collect unique parent Users (one parent may have multiple kids)
    seen_parent_ids: set[uuid.UUID] = set()
    unique_parents: list[User] = []
    for student in students:
        for sp in student.parents:
            if sp.parent and sp.parent.id not in seen_parent_ids:
                seen_parent_ids.add(sp.parent.id)
                unique_parents.append(sp.parent)

    if not unique_parents:
        raise HTTPException(status_code=404, detail="No parent users found for the given scope.")

    msgs = await send_to_users(
        unique_parents,
        text,
        "broadcast",
        db,
        email_subject=f"[SchoolOS] {body.subject or 'School Announcement'}",
    )

    await db.commit()

    sent    = sum(1 for m in msgs if m.status == "sent")
    failed  = sum(1 for m in msgs if m.status == "failed")
    skipped = sum(1 for m in msgs if m.status == "skipped")

    scope = "all parents"
    if body.grade and body.section:
        scope = f"{body.grade} {body.section} parents"
    elif body.grade:
        scope = f"{body.grade} parents"

    return {
        "scope": scope,
        "recipients": len(unique_parents),
        "summary": {
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /communication/log
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/log", summary="View message history")
async def message_log(
    message_type: str | None = None,   # filter: daily_digest / broadcast / substitution_alert
    channel: str | None = None,        # filter: whatsapp / sms / email
    status: str | None = None,         # filter: sent / failed / skipped
    limit: int = 50,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns message history for the tenant, newest first.

    Filterable by message_type, channel, and status.
    Limited to 50 rows by default (pass ?limit=N to change).
    """
    await set_tenant_context(db, tenant.id)

    query = (
        select(Message)
        .where(Message.tenant_id == tenant.id)
        .options(
            selectinload(Message.recipient),
            selectinload(Message.student),
        )
        .order_by(Message.created_at.desc())
        .limit(min(limit, 200))
    )

    if message_type:
        query = query.where(Message.message_type == message_type)
    if channel:
        query = query.where(Message.channel == channel)
    if status:
        query = query.where(Message.status == status)

    result = await db.execute(query)
    messages = result.scalars().all()

    return [
        {
            "id":           str(m.id),
            "recipient":    m.recipient.name if m.recipient else None,
            "student":      m.student.name if m.student else None,
            "channel":      m.channel,
            "message_type": m.message_type,
            "status":       m.status,
            "error":        m.error,
            "body":         m.body,
            "sent_at":      str(m.created_at),
        }
        for m in messages
    ]


# ─────────────────────────────────────────────────────────────────────────────
# GET /communication/stats — message counts by type/channel/status
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Message stats for dashboard cards")
async def message_stats(
    days: int = 7,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Returns counts by message_type, channel, and status for the last N days."""
    await set_tenant_context(db, tenant.id)

    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)

    type_q = await db.execute(
        select(Message.message_type, func.count(Message.id))
        .where(Message.tenant_id == tenant.id, Message.created_at >= cutoff)
        .group_by(Message.message_type)
    )
    by_type = {row[0]: row[1] for row in type_q.all()}

    status_q = await db.execute(
        select(Message.status, func.count(Message.id))
        .where(Message.tenant_id == tenant.id, Message.created_at >= cutoff)
        .group_by(Message.status)
    )
    by_status = {row[0]: row[1] for row in status_q.all()}

    channel_q = await db.execute(
        select(Message.channel, func.count(Message.id))
        .where(Message.tenant_id == tenant.id, Message.created_at >= cutoff)
        .group_by(Message.channel)
    )
    by_channel = {row[0]: row[1] for row in channel_q.all()}

    return {
        "period_days": days,
        "total": sum(by_status.values()),
        "by_type": by_type,
        "by_status": by_status,
        "by_channel": by_channel,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /communication/grades — available grades for broadcast filtering
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/grades", summary="List grades and sections for broadcast targeting")
async def list_grades(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    q = await db.execute(
        select(Class.grade, Class.section)
        .where(Class.tenant_id == tenant.id, Class.academic_year == academic_year)
        .order_by(Class.grade, Class.section)
    )
    rows = q.all()

    grades: dict[str, list[str]] = {}
    for grade, section in rows:
        grades.setdefault(grade, []).append(section)

    return [{"grade": g, "sections": secs} for g, secs in grades.items()]


# ─────────────────────────────────────────────────────────────────────────────
# GET /communication/agents — autonomous agent definitions
# ─────────────────────────────────────────────────────────────────────────────

AGENT_DEFINITIONS = [
    {
        "id": "daily_digest",
        "name": "Daily Digest Agent",
        "description": "Sends tomorrow's schedule to all parents every evening at 7 PM",
        "trigger": "Daily at 7:00 PM",
        "channel": "Preferred (WhatsApp / SMS / Email)",
        "icon": "📅",
    },
    {
        "id": "substitution_alert",
        "name": "Substitution Agent",
        "description": "Notifies substitute teachers and affected parents when a teacher is absent",
        "trigger": "On teacher absence report",
        "channel": "Email + SMS",
        "icon": "🔄",
    },
    {
        "id": "duty_reminder",
        "name": "Duty Reminder Agent",
        "description": "Reminds teachers of their duty assignment 15 min before the slot",
        "trigger": "15 min before duty slot",
        "channel": "SMS",
        "icon": "🛡️",
    },
    {
        "id": "attendance_alert",
        "name": "Attendance Agent",
        "description": "Alerts parents when their child is marked absent during the day",
        "trigger": "On absence marked",
        "channel": "WhatsApp",
        "icon": "📋",
    },
    {
        "id": "pickup_notify",
        "name": "Pickup Agent",
        "description": "Confirms pickup requests and notifies the class teacher for release",
        "trigger": "On parent pickup request",
        "channel": "WhatsApp + SMS",
        "icon": "🚗",
    },
    {
        "id": "crisis_alert",
        "name": "Crisis Agent",
        "description": "Detects spikes in negative social mentions and alerts the principal",
        "trigger": "On negative mention spike",
        "channel": "SMS + Email",
        "icon": "🚨",
    },
]


@router.get("/agents", summary="List autonomous agent definitions")
async def list_agents(
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Returns agent definitions with live message counts from the last 7 days."""
    await set_tenant_context(db, tenant.id)

    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)

    q = await db.execute(
        select(Message.message_type, func.count(Message.id))
        .where(Message.tenant_id == tenant.id, Message.created_at >= cutoff)
        .group_by(Message.message_type)
    )
    counts = {row[0]: row[1] for row in q.all()}

    result = []
    for agent in AGENT_DEFINITIONS:
        result.append({
            **agent,
            "messages_7d": counts.get(agent["id"], 0),
        })
    return result
