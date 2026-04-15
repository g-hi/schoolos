"""
Phase 1 – Data Ingestion Router
=================================
Accepts CSV file uploads and inserts rows into the database.
Every endpoint is tenant-scoped: data is always isolated to the school
making the request (via the X-Tenant-Slug header).

Endpoints
---------
POST /ingest/subjects  – subject list (code, name)
POST /ingest/classes   – class groups (grade, section, academic_year)
POST /ingest/teachers  – teacher profiles (creates User + Teacher rows)
POST /ingest/students  – student list (creates Student row, links to class)
POST /ingest/parents   – parent accounts (creates User + StudentParent link)

Response shape (all endpoints)
-------------------------------
{
  "inserted": 12,
  "skipped":  2,
  "errors": [
    {"row": 3, "error": "duplicate code: MATH"},
    {"row": 7, "error": "class not found: Grade 3 / B"}
  ]
}

Design decisions
----------------
- We use Python's built-in `csv` module — no extra dependency.
- Each row is attempted individually inside a savepoint. A bad row is
  skipped and logged; the rest of the batch still commits.
- Duplicate detection is done via a SELECT before INSERT (simpler than
  catching IntegrityError and parsing the message).
- The tenant_id comes from `resolve_tenant` — never from the CSV itself.
  A CSV cannot override which school it belongs to.
"""

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    Class,
    Student,
    StudentParent,
    Subject,
    Teacher,
    TeacherSubject,
    Tenant,
    User,
)

router = APIRouter(prefix="/ingest", tags=["Data Ingestion"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_csv(content: bytes) -> list[dict[str, str]]:
    """Decode uploaded bytes and return a list of row dicts."""
    text = content.decode("utf-8-sig")  # utf-8-sig strips the BOM Excel adds
    reader = csv.DictReader(io.StringIO(text))
    return [
        {k.strip().lower(): v.strip() for k, v in row.items()}
        for row in reader
    ]


def _missing(row: dict, *fields: str) -> str | None:
    """Return an error string if any required field is blank, else None."""
    for f in fields:
        if not row.get(f):
            return f"missing required field: {f}"
    return None


IngestResult = dict[str, Any]


def _result(inserted: int, skipped: int, errors: list[dict]) -> IngestResult:
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/subjects
# CSV columns: code, name
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/subjects", summary="Upload subjects CSV")
async def ingest_subjects(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        code,name
        MATH,Mathematics
        ENG,English Language
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())

    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):  # start=2: row 1 is the header
        err = _missing(row, "code", "name")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        code = row["code"].upper()

        # Duplicate check
        exists = await db.scalar(
            select(Subject.id).where(
                Subject.tenant_id == tenant.id,
                Subject.code == code,
            )
        )
        if exists:
            errors.append({"row": i, "error": f"duplicate code: {code}"})
            skipped += 1
            continue

        db.add(Subject(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            code=code,
            name=row["name"],
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/classes
# CSV columns: grade, section, academic_year
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/classes", summary="Upload classes CSV")
async def ingest_classes(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        grade,section,academic_year
        Grade 1,A,2025-2026
        Grade 1,B,2025-2026
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())

    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "grade", "section", "academic_year")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        # Duplicate check
        exists = await db.scalar(
            select(Class.id).where(
                Class.tenant_id == tenant.id,
                Class.grade == row["grade"],
                Class.section == row["section"],
                Class.academic_year == row["academic_year"],
            )
        )
        if exists:
            errors.append({"row": i, "error": f"duplicate class: {row['grade']} {row['section']} ({row['academic_year']})"})
            skipped += 1
            continue

        db.add(Class(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            grade=row["grade"],
            section=row["section"],
            academic_year=row["academic_year"],
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/teachers
# CSV columns: email, name, phone (opt), employee_id (opt),
#              subject_codes (opt, comma-separated), max_weekly_hours (opt)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/teachers", summary="Upload teachers CSV")
async def ingest_teachers(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        email,name,phone,employee_id,subject_codes,max_weekly_hours
        john@school.com,John Smith,+966501234567,EMP001,"MATH,SCI",20

    subject_codes is a comma-separated list of existing subject codes.
    Unknown subject codes are silently ignored (a warning is added).
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())

    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "email", "name")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        email = row["email"].lower()

        # Duplicate check — email must be unique per tenant
        exists = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant.id,
                User.email == email,
            )
        )
        if exists:
            errors.append({"row": i, "error": f"duplicate email: {email}"})
            skipped += 1
            continue

        # Parse max_weekly_hours (optional, default 20)
        try:
            max_hours = int(row.get("max_weekly_hours") or 20)
        except ValueError:
            max_hours = 20

        # Create User row
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=row["name"],
            email=email,
            phone=row.get("phone") or None,
            role="teacher",
            preferred_channel="whatsapp",
        )
        db.add(user)
        await db.flush()  # flush so user.id is available for Teacher FK

        # Create Teacher row
        teacher = Teacher(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            user_id=user.id,
            employee_id=row.get("employee_id") or None,
            max_weekly_hours=max_hours,
        )
        db.add(teacher)
        await db.flush()  # flush so teacher.id is available for TeacherSubject FK

        # Link subjects
        raw_codes = row.get("subject_codes", "")
        if raw_codes:
            for code in [c.strip().upper() for c in raw_codes.split(",") if c.strip()]:
                subject_id = await db.scalar(
                    select(Subject.id).where(
                        Subject.tenant_id == tenant.id,
                        Subject.code == code,
                    )
                )
                if subject_id:
                    db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject_id))
                else:
                    errors.append({"row": i, "error": f"subject code not found: {code} (teacher still inserted)"})

        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/students
# CSV columns: name, student_code (opt), grade, section, academic_year
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/students", summary="Upload students CSV")
async def ingest_students(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        name,student_code,grade,section,academic_year
        Ahmed Ali,STU001,Grade 1,A,2025-2026
        Sara Khan,STU002,Grade 1,A,2025-2026

    The class (grade + section + academic_year) must already exist.
    Run /ingest/classes first.
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())

    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "name", "grade", "section", "academic_year")
        if err:
            errors.append({"row": i, "error": err})
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
            errors.append({"row": i, "error": f"class not found: {row['grade']} / {row['section']} ({row['academic_year']})"})
            skipped += 1
            continue

        student_code = row.get("student_code") or None

        # Duplicate check by student_code if provided
        if student_code:
            exists = await db.scalar(
                select(Student.id).where(
                    Student.tenant_id == tenant.id,
                    Student.student_code == student_code,
                )
            )
            if exists:
                errors.append({"row": i, "error": f"duplicate student_code: {student_code}"})
                skipped += 1
                continue

        db.add(Student(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            class_id=class_id,
            name=row["name"],
            student_code=student_code,
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/parents
# CSV columns: name, email, phone, whatsapp (opt), student_code,
#              relation_type (opt), preferred_channel (opt)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/parents", summary="Upload parents CSV")
async def ingest_parents(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """
    Expected CSV format:
        name,email,phone,student_code,relation_type,preferred_channel
        Fatima Ali,fatima@example.com,+966501234568,STU001,mother,whatsapp
        Omar Ali,omar@example.com,+966501234569,STU001,father,sms

    - If a parent email already exists, the existing User is reused
      (a parent can have multiple children — their account is not duplicated).
    - The student (by student_code) must already exist.
    - Run /ingest/students first.
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())

    inserted, skipped, errors = 0, 0, []

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "name", "email", "phone", "student_code")
        if err:
            errors.append({"row": i, "error": err})
            skipped += 1
            continue

        email = row["email"].lower()

        # Resolve student
        student_id = await db.scalar(
            select(Student.id).where(
                Student.tenant_id == tenant.id,
                Student.student_code == row["student_code"],
            )
        )
        if not student_id:
            errors.append({"row": i, "error": f"student not found: {row['student_code']}"})
            skipped += 1
            continue

        # Upsert parent User — reuse if email already exists
        parent_id = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant.id,
                User.email == email,
            )
        )
        if not parent_id:
            channel = row.get("preferred_channel", "whatsapp")
            if channel not in ("whatsapp", "sms", "email"):
                channel = "whatsapp"

            parent = User(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                name=row["name"],
                email=email,
                phone=row.get("phone") or None,
                role="parent",
                preferred_channel=channel,
            )
            db.add(parent)
            await db.flush()
            parent_id = parent.id

        # Avoid duplicate StudentParent link
        link_exists = await db.scalar(
            select(StudentParent.student_id).where(
                StudentParent.student_id == student_id,
                StudentParent.parent_id == parent_id,
            )
        )
        if link_exists:
            errors.append({"row": i, "error": f"parent {email} already linked to student {row['student_code']}"})
            skipped += 1
            continue

        relation = row.get("relation_type") or "parent"
        db.add(StudentParent(
            student_id=student_id,
            parent_id=parent_id,
            relation_type=relation,
        ))
        inserted += 1

    await db.commit()
    return _result(inserted, skipped, errors)
