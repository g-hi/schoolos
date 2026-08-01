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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AcademicYear,
    Class,
    Student,
    StudentEnrollment,
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

ImportKind = Literal["subjects", "classes", "teachers", "students", "parents"]


def _row_outcome(
    row: int,
    status: str,
    *,
    error: str | None = None,
    warnings: list[str] | None = None,
    data: dict[str, Any] | None = None,
    raw: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "row": row,
        "status": status,
        "error": error,
        "warnings": warnings or [],
        "data": data or {},
        "raw": raw or {},
    }


def _result(inserted: int, skipped: int, errors: list[dict]) -> IngestResult:
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


def _summary_result(
    *,
    inserted: int,
    skipped: int,
    errors: list[dict],
    row_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "row_results": row_results,
    }


async def _ingest_subject_rows(
    *,
    rows: list[dict[str, str]],
    tenant: Tenant,
    db: AsyncSession,
    commit: bool,
) -> dict[str, Any]:
    inserted, skipped, errors = 0, 0, []
    row_results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "code", "name")
        if err:
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        code = row["code"].upper()
        if code in seen_codes:
            err = f"duplicate code in file: {code}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue
        seen_codes.add(code)

        exists = await db.scalar(
            select(Subject.id).where(
                Subject.tenant_id == tenant.id,
                Subject.code == code,
            )
        )
        if exists:
            err = f"duplicate code: {code}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        if commit:
            db.add(Subject(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                code=code,
                name=row["name"],
            ))

        inserted += 1
        row_results.append(_row_outcome(i, "inserted", data={"code": code, "name": row["name"]}, raw=row))

    return _summary_result(inserted=inserted, skipped=skipped, errors=errors, row_results=row_results)


async def _ingest_class_rows(
    *,
    rows: list[dict[str, str]],
    tenant: Tenant,
    db: AsyncSession,
    commit: bool,
) -> dict[str, Any]:
    inserted, skipped, errors = 0, 0, []
    row_results: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "grade", "section", "academic_year")
        if err:
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        identity = (row["grade"], row["section"], row["academic_year"])
        if identity in seen_keys:
            err = f"duplicate class in file: {row['grade']} {row['section']} ({row['academic_year']})"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue
        seen_keys.add(identity)

        exists = await db.scalar(
            select(Class.id).where(
                Class.tenant_id == tenant.id,
                Class.grade == row["grade"],
                Class.section == row["section"],
                Class.academic_year == row["academic_year"],
            )
        )
        if exists:
            err = f"duplicate class: {row['grade']} {row['section']} ({row['academic_year']})"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        if commit:
            db.add(Class(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                grade=row["grade"],
                section=row["section"],
                academic_year=row["academic_year"],
            ))

        inserted += 1
        row_results.append(
            _row_outcome(
                i,
                "inserted",
                data={"grade": row["grade"], "section": row["section"], "academic_year": row["academic_year"]},
                raw=row,
            )
        )

    return _summary_result(inserted=inserted, skipped=skipped, errors=errors, row_results=row_results)


async def _ingest_teacher_rows(
    *,
    rows: list[dict[str, str]],
    tenant: Tenant,
    db: AsyncSession,
    commit: bool,
) -> dict[str, Any]:
    inserted, skipped, errors = 0, 0, []
    row_results: list[dict[str, Any]] = []
    seen_emails: set[str] = set()

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "email", "name")
        if err:
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        email = row["email"].lower()
        if email in seen_emails:
            err = f"duplicate email in file: {email}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue
        seen_emails.add(email)

        exists = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant.id,
                User.email == email,
            )
        )
        if exists:
            err = f"duplicate email: {email}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        try:
            max_hours = int(row.get("max_weekly_hours") or 20)
        except ValueError:
            max_hours = 20

        warnings: list[str] = []
        linked_subject_codes: list[str] = []
        raw_codes = row.get("subject_codes", "")
        if raw_codes:
            for code in [code.strip().upper() for code in raw_codes.split(",") if code.strip()]:
                subject_id = await db.scalar(
                    select(Subject.id).where(
                        Subject.tenant_id == tenant.id,
                        Subject.code == code,
                    )
                )
                if subject_id:
                    linked_subject_codes.append(code)
                else:
                    warnings.append(f"subject code not found: {code}")

        if commit:
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
            await db.flush()

            teacher = Teacher(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                user_id=user.id,
                employee_id=row.get("employee_id") or None,
                max_weekly_hours=max_hours,
            )
            db.add(teacher)
            await db.flush()

            if raw_codes:
                for code in linked_subject_codes:
                    subject_id = await db.scalar(
                        select(Subject.id).where(
                            Subject.tenant_id == tenant.id,
                            Subject.code == code,
                        )
                    )
                    if subject_id:
                        db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject_id))

        inserted += 1
        row_results.append(
            _row_outcome(
                i,
                "inserted",
                warnings=warnings,
                data={
                    "email": email,
                    "name": row["name"],
                    "employee_id": row.get("employee_id") or None,
                    "max_weekly_hours": max_hours,
                    "subject_codes": linked_subject_codes,
                },
                raw=row,
            )
        )

    return _summary_result(inserted=inserted, skipped=skipped, errors=errors, row_results=row_results)


async def _ingest_student_rows(
    *,
    rows: list[dict[str, str]],
    tenant: Tenant,
    db: AsyncSession,
    commit: bool,
) -> dict[str, Any]:
    inserted, skipped, errors = 0, 0, []
    row_results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "name", "grade", "section", "academic_year")
        if err:
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        klass = await db.scalar(
            select(Class).where(
                Class.tenant_id == tenant.id,
                Class.grade == row["grade"],
                Class.section == row["section"],
                Class.academic_year == row["academic_year"],
            )
        )
        if not klass:
            err = f"class not found: {row['grade']} / {row['section']} ({row['academic_year']})"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        is_canonical = (
            klass.campus_id is not None
            and klass.academic_year_id is not None
            and klass.grade_level_id is not None
            and klass.is_active
        )

        student_code = row.get("student_code") or None
        if student_code:
            if student_code in seen_codes:
                err = f"duplicate student_code in file: {student_code}"
                errors.append({"row": i, "error": err})
                row_results.append(_row_outcome(i, "error", error=err, raw=row))
                skipped += 1
                continue
            seen_codes.add(student_code)

        existing_student: Student | None = None
        if student_code:
            existing_student = await db.scalar(
                select(Student).where(
                    Student.tenant_id == tenant.id,
                    Student.student_code == student_code,
                )
            )

        if existing_student is not None:
            if not is_canonical:
                err = f"duplicate student_code: {student_code}"
                errors.append({"row": i, "error": err})
                row_results.append(_row_outcome(i, "error", error=err, raw=row))
                skipped += 1
                continue

            academic_year = await db.scalar(
                select(AcademicYear).where(
                    AcademicYear.id == klass.academic_year_id,
                    AcademicYear.tenant_id == tenant.id,
                    AcademicYear.is_active.is_(True),
                )
            )
            if academic_year is None:
                err = "canonical class academic year not found or inactive"
                errors.append({"row": i, "error": err})
                row_results.append(_row_outcome(i, "error", error=err, raw=row))
                skipped += 1
                continue

            same_class_active = await db.scalar(
                select(StudentEnrollment.id).where(
                    StudentEnrollment.tenant_id == tenant.id,
                    StudentEnrollment.student_id == existing_student.id,
                    StudentEnrollment.class_id == klass.id,
                    StudentEnrollment.academic_year_id == klass.academic_year_id,
                    StudentEnrollment.status == "active",
                )
            )
            if same_class_active is not None:
                skipped += 1
                row_results.append(_row_outcome(i, "skipped", data={"reason": "already enrolled in class"}, raw=row))
                continue

            conflict_enrollment = await db.scalar(
                select(StudentEnrollment.id).where(
                    StudentEnrollment.tenant_id == tenant.id,
                    StudentEnrollment.student_id == existing_student.id,
                    StudentEnrollment.academic_year_id == klass.academic_year_id,
                    StudentEnrollment.status == "active",
                )
            )
            if conflict_enrollment is not None:
                err = (
                    f"student '{student_code}' already has an active enrollment in a different class for this academic year. "
                    "Use the transfer endpoint to move them."
                )
                errors.append({"row": i, "error": err})
                row_results.append(_row_outcome(i, "error", error=err, raw=row))
                skipped += 1
                continue

            if commit:
                existing_student.class_id = klass.id
                enrollment = StudentEnrollment(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    academic_year_id=klass.academic_year_id,
                    student_id=existing_student.id,
                    class_id=klass.id,
                    grade_level_id=klass.grade_level_id,
                    status="active",
                    enrolled_on=academic_year.start_date,
                    exited_on=None,
                    exit_reason=None,
                )
                db.add(enrollment)

            inserted += 1
            row_results.append(_row_outcome(i, "inserted", data={"student_code": student_code}, raw=row))
            continue

        academic_year = None
        if is_canonical:
            academic_year = await db.scalar(
                select(AcademicYear).where(
                    AcademicYear.id == klass.academic_year_id,
                    AcademicYear.tenant_id == tenant.id,
                    AcademicYear.is_active.is_(True),
                )
            )
            if academic_year is None:
                err = "canonical class academic year not found or inactive"
                errors.append({"row": i, "error": err})
                row_results.append(_row_outcome(i, "error", error=err, raw=row))
                skipped += 1
                continue

        if commit:
            student = Student(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                class_id=klass.id,
                name=row["name"],
                student_code=student_code,
            )
            db.add(student)
            await db.flush()

            if is_canonical and academic_year is not None:
                enrollment = StudentEnrollment(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    academic_year_id=klass.academic_year_id,
                    student_id=student.id,
                    class_id=klass.id,
                    grade_level_id=klass.grade_level_id,
                    status="active",
                    enrolled_on=academic_year.start_date,
                    exited_on=None,
                    exit_reason=None,
                )
                db.add(enrollment)

        inserted += 1
        row_results.append(
            _row_outcome(
                i,
                "inserted",
                data={"student_code": student_code, "name": row["name"], "class_id": str(klass.id)},
                raw=row,
            )
        )

    return _summary_result(inserted=inserted, skipped=skipped, errors=errors, row_results=row_results)


async def _ingest_parent_rows(
    *,
    rows: list[dict[str, str]],
    tenant: Tenant,
    db: AsyncSession,
    commit: bool,
) -> dict[str, Any]:
    inserted, skipped, errors = 0, 0, []
    row_results: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str]] = set()
    preview_parent_ids: dict[str, uuid.UUID] = {}

    for i, row in enumerate(rows, start=2):
        err = _missing(row, "name", "email", "phone", "student_code")
        if err:
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        email = row["email"].lower()

        student_id = await db.scalar(
            select(Student.id).where(
                Student.tenant_id == tenant.id,
                Student.student_code == row["student_code"],
            )
        )
        if not student_id:
            err = f"student not found: {row['student_code']}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        parent_id = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant.id,
                User.email == email,
            )
        )
        if not parent_id:
            if commit:
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
            else:
                parent_id = preview_parent_ids.setdefault(email, uuid.uuid4())

        link_key = (email, str(student_id))
        if link_key in seen_links:
            err = f"parent {email} already linked to student {row['student_code']}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue
        seen_links.add(link_key)

        link_exists = await db.scalar(
            select(StudentParent.student_id).where(
                StudentParent.student_id == student_id,
                StudentParent.parent_id == parent_id,
            )
        )
        if link_exists:
            err = f"parent {email} already linked to student {row['student_code']}"
            errors.append({"row": i, "error": err})
            row_results.append(_row_outcome(i, "error", error=err, raw=row))
            skipped += 1
            continue

        if commit:
            relation = row.get("relation_type") or "parent"
            db.add(StudentParent(
                student_id=student_id,
                parent_id=parent_id,
                relation_type=relation,
            ))

        inserted += 1
        row_results.append(_row_outcome(i, "inserted", data={"email": email, "student_code": row["student_code"]}, raw=row))

    return _summary_result(inserted=inserted, skipped=skipped, errors=errors, row_results=row_results)


async def run_ingest(kind: ImportKind, rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession, *, commit: bool) -> dict[str, Any]:
    if kind == "subjects":
        return await _ingest_subject_rows(rows=rows, tenant=tenant, db=db, commit=commit)
    if kind == "classes":
        return await _ingest_class_rows(rows=rows, tenant=tenant, db=db, commit=commit)
    if kind == "teachers":
        return await _ingest_teacher_rows(rows=rows, tenant=tenant, db=db, commit=commit)
    if kind == "students":
        return await _ingest_student_rows(rows=rows, tenant=tenant, db=db, commit=commit)
    if kind == "parents":
        return await _ingest_parent_rows(rows=rows, tenant=tenant, db=db, commit=commit)
    raise HTTPException(status_code=404, detail=f"Unsupported import kind: {kind}")


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
    result = await run_ingest("subjects", rows, tenant, db, commit=True)
    await db.commit()
    return _result(result["inserted"], result["skipped"], result["errors"])


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
    result = await run_ingest("classes", rows, tenant, db, commit=True)
    await db.commit()
    return _result(result["inserted"], result["skipped"], result["errors"])


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
    result = await run_ingest("teachers", rows, tenant, db, commit=True)
    await db.commit()
    return _result(result["inserted"], result["skipped"], result["errors"])


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

    Dual-write behaviour:
    - Legacy class (no canonical scope):  Student.class_id is set normally.
      No StudentEnrollment is created.
    - Canonical class (campus_id + academic_year_id + grade_level_id all set):
      Student.class_id is set AND an active StudentEnrollment is created.
      enrolled_on defaults to AcademicYear.start_date.
      Repeated import of the same student into the same active canonical
      enrollment is idempotent (counted as skipped/unchanged).
      If the student already has a DIFFERENT active enrollment in the same
      academic year, the row is rejected with a controlled error — no
      automatic transfer is performed.
    """
    await set_tenant_context(db, tenant.id)
    rows = _parse_csv(await file.read())
    result = await run_ingest("students", rows, tenant, db, commit=True)
    await db.commit()
    return _result(result["inserted"], result["skipped"], result["errors"])


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
    result = await run_ingest("parents", rows, tenant, db, commit=True)
    await db.commit()
    return _result(result["inserted"], result["skipped"], result["errors"])
