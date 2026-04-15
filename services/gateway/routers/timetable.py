"""
Phase 2 – Timetable Router
============================
Manages the weekly class schedule for a school.

Endpoints
---------
POST   /timetable/periods          – upload periods CSV (school day time slots)
POST   /timetable/upload           – upload full timetable CSV
GET    /timetable/                 – list full timetable (filterable by class/teacher/day)
GET    /timetable/class/{class_id} – weekly schedule for one class
GET    /timetable/teacher/{teacher_id} – weekly schedule for one teacher
DELETE /timetable/{entry_id}       – remove a single timetable slot

Phase 2 Enhanced
-----------------
POST   /timetable/chat             – add a natural-language scheduling constraint (via Groq)
POST   /timetable/generate         – auto-generate timetable via OR-Tools solver
GET    /timetable/download/pdf     – download full timetable as PDF

How the timetable grid works
-----------------------------
Think of the timetable as a spreadsheet:
  - Rows     = Periods (Period 1, Period 2, …)
  - Columns  = Days (Monday, Tuesday, …)
  - Each cell = one TimetableEntry (class + subject + teacher)

A school first uploads their periods (the time slots), then uploads
the timetable CSV which fills in the grid.

Day encoding: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday
"""

import csv
import io
import uuid
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    Subject,
    Teacher,
    TimetableConstraint,
    TimetableEntry,
    Tenant,
    User,
)

router = APIRouter(prefix="/timetable", tags=["Timetable"])

DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday",
             5: "Saturday", 6: "Sunday"}
DAY_LOOKUP = {v.lower(): k for k, v in DAY_NAMES.items()}
# Also accept short forms
DAY_LOOKUP.update({"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6})


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [{k.strip().lower(): v.strip() for k, v in row.items()} for row in reader]


def _missing(row: dict, *fields: str) -> str | None:
    for f in fields:
        if not row.get(f):
            return f"missing required field: {f}"
    return None


IngestResult = dict[str, Any]


def _result(inserted: int, skipped: int, errors: list[dict]) -> IngestResult:
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# POST /timetable/periods
# CSV columns: sort_order, name, start_time, end_time
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/periods", summary="Upload school day periods CSV")
async def upload_periods(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        sort_order,name,start_time,end_time
        1,Period 1,08:00,08:45
        2,Period 2,08:50,09:35
        3,Break,09:35,09:50
        4,Period 3,09:50,10:35
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())
    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "sort_order", "name", "start_time", "end_time")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        try:
            sort_order = int(row["sort_order"])
        except ValueError:
            errors.append({"row": i, "error": "sort_order must be a number"})
            skipped += 1
            continue

        exists = await db.scalar(
            select(Period.id).where(
                Period.tenant_id == tenant.id,
                Period.sort_order == sort_order,
            )
        )
        if exists:
            errors.append({"row": i, "error": f"duplicate sort_order: {sort_order}"})
            skipped += 1
            continue

        db.add(Period(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=row["name"],
            sort_order=sort_order,
            start_time=row["start_time"],
            end_time=row["end_time"],
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# POST /timetable/upload
# CSV columns: day, period_order, grade, section, academic_year,
#              subject_code, teacher_email
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload", summary="Upload full timetable CSV")
async def upload_timetable(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        day,period_order,grade,section,academic_year,subject_code,teacher_email
        Monday,1,Grade 1,A,2025-2026,MATH,john.smith@greenwood.edu
        Monday,2,Grade 1,A,2025-2026,ENG,sara.jones@greenwood.edu
        Tuesday,1,Grade 1,A,2025-2026,SCI,john.smith@greenwood.edu

    day: Monday/Tuesday/Wednesday/Thursday/Friday (or Mon/Tue/Wed/Thu/Fri)
    period_order: the sort_order of the period (e.g. 1, 2, 3)
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())
    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "day", "period_order", "grade", "section",
                       "academic_year", "subject_code", "teacher_email")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        # Resolve day_of_week
        day_of_week = DAY_LOOKUP.get(row["day"].lower())
        if day_of_week is None:
            errors.append({"row": i, "error": f"unknown day: {row['day']}"})
            skipped += 1
            continue

        # Resolve period
        try:
            period_order = int(row["period_order"])
        except ValueError:
            errors.append({"row": i, "error": "period_order must be a number"})
            skipped += 1
            continue

        period_id = await db.scalar(
            select(Period.id).where(
                Period.tenant_id == tenant.id,
                Period.sort_order == period_order,
            )
        )
        if not period_id:
            errors.append({"row": i, "error": f"period not found: order {period_order}"})
            skipped += 1
            continue

        # Resolve class
        class_id = await db.scalar(
            select(Class.id).where(
                Class.tenant_id == tenant.id,
                Class.grade == row["grade"],
                Class.section == row["section"],
                Class.academic_year == row["academic_year"],
            )
        )
        if not class_id:
            errors.append({"row": i, "error": f"class not found: {row['grade']} {row['section']} ({row['academic_year']})"})
            skipped += 1
            continue

        # Resolve subject
        subject_id = await db.scalar(
            select(Subject.id).where(
                Subject.tenant_id == tenant.id,
                Subject.code == row["subject_code"].upper(),
            )
        )
        if not subject_id:
            errors.append({"row": i, "error": f"subject not found: {row['subject_code']}"})
            skipped += 1
            continue

        # Resolve teacher via email → user → teacher
        user_id = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant.id,
                User.email == row["teacher_email"].lower(),
            )
        )
        teacher_id = await db.scalar(
            select(Teacher.id).where(
                Teacher.tenant_id == tenant.id,
                Teacher.user_id == user_id,
            )
        ) if user_id else None

        if not teacher_id:
            errors.append({"row": i, "error": f"teacher not found: {row['teacher_email']}"})
            skipped += 1
            continue

        # Duplicate slot check (class conflict)
        class_conflict = await db.scalar(
            select(TimetableEntry.id).where(
                TimetableEntry.tenant_id == tenant.id,
                TimetableEntry.academic_year == row["academic_year"],
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.period_id == period_id,
                TimetableEntry.class_id == class_id,
            )
        )
        if class_conflict:
            errors.append({"row": i, "error": f"class already has a lesson in this slot"})
            skipped += 1
            continue

        # Teacher double-booking check
        teacher_conflict = await db.scalar(
            select(TimetableEntry.id).where(
                TimetableEntry.tenant_id == tenant.id,
                TimetableEntry.academic_year == row["academic_year"],
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.period_id == period_id,
                TimetableEntry.teacher_id == teacher_id,
            )
        )
        if teacher_conflict:
            errors.append({"row": i, "error": f"teacher {row['teacher_email']} already assigned in this slot"})
            skipped += 1
            continue

        db.add(TimetableEntry(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            academic_year=row["academic_year"],
            day_of_week=day_of_week,
            period_id=period_id,
            class_id=class_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# GET /timetable/
# Returns all entries, optionally filtered
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", summary="List timetable entries")
async def list_timetable(
    academic_year: str = "2025-2026",
    day: int | None = None,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all timetable entries for the school.
    Filter by day (0=Monday … 4=Friday) and academic_year.
    Results are sorted by day then period order.
    """
    await set_tenant_context(db, tenant.id)

    stmt = (
        select(TimetableEntry)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.is_active == True,
        )
        .options(
            selectinload(TimetableEntry.period),
            selectinload(TimetableEntry.klass),
            selectinload(TimetableEntry.subject),
            selectinload(TimetableEntry.teacher).selectinload(Teacher.user),
        )
    )
    if day is not None:
        stmt = stmt.where(TimetableEntry.day_of_week == day)

    result = await db.execute(stmt)
    entries = result.scalars().all()

    return [_format_entry(e) for e in entries]


# ─────────────────────────────────────────────────────────────────────────────
# GET /timetable/class/{class_id}
# Weekly schedule for a single class
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/class/{class_id}", summary="Get class weekly schedule")
async def class_timetable(
    class_id: uuid.UUID,
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the full weekly schedule for one class, grouped by day.
    Used to display the class timetable on a dashboard or print it.
    """
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        select(TimetableEntry)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.class_id == class_id,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.is_active == True,
        )
        .options(
            selectinload(TimetableEntry.period),
            selectinload(TimetableEntry.klass),
            selectinload(TimetableEntry.subject),
            selectinload(TimetableEntry.teacher).selectinload(Teacher.user),
        )
    )
    entries = result.scalars().all()

    # Group by day
    grouped: dict[str, list] = {}
    for e in entries:
        day_name = DAY_NAMES.get(e.day_of_week, str(e.day_of_week))
        grouped.setdefault(day_name, []).append(_format_entry(e))

    return grouped


# ─────────────────────────────────────────────────────────────────────────────
# GET /timetable/teacher/{teacher_id}
# Weekly schedule for a single teacher
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/teacher/{teacher_id}", summary="Get teacher weekly schedule")
async def teacher_timetable(
    teacher_id: uuid.UUID,
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the full weekly schedule for one teacher, grouped by day.
    Used by the substitution engine (Phase 3) to find free slots.
    """
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        select(TimetableEntry)
        .where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.teacher_id == teacher_id,
            TimetableEntry.academic_year == academic_year,
            TimetableEntry.is_active == True,
        )
        .options(
            selectinload(TimetableEntry.period),
            selectinload(TimetableEntry.klass),
            selectinload(TimetableEntry.subject),
            selectinload(TimetableEntry.teacher).selectinload(Teacher.user),
        )
    )
    entries = result.scalars().all()

    grouped: dict[str, list] = {}
    for e in entries:
        day_name = DAY_NAMES.get(e.day_of_week, str(e.day_of_week))
        grouped.setdefault(day_name, []).append(_format_entry(e))

    return grouped


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /timetable/{entry_id}
# Remove one slot
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{entry_id}", summary="Remove a timetable slot")
async def delete_entry(
    entry_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)

    entry = await db.scalar(
        select(TimetableEntry).where(
            TimetableEntry.id == entry_id,
            TimetableEntry.tenant_id == tenant.id,
        )
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Timetable entry not found")

    await db.delete(entry)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable.deleted",
        entity_type="TimetableEntry",
        entity_id=entry.id,
        details={"day_of_week": entry.day_of_week, "period_id": str(entry.period_id)},
    )
    await db.commit()
    return {"deleted": str(entry_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_entry(e: TimetableEntry) -> dict:
    """Serialize a TimetableEntry into a clean JSON-friendly dict."""
    return {
        "id":            str(e.id),
        "day":           DAY_NAMES.get(e.day_of_week, e.day_of_week),
        "day_of_week":   e.day_of_week,
        "period":        {
            "id":         str(e.period.id),
            "name":       e.period.name,
            "start_time": e.period.start_time,
            "end_time":   e.period.end_time,
        } if e.period else None,
        "class":         {
            "id":      str(e.klass.id),
            "grade":   e.klass.grade,
            "section": e.klass.section,
        } if e.klass else None,
        "subject":       {
            "id":   str(e.subject.id),
            "code": e.subject.code,
            "name": e.subject.name,
        } if e.subject else None,
        "teacher":       {
            "id":   str(e.teacher.id),
            "name": e.teacher.user.name if e.teacher and e.teacher.user else None,
        } if e.teacher else None,
        "is_active":     e.is_active,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /timetable/chat
# Admin types a natural-language constraint;
# Groq LLM parses it and stores it in timetable_constraints.
# ─────────────────────────────────────────────────────────────────────────────

class ChatConstraintRequest(BaseModel):
    message: str                    # e.g. "Teacher John should not have Period 4"
    academic_year: str = "2025-2026"


@router.post("/chat", summary="Add a scheduling constraint in plain English")
async def chat_constraint(
    body: ChatConstraintRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    The admin describes a scheduling rule in plain English.
    The Groq LLM parses it into structured JSON and saves it to the DB.

    Example request body:
        {
          "message": "Teacher John Smith should not have any lessons in Period 4",
          "academic_year": "2025-2026"
        }

    Example response:
        {
          "saved": true,
          "constraint_type": "teacher_unavailable",
          "parsed": {"teacher_name": "John Smith", "day_of_week": null, "period_order": 4},
          "confidence": "high",
          "constraint_id": "uuid..."
        }

    The saved constraint will be enforced the next time /timetable/generate is called.
    """
    from services.gateway.ai.constraint_parser import parse_constraint

    await set_tenant_context(db, tenant.id)

    # Run the synchronous LLM call off the async event loop
    try:
        parsed = await asyncio.get_event_loop().run_in_executor(
            None, parse_constraint, body.message
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        # Catch Groq auth errors, network errors, etc.
        err_msg = str(exc)
        if "401" in err_msg or "invalid_api_key" in err_msg or "Invalid API Key" in err_msg:
            raise HTTPException(
                status_code=503,
                detail="Groq API key is not configured. Set GROQ_API_KEY in .env and restart.",
            )
        raise HTTPException(status_code=502, detail=f"LLM error: {err_msg}")

    constraint = TimetableConstraint(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        raw_text=body.message,
        constraint_type=parsed["constraint_type"],
        data=parsed.get("data", {}),
        is_active=True,
        academic_year=body.academic_year,
    )
    db.add(constraint)
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable.constraint_added",
        entity_type="TimetableConstraint",
        details={"raw_text": body.message, "constraint_type": parsed["constraint_type"]},
    )
    await db.commit()

    return {
        "saved":           True,
        "constraint_type": parsed["constraint_type"],
        "parsed":          parsed.get("data", {}),
        "confidence":      parsed.get("confidence", "unknown"),
        "constraint_id":   str(constraint.id),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /timetable/generate
# Runs the OR-Tools solver to auto-generate a valid timetable.
# Replaces all existing entries for the given academic_year.
# ─────────────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    academic_year: str = "2025-2026"


@router.post("/generate", summary="Auto-generate timetable via OR-Tools solver")
async def generate_timetable(
    body: GenerateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Runs the OR-Tools CP-SAT solver to create a valid weekly timetable.

    What it does:
    1. Reads all teachers, classes, subjects, periods from DB.
    2. Reads all active constraints for the academic_year.
    3. Solves: every class gets every subject once a week, no double-booking.
    4. Deletes all existing TimetableEntry rows for this academic_year.
    5. Inserts the new generated entries.

    Returns a summary: how many entries were created.

    WARNING: This clears and replaces the existing timetable for the academic_year.
             Run /timetable/chat to add constraints first, then call this endpoint.
    """
    from services.gateway.ai.solver import generate_timetable as run_solver, SolverError

    await set_tenant_context(db, tenant.id)

    try:
        entries = await run_solver(tenant.id, body.academic_year)
    except SolverError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Clear existing entries for this year
    await db.execute(
        sql_delete(TimetableEntry).where(
            TimetableEntry.tenant_id == tenant.id,
            TimetableEntry.academic_year == body.academic_year,
        )
    )

    # Bulk-insert new entries
    for e in entries:
        db.add(TimetableEntry(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            academic_year=e["academic_year"],
            day_of_week=e["day_of_week"],
            period_id=uuid.UUID(e["period_id"]),
            class_id=uuid.UUID(e["class_id"]),
            subject_id=uuid.UUID(e["subject_id"]),
            teacher_id=uuid.UUID(e["teacher_id"]),
            is_active=True,
        ))

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable.generated",
        entity_type="TimetableEntry",
        details={"generated_count": len(entries), "academic_year": body.academic_year},
    )

    await db.commit()

    return {
        "generated":    len(entries),
        "academic_year": body.academic_year,
        "message":      (
            f"Timetable generated: {len(entries)} slots created for {body.academic_year}. "
            "Use GET /timetable/ to view, or GET /timetable/download/pdf to download."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /timetable/download/pdf
# Returns the full timetable as a downloadable PDF.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/download/pdf", summary="Download timetable as PDF")
async def download_pdf(
    academic_year: str = "2025-2026",
    tenant: Tenant = Depends(resolve_tenant),
):
    """
    Generates and downloads a branded PDF timetable (one page per class).
    The school name is pulled from the tenant record.

    Returns: application/pdf binary download.
    """
    from services.gateway.ai.pdf_export import build_timetable_pdf

    pdf_bytes = await build_timetable_pdf(tenant.id, academic_year)

    filename = f"timetable_{tenant.slug}_{academic_year}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
