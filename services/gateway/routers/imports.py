from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import AcademicYear, Class, ImportBatch, ImportRowResult, Student, StudentEnrollment, StudentParent, Subject, Teacher, TeacherSubject, Tenant, User

router = APIRouter(prefix="/leadership/imports", tags=["Import History"])
SUPPORTED_ENTITY_TYPES = {"subjects", "classes", "teachers", "students", "parents"}
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "subjects": {"code", "name"},
    "classes": {"grade", "section", "academic_year"},
    "teachers": {"email", "name"},
    "students": {"name", "grade", "section", "academic_year"},
    "parents": {"name", "email", "phone", "student_code"},
}
ALLOWED_COLUMNS: dict[str, set[str]] = {
    "subjects": {"code", "name"},
    "classes": {"grade", "section", "academic_year"},
    "teachers": {"email", "name", "phone", "employee_id", "subject_codes", "max_weekly_hours"},
    "students": {"name", "student_code", "grade", "section", "academic_year"},
    "parents": {"name", "email", "phone", "whatsapp", "student_code", "relation_type", "preferred_channel"},
}
FILE_SIZE_LIMIT = 1024 * 1024
ROW_COUNT_LIMIT = 5000
SENSITIVE_KEY_RE = re.compile(r"(password|secret|token|hash|credential)", re.IGNORECASE)


@dataclass
class ParsedCSV:
    filename: str
    sha256: str
    rows: list[dict[str, str]]
    columns: list[str]



def _now() -> datetime:
    return datetime.now(timezone.utc)



def _sanitize_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    name = PurePath(filename).name.replace("\x00", "")
    return name[:255] or None



def _supported_entity_type(entity_type: str) -> str:
    value = entity_type.strip().lower()
    if value not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity type.")
    return value



def _parse_csv_bytes(content: bytes, filename: str | None) -> ParsedCSV:
    if len(content) > FILE_SIZE_LIMIT:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="CSV file is too large.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CSV must be valid UTF-8.") from None
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CSV file is empty or malformed.")
    columns = [name.strip().lower() for name in reader.fieldnames if name is not None]
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if raw_row is None:
            continue
        row: dict[str, str] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            row[key.strip().lower()] = (value or "").strip()
        if any(row.values()):
            rows.append(row)
    if not rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CSV file is empty or malformed.")
    if len(rows) > ROW_COUNT_LIMIT:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="CSV row limit exceeded.")
    return ParsedCSV(filename=_sanitize_filename(filename) or "import.csv", sha256=hashlib.sha256(content).hexdigest(), rows=rows, columns=columns)



def _validate_columns(entity_type: str, columns: list[str]) -> None:
    required = REQUIRED_COLUMNS[entity_type]
    allowed = ALLOWED_COLUMNS[entity_type]
    column_set = set(columns)
    missing = sorted(required - column_set)
    if missing:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Missing required columns: {', '.join(missing)}")
    unknown = sorted(column_set - allowed)
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown columns: {', '.join(unknown)}")



def _normalized_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        clean_key = key.strip().lower()
        if SENSITIVE_KEY_RE.search(clean_key):
            continue
        normalized[clean_key] = value.strip() if isinstance(value, str) else value
    return normalized



def _row_payload(
    *,
    row_number: int,
    status_value: str,
    action: str,
    entity_reference_id: uuid.UUID | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    field_errors: dict[str, Any] | None = None,
    normalized_data: dict[str, Any] | None = None,
    row_data: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "status": status_value,
        "action": action,
        "entity_reference_id": str(entity_reference_id) if entity_reference_id else None,
        "error_code": error_code,
        "error_message": error_message,
        "field_errors": field_errors or {},
        "normalized_data": normalized_data or {},
        "row_data": row_data or {},
    }


async def _preview_subjects(rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        code = row.get("code", "").strip().upper()
        name = row.get("name", "").strip()
        normalized = {"code": code, "name": name}
        if not code or not name:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="missing_required_field", error_message="code and name are required.", field_errors={k: "required" for k in ["code", "name"] if not row.get(k)}, normalized_data=normalized, row_data=row))
            continue
        if code in seen_codes:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", error_code="duplicate_in_file", error_message=f"Duplicate subject code in file: {code}", field_errors={"code": "duplicate_in_file"}, normalized_data=normalized, row_data=row))
            continue
        seen_codes.add(code)
        existing = await db.scalar(select(Subject.id).where(Subject.tenant_id == tenant.id, Subject.code == code))
        if existing is not None:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", entity_reference_id=existing, error_code="duplicate_existing_record", error_message=f"Subject already exists: {code}", field_errors={"code": "already_exists"}, normalized_data=normalized, row_data=row))
            continue
        results.append(_row_payload(row_number=index, status_value="valid", action="create", normalized_data=normalized, row_data=row))
    return results


async def _preview_classes(rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows, start=1):
        grade = row.get("grade", "").strip()
        section = row.get("section", "").strip()
        academic_year = row.get("academic_year", "").strip()
        normalized = {"grade": grade, "section": section, "academic_year": academic_year}
        missing = {key: "required" for key in ["grade", "section", "academic_year"] if not row.get(key)}
        if missing:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="missing_required_field", error_message="grade, section and academic_year are required.", field_errors=missing, normalized_data=normalized, row_data=row))
            continue
        key = (grade, section, academic_year)
        if key in seen:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", error_code="duplicate_in_file", error_message=f"Duplicate class in file: {grade} {section} ({academic_year})", field_errors={"identity": "duplicate_in_file"}, normalized_data=normalized, row_data=row))
            continue
        seen.add(key)
        existing = await db.scalar(select(Class.id).where(Class.tenant_id == tenant.id, Class.grade == grade, Class.section == section, Class.academic_year == academic_year))
        if existing is not None:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", entity_reference_id=existing, error_code="duplicate_existing_record", error_message=f"Class already exists: {grade} {section} ({academic_year})", field_errors={"identity": "already_exists"}, normalized_data=normalized, row_data=row))
            continue
        results.append(_row_payload(row_number=index, status_value="valid", action="create", normalized_data=normalized, row_data=row))
    return results


async def _preview_teachers(rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        email = row.get("email", "").strip().lower()
        name = row.get("name", "").strip()
        phone = row.get("phone", "").strip() or None
        employee_id = row.get("employee_id", "").strip() or None
        subject_codes = [code.strip().upper() for code in (row.get("subject_codes", "") or "").split(",") if code.strip()]
        try:
            max_weekly_hours = int(row.get("max_weekly_hours") or 20)
        except ValueError:
            max_weekly_hours = 20
        normalized = _normalized_row({**row, "email": email, "name": name, "phone": phone or "", "employee_id": employee_id or "", "subject_codes": ",".join(subject_codes), "max_weekly_hours": str(max_weekly_hours)})
        if not email or not name:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="missing_required_field", error_message="email and name are required.", field_errors={k: "required" for k in ["email", "name"] if not row.get(k)}, normalized_data=normalized, row_data=row))
            continue
        if email in seen:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", error_code="duplicate_in_file", error_message=f"Duplicate teacher email in file: {email}", field_errors={"email": "duplicate_in_file"}, normalized_data=normalized, row_data=row))
            continue
        seen.add(email)
        existing = await db.scalar(select(User.id).where(User.tenant_id == tenant.id, User.email == email))
        if existing is not None:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", entity_reference_id=existing, error_code="duplicate_existing_record", error_message=f"Teacher already exists: {email}", field_errors={"email": "already_exists"}, normalized_data=normalized, row_data=row))
            continue
        unknown_subjects = []
        for code in subject_codes:
            subject = await db.scalar(select(Subject.id).where(Subject.tenant_id == tenant.id, Subject.code == code))
            if subject is None:
                unknown_subjects.append(code)
        if unknown_subjects:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="subject_not_found", error_message=f"Subject code not found: {', '.join(unknown_subjects)}", field_errors={"subject_codes": "unknown_subject_code"}, normalized_data=normalized, row_data=row))
            continue
        results.append(_row_payload(row_number=index, status_value="valid", action="create", normalized_data=normalized, row_data=row))
    return results


async def _preview_students(rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        name = row.get("name", "").strip()
        student_code = row.get("student_code", "").strip() or None
        grade = row.get("grade", "").strip()
        section = row.get("section", "").strip()
        academic_year = row.get("academic_year", "").strip()
        normalized = {"name": name, "student_code": student_code, "grade": grade, "section": section, "academic_year": academic_year}
        missing = {key: "required" for key in ["name", "grade", "section", "academic_year"] if not row.get(key)}
        if missing:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="missing_required_field", error_message="name, grade, section and academic_year are required.", field_errors=missing, normalized_data=normalized, row_data=row))
            continue
        klass = await db.scalar(select(Class).where(Class.tenant_id == tenant.id, Class.grade == grade, Class.section == section, Class.academic_year == academic_year, Class.is_active.is_(True)))
        if klass is None:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="class_not_found", error_message=f"Class not found: {grade} / {section} ({academic_year})", field_errors={"class": "not_found"}, normalized_data=normalized, row_data=row))
            continue
        if student_code:
            if student_code in seen_codes:
                results.append(_row_payload(row_number=index, status_value="conflict", action="skip", error_code="duplicate_in_file", error_message=f"Duplicate student_code in file: {student_code}", field_errors={"student_code": "duplicate_in_file"}, normalized_data=normalized, row_data=row))
                continue
            seen_codes.add(student_code)
            existing_student = await db.scalar(select(Student).where(Student.tenant_id == tenant.id, Student.student_code == student_code))
            if existing_student is not None:
                active_enrollment = await db.scalar(select(StudentEnrollment.id).where(StudentEnrollment.tenant_id == tenant.id, StudentEnrollment.student_id == existing_student.id, StudentEnrollment.academic_year_id == klass.academic_year_id, StudentEnrollment.status == "active"))
                if active_enrollment is not None and existing_student.class_id != klass.id:
                    results.append(_row_payload(row_number=index, status_value="conflict", action="skip", entity_reference_id=existing_student.id, error_code="active_enrollment_conflict", error_message="Student already has an active enrollment in another class for this year.", field_errors={"student_code": "active_enrollment_conflict"}, normalized_data=normalized, row_data=row))
                    continue
                if existing_student.class_id == klass.id:
                    results.append(_row_payload(row_number=index, status_value="skipped", action="skip", entity_reference_id=existing_student.id, error_code="already_assigned", error_message="Student already in this class.", normalized_data=normalized, row_data=row))
                    continue
                results.append(_row_payload(row_number=index, status_value="valid", action="update", entity_reference_id=existing_student.id, normalized_data=normalized, row_data=row))
                continue
        results.append(_row_payload(row_number=index, status_value="valid", action="create", normalized_data=normalized, row_data=row))
    return results


async def _preview_parents(rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=1):
        name = row.get("name", "").strip()
        email = row.get("email", "").strip().lower()
        phone = row.get("phone", "").strip()
        whatsapp = row.get("whatsapp", "").strip() or None
        student_code = row.get("student_code", "").strip()
        relation_type = row.get("relation_type", "").strip() or "parent"
        preferred_channel = row.get("preferred_channel", "").strip().lower() or "whatsapp"
        normalized = {"name": name, "email": email, "phone": phone, "whatsapp": whatsapp, "student_code": student_code, "relation_type": relation_type, "preferred_channel": preferred_channel}
        missing = {key: "required" for key in ["name", "email", "phone", "student_code"] if not row.get(key)}
        if missing:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="missing_required_field", error_message="name, email, phone and student_code are required.", field_errors=missing, normalized_data=normalized, row_data=row))
            continue
        student = await db.scalar(select(Student.id).where(Student.tenant_id == tenant.id, Student.student_code == student_code))
        if student is None:
            results.append(_row_payload(row_number=index, status_value="invalid", action="none", error_code="student_not_found", error_message=f"Student not found: {student_code}", field_errors={"student_code": "not_found"}, normalized_data=normalized, row_data=row))
            continue
        parent = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
        if (email, student_code) in seen_links:
            results.append(_row_payload(row_number=index, status_value="conflict", action="skip", error_code="duplicate_in_file", error_message=f"Duplicate parent/student link in file: {email} -> {student_code}", field_errors={"link": "duplicate_in_file"}, normalized_data=normalized, row_data=row))
            continue
        seen_links.add((email, student_code))
        if parent is None:
            results.append(_row_payload(row_number=index, status_value="valid", action="create", normalized_data=normalized, row_data=row))
            continue
        link_exists = await db.scalar(select(StudentParent.student_id).where(StudentParent.student_id == student, StudentParent.parent_id == parent.id))
        if link_exists:
            results.append(_row_payload(row_number=index, status_value="skipped", action="skip", entity_reference_id=parent.id, error_code="already_linked", error_message=f"Parent already linked to student {student_code}.", normalized_data=normalized, row_data=row))
            continue
        results.append(_row_payload(row_number=index, status_value="valid", action="create", entity_reference_id=parent.id, normalized_data=normalized, row_data=row))
    return results


async def _preview_rows(entity_type: str, rows: list[dict[str, str]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    if entity_type == "subjects":
        return await _preview_subjects(rows, tenant, db)
    if entity_type == "classes":
        return await _preview_classes(rows, tenant, db)
    if entity_type == "teachers":
        return await _preview_teachers(rows, tenant, db)
    if entity_type == "students":
        return await _preview_students(rows, tenant, db)
    if entity_type == "parents":
        return await _preview_parents(rows, tenant, db)
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity type.")


async def _apply_rows(entity_type: str, rows: list[dict[str, Any]], tenant: Tenant, db: AsyncSession) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for row in rows:
        normalized = row["normalized_data"]
        if row["status"] in {"invalid", "conflict"}:
            applied.append(row)
            continue
        if entity_type == "subjects":
            if row["action"] == "create":
                item = Subject(id=uuid.uuid4(), tenant_id=tenant.id, code=normalized["code"], name=normalized["name"])
                db.add(item)
                applied.append({**row, "status": "created", "entity_reference_id": item.id})
            else:
                applied.append({**row, "status": "skipped"})
        elif entity_type == "classes":
            if row["action"] == "create":
                item = Class(id=uuid.uuid4(), tenant_id=tenant.id, grade=normalized["grade"], section=normalized["section"], academic_year=normalized["academic_year"])
                db.add(item)
                applied.append({**row, "status": "created", "entity_reference_id": item.id})
            else:
                applied.append({**row, "status": "skipped"})
        elif entity_type == "teachers":
            if row["action"] == "create":
                user = User(id=uuid.uuid4(), tenant_id=tenant.id, name=normalized["name"], email=normalized["email"], phone=normalized.get("phone") or None, role="teacher", preferred_channel="whatsapp")
                db.add(user)
                await db.flush()
                teacher = Teacher(id=uuid.uuid4(), tenant_id=tenant.id, user_id=user.id, employee_id=normalized.get("employee_id") or None, max_weekly_hours=int(normalized.get("max_weekly_hours") or 20))
                db.add(teacher)
                await db.flush()
                for code in [item.strip().upper() for item in (normalized.get("subject_codes") or "").split(",") if item.strip()]:
                    subject_id = await db.scalar(select(Subject.id).where(Subject.tenant_id == tenant.id, Subject.code == code))
                    if subject_id:
                        db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject_id))
                applied.append({**row, "status": "created", "entity_reference_id": teacher.id})
            else:
                applied.append({**row, "status": "skipped"})
        elif entity_type == "students":
            klass = await db.scalar(select(Class).where(Class.tenant_id == tenant.id, Class.grade == normalized["grade"], Class.section == normalized["section"], Class.academic_year == normalized["academic_year"]))
            if row["action"] == "create":
                student = Student(id=uuid.uuid4(), tenant_id=tenant.id, class_id=klass.id, name=normalized["name"], student_code=normalized.get("student_code") or None)
                db.add(student)
                await db.flush()
                if klass.campus_id is not None and klass.academic_year_id is not None and klass.grade_level_id is not None:
                    academic_year = await db.scalar(select(AcademicYear).where(AcademicYear.id == klass.academic_year_id, AcademicYear.tenant_id == tenant.id))
                    if academic_year is not None:
                        db.add(StudentEnrollment(id=uuid.uuid4(), tenant_id=tenant.id, academic_year_id=klass.academic_year_id, student_id=student.id, class_id=klass.id, grade_level_id=klass.grade_level_id, status="active", enrolled_on=academic_year.start_date, exited_on=None, exit_reason=None))
                applied.append({**row, "status": "created", "entity_reference_id": student.id})
            elif row["action"] == "update":
                student = await db.scalar(select(Student).where(Student.tenant_id == tenant.id, Student.student_code == normalized.get("student_code")))
                if student is None:
                    applied.append({**row, "status": "failed", "error_code": "missing_existing_record", "error_message": "Student record not found during commit."})
                else:
                    student.class_id = klass.id
                    applied.append({**row, "status": "updated", "entity_reference_id": student.id})
            else:
                applied.append({**row, "status": "skipped"})
        elif entity_type == "parents":
            if row["action"] == "create":
                student_id = await db.scalar(select(Student.id).where(Student.tenant_id == tenant.id, Student.student_code == normalized["student_code"]))
                if student_id is None:
                    applied.append({**row, "status": "failed", "error_code": "missing_student", "error_message": "Student not found during commit."})
                    continue
                parent = User(id=uuid.uuid4(), tenant_id=tenant.id, name=normalized["name"], email=normalized["email"], phone=normalized.get("phone") or normalized.get("whatsapp") or None, role="parent", preferred_channel=normalized.get("preferred_channel") or "whatsapp")
                db.add(parent)
                await db.flush()
                db.add(StudentParent(student_id=student_id, parent_id=parent.id, relation_type=normalized.get("relation_type") or "parent"))
                applied.append({**row, "status": "created", "entity_reference_id": parent.id})
            elif row["action"] == "update":
                parent = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == normalized["email"]))
                if parent is None:
                    applied.append({**row, "status": "failed", "error_code": "missing_existing_record", "error_message": "Parent record not found during commit."})
                else:
                    applied.append({**row, "status": "updated", "entity_reference_id": parent.id})
            else:
                applied.append({**row, "status": "skipped"})
    return applied



def _batch_payload(batch: ImportBatch) -> dict[str, Any]:
    return {
        "id": str(batch.id),
        "tenant_id": str(batch.tenant_id),
        "entity_type": batch.entity_type,
        "original_filename": batch.original_filename,
        "file_sha256": batch.file_sha256,
        "status": batch.status,
        "mode": batch.mode,
        "created_by_user_id": str(batch.created_by_user_id),
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "created_rows": batch.created_rows,
        "updated_rows": batch.updated_rows,
        "skipped_rows": batch.skipped_rows,
        "conflict_rows": batch.conflict_rows,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "committed_at": batch.committed_at,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }



def _row_model_payload(row: ImportRowResult) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "import_batch_id": str(row.import_batch_id),
        "row_number": row.row_number,
        "status": row.status,
        "action": row.action,
        "entity_reference_id": str(row.entity_reference_id) if row.entity_reference_id else None,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "field_errors": row.field_errors,
        "normalized_data": row.normalized_data,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }



def _summary_payload(batches: list[ImportBatch]) -> dict[str, Any]:
    payload = {"total_batches": len(batches), "by_entity_type": {}, "by_status": {}, "by_mode": {}}
    for batch in batches:
        payload["by_entity_type"][batch.entity_type] = payload["by_entity_type"].get(batch.entity_type, 0) + 1
        payload["by_status"][batch.status] = payload["by_status"].get(batch.status, 0) + 1
        payload["by_mode"][batch.mode] = payload["by_mode"].get(batch.mode, 0) + 1
    return payload


async def _load_batch(db: AsyncSession, tenant_id: uuid.UUID, batch_id: uuid.UUID, *, lock: bool = False) -> ImportBatch | None:
    stmt = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.tenant_id == tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def _create_preview_batch(*, tenant: Tenant, actor: User, db: AsyncSession, entity_type: str, file: UploadFile) -> dict[str, Any]:
    await set_tenant_context(db, tenant.id)
    parsed = _parse_csv_bytes(await file.read(), file.filename)
    _validate_columns(entity_type, parsed.columns)
    row_results = await _preview_rows(entity_type, parsed.rows, tenant, db)
    batch = ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        entity_type=entity_type,
        original_filename=parsed.filename,
        file_sha256=parsed.sha256,
        status="preview_ready",
        mode="preview",
        created_by_user_id=actor.id,
        total_rows=len(parsed.rows),
        valid_rows=sum(1 for row in row_results if row["status"] == "valid"),
        invalid_rows=sum(1 for row in row_results if row["status"] == "invalid"),
        created_rows=0,
        updated_rows=0,
        skipped_rows=sum(1 for row in row_results if row["status"] == "skipped"),
        conflict_rows=sum(1 for row in row_results if row["status"] == "conflict"),
        started_at=_now(),
        completed_at=_now(),
        committed_at=None,
    )
    db.add(batch)
    await db.flush()
    for row in row_results:
        db.add(
            ImportRowResult(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                import_batch_id=batch.id,
                row_number=row["row_number"],
                status=row["status"],
                action=row["action"],
                entity_reference_id=uuid.UUID(row["entity_reference_id"]) if row["entity_reference_id"] else None,
                error_code=row["error_code"],
                error_message=row["error_message"],
                field_errors=row["field_errors"],
                normalized_data=row["normalized_data"],
                row_data=row["row_data"],
                created_at=_now(),
                updated_at=_now(),
            )
        )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="data_import.previewed",
        entity_type="ImportBatch",
        entity_id=batch.id,
        actor_id=actor.id,
        details={"entity_type": entity_type, "filename": parsed.filename, "sha256": parsed.sha256, "rows": len(parsed.rows)},
    )
    await db.commit()
    await db.refresh(batch)
    return {"batch": _batch_payload(batch), "rows": row_results}


async def _commit_batch(*, tenant: Tenant, actor: User, db: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
    await set_tenant_context(db, tenant.id)
    batch = await _load_batch(db, tenant.id, batch_id, lock=True)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    if batch.status in {"cancelled", "completed", "completed_with_errors", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import batch is already finished.")
    if batch.status == "committing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import batch is already committing.")
    if batch.status != "preview_ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import batch must be preview_ready before commit.")
    batch.status = "committing"
    await db.flush()
    row_models = (await db.execute(select(ImportRowResult).where(ImportRowResult.import_batch_id == batch.id, ImportRowResult.tenant_id == tenant.id).order_by(ImportRowResult.row_number.asc()))).scalars().all()
    rows = [
        {
            "row_number": row.row_number,
            "status": row.status,
            "action": row.action,
            "entity_reference_id": str(row.entity_reference_id) if row.entity_reference_id else None,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "field_errors": row.field_errors,
            "normalized_data": row.normalized_data,
            "row_data": row.row_data,
        }
        for row in row_models
    ]
    applied = await _apply_rows(batch.entity_type, rows, tenant, db)
    batch.created_rows = sum(1 for row in applied if row["status"] == "created")
    batch.updated_rows = sum(1 for row in applied if row["status"] == "updated")
    batch.skipped_rows = sum(1 for row in applied if row["status"] == "skipped")
    batch.invalid_rows = sum(1 for row in applied if row["status"] == "invalid")
    batch.conflict_rows = sum(1 for row in applied if row["status"] == "conflict")
    batch.valid_rows = batch.created_rows + batch.updated_rows + batch.skipped_rows
    batch.total_rows = len(applied)
    batch.completed_at = _now()
    batch.committed_at = _now()
    batch.status = "completed" if not any(row["status"] == "failed" for row in applied) else "completed_with_errors"
    for row_model, applied_row in zip(row_models, applied, strict=False):
        row_model.status = applied_row["status"]
        row_model.action = applied_row.get("action", row_model.action)
        if applied_row.get("entity_reference_id"):
            row_model.entity_reference_id = uuid.UUID(str(applied_row["entity_reference_id"]))
        row_model.error_code = applied_row.get("error_code")
        row_model.error_message = applied_row.get("error_message")
        row_model.field_errors = applied_row.get("field_errors") or row_model.field_errors
        row_model.normalized_data = applied_row.get("normalized_data") or row_model.normalized_data
        row_model.updated_at = _now()
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="data_import.committed",
        entity_type="ImportBatch",
        entity_id=batch.id,
        actor_id=actor.id,
        details={"entity_type": batch.entity_type, "created_rows": batch.created_rows, "updated_rows": batch.updated_rows, "skipped_rows": batch.skipped_rows},
    )
    await db.commit()
    await db.refresh(batch)
    return {"batch": _batch_payload(batch), "rows": [_row_model_payload(row) for row in row_models]}


@router.post("/preview", summary="Preview CSV import")
async def preview_import(
    entity_type: str = Form(...),
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _create_preview_batch(tenant=tenant, actor=actor, db=db, entity_type=_supported_entity_type(entity_type), file=file)


@router.post("/{batch_id}/commit", summary="Commit CSV import")
async def commit_import(
    batch_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    return await _commit_batch(tenant=tenant, actor=actor, db=db, batch_id=batch_id)


@router.get("", summary="List import batches")
async def list_import_batches(
    entity_type: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    stmt = select(ImportBatch).where(ImportBatch.tenant_id == tenant.id)
    if entity_type is not None:
        stmt = stmt.where(ImportBatch.entity_type == _supported_entity_type(entity_type))
    batches = (await db.execute(stmt.order_by(ImportBatch.created_at.desc()))).scalars().all()
    return [_batch_payload(batch) for batch in batches]


@router.get("/summary", summary="Import summary")
async def import_summary(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    batches = (await db.execute(select(ImportBatch).where(ImportBatch.tenant_id == tenant.id))).scalars().all()
    return _summary_payload(batches)


@router.get("/{batch_id}", summary="Get import batch")
async def get_import_batch(
    batch_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    batch = await _load_batch(db, tenant.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    return _batch_payload(batch)


@router.get("/{batch_id}/rows", summary="Get import batch rows")
async def get_import_batch_rows(
    batch_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    batch = await _load_batch(db, tenant.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    rows = (await db.execute(select(ImportRowResult).where(ImportRowResult.import_batch_id == batch_id, ImportRowResult.tenant_id == tenant.id).order_by(ImportRowResult.row_number.asc()))).scalars().all()
    return [_row_model_payload(row) for row in rows]


@router.post("/{batch_id}/cancel", summary="Cancel import batch")
async def cancel_import_batch(
    batch_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    batch = await _load_batch(db, tenant.id, batch_id, lock=True)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    if batch.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import batch is already finished.")
    if batch.status == "committing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import batch is currently committing.")
    batch.status = "cancelled"
    batch.completed_at = _now()
    await db.commit()
    await db.refresh(batch)
    return _batch_payload(batch)


@router.get("/{batch_id}/errors.csv", summary="Download import errors CSV")
async def export_import_errors_csv(
    batch_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    await set_tenant_context(db, tenant.id)
    batch = await _load_batch(db, tenant.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    rows = (await db.execute(select(ImportRowResult).where(ImportRowResult.import_batch_id == batch_id, ImportRowResult.tenant_id == tenant.id, ImportRowResult.status.in_(["invalid", "conflict", "failed"])).order_by(ImportRowResult.row_number.asc()))).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_number", "status", "error_code", "error_message"])
    for row in rows:
        writer.writerow([row.row_number, row.status, row.error_code or "", row.error_message or ""])
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="import-errors-{batch_id}.csv"'})
