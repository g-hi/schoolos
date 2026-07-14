"""
Assessment Review & Marking Studio — REST API router.

Endpoints that require file upload or session CRUD semantics live here.
The LangGraph processing pipeline is triggered via the existing
POST /ai/copilot/run contract (reused, not duplicated).

Tenant isolation: every endpoint filters by tenant_id resolved from
X-Tenant-Slug header. Cross-tenant requests return 404 (not 403)
to avoid information leakage.

Security:
    - File type whitelist enforced before storage
    - File size limit (20 MB default)
    - Raw binaries never stored in DB or graph state
    - Student answer text never logged
    - All teacher approvals/overrides written to AuditLog
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.exam_marking.quality.image_quality import ImageQualityChecker
from services.gateway.ai.exam_marking.schemas import (
    ApproveSubmissionRequest,
    CreateMarkingSessionRequest,
    MarkingSessionResponse,
    PageUploadResponse,
    ProcessSessionRequest,
    SubmitReviewRequest,
    SubmissionSummary,
)
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    AssessmentSubmission,
    AuditLog,
    MarkingSession,
    QuestionResponse,
    ScannedPage,
    Tenant,
)

router = APIRouter(prefix="/ai/exam-marking", tags=["Assessment Review & Marking Studio"])

_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "txt"}
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
_UPLOAD_BASE = Path("tmp_uploads")

_quality_checker = ImageQualityChecker()


def _resolve_teacher(request: Request) -> str:
    return request.headers.get("X-User-Id", "teacher-local")


def _storage_key(tenant_id: str, session_id: str, filename: str) -> str:
    return str(_UPLOAD_BASE / tenant_id / session_id / filename)


async def _save_upload(file: UploadFile, storage_key: str) -> None:
    path = Path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    path.write_bytes(content)


def _validate_file(file: UploadFile) -> str:
    """Validate file type and return extension. Raises 400 on failure."""
    name = file.filename or "unknown"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )
    return ext


def _fmt_dt(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def _session_to_response(s: MarkingSession) -> MarkingSessionResponse:
    return MarkingSessionResponse(
        session_id=str(s.session_id),
        tenant_id=str(s.tenant_id),
        teacher_id=s.teacher_id,
        exam_title=s.exam_title,
        subject=s.subject or "",
        grade=s.grade or "",
        class_name=s.class_name or "",
        curriculum=s.curriculum or "",
        academic_year=s.academic_year or "",
        term=s.term or "",
        exam_date=str(s.exam_date) if s.exam_date else None,
        total_marks=s.total_marks or 0,
        paper_type=s.paper_type,
        input_method=s.input_method,
        language=s.language,
        total_students=s.total_students,
        captured_students=s.captured_students,
        processed_students=s.processed_students,
        pending_students=s.pending_students,
        flagged_students=s.flagged_students,
        approved_students=s.approved_students,
        average_confidence=s.average_confidence,
        status=s.status,
        teacher_notes=s.teacher_notes or "",
        created_at=_fmt_dt(s.created_at),
        updated_at=_fmt_dt(s.updated_at),
    )


# ── Session CRUD ──────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=MarkingSessionResponse, status_code=201)
async def create_session(
    body: CreateMarkingSessionRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new marking session."""
    await set_tenant_context(db, tenant.id)
    teacher_id = _resolve_teacher(request)

    session = MarkingSession(
        tenant_id=tenant.id,
        teacher_id=teacher_id,
        exam_title=body.exam_title,
        subject=body.subject,
        grade=body.grade,
        class_name=body.class_name,
        curriculum=body.curriculum,
        academic_year=body.academic_year,
        term=body.term,
        total_marks=body.total_marks,
        time_allowed_minutes=body.time_allowed_minutes,
        expected_pages_per_student=body.expected_pages_per_student,
        paper_type=body.paper_type,
        input_method=body.input_method,
        language=body.language,
        total_students=body.total_students,
        teacher_notes=body.teacher_notes,
        status="draft",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    db.add(AuditLog(
        tenant_id=tenant.id,
        action="exam_marking.session_created",
        entity_type="marking_session",
        entity_id=session.session_id,
        details={"exam_title": body.exam_title, "teacher_id": teacher_id},
    ))
    await db.commit()

    return _session_to_response(session)


@router.get("/sessions", response_model=list[MarkingSessionResponse])
async def list_sessions(
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all marking sessions for this tenant."""
    await set_tenant_context(db, tenant.id)
    teacher_id = _resolve_teacher(request)

    result = await db.execute(
        select(MarkingSession)
        .where(
            MarkingSession.tenant_id == tenant.id,
            MarkingSession.teacher_id == teacher_id,
        )
        .order_by(MarkingSession.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [_session_to_response(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=MarkingSessionResponse)
async def get_session(
    session_id: str,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a single marking session. Returns 404 for cross-tenant access."""
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(MarkingSession).where(
            MarkingSession.session_id == uuid.UUID(session_id),
            MarkingSession.tenant_id == tenant.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _session_to_response(session)


# ── Page Upload ───────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/pages", response_model=PageUploadResponse, status_code=201)
async def upload_page(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    submission_id: str = Form(default=""),
    page_number: int = Form(default=1),
    student_name: str = Form(default=""),
    student_code: str = Form(default=""),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a single page for a submission within a session.

    File type and size are validated before storage.
    Raw binaries are never stored in the database — only the storage_key path.
    Quality check is performed synchronously and returned in the response.
    """
    await set_tenant_context(db, tenant.id)

    # Validate session ownership (tenant isolation)
    sess_result = await db.execute(
        select(MarkingSession).where(
            MarkingSession.session_id == uuid.UUID(session_id),
            MarkingSession.tenant_id == tenant.id,
        )
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # File validation
    ext = _validate_file(file)
    file_size = 0
    content = await file.read()
    file_size = len(content)
    if file_size > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({file_size} bytes). Maximum {_MAX_FILE_BYTES} bytes.",
        )
    # Reset after read
    await file.seek(0)

    # Resolve or create AssessmentSubmission
    sub_uuid: uuid.UUID | None = None
    if submission_id:
        try:
            sub_uuid = uuid.UUID(submission_id)
        except ValueError:
            pass

    if sub_uuid:
        sub_result = await db.execute(
            select(AssessmentSubmission).where(
                AssessmentSubmission.submission_id == sub_uuid,
                AssessmentSubmission.tenant_id == tenant.id,
            )
        )
        submission = sub_result.scalar_one_or_none()
    else:
        submission = None

    if not submission:
        submission = AssessmentSubmission(
            session_id=session.session_id,
            tenant_id=tenant.id,
            student_name=student_name or f"Student {page_number}",
            student_code=student_code,
            paper_type=session.paper_type,
            status="pending",
        )
        db.add(submission)
        await db.flush()  # get submission_id

    # Store file
    unique_name = f"{uuid.uuid4()}.{ext}"
    key = _storage_key(str(tenant.id), session_id, unique_name)
    # Malware scan extension point (V1: no-op)
    # await malware_scanner.scan(content)
    await _save_upload_bytes(key, content)

    # Quality check
    quality = _quality_checker.check(key, source="upload")

    # Create ScannedPage record
    page = ScannedPage(
        submission_id=submission.submission_id,
        session_id=session.session_id,
        tenant_id=tenant.id,
        page_number=page_number,
        expected_page_count=session.expected_pages_per_student,
        storage_key=key,
        original_filename=file.filename or unique_name,
        file_type=ext,
        source="upload",
        quality_score=quality.quality_score,
        quality_warnings=quality.warnings,
        retake_required=quality.retake_required,
        accepted_for_processing=quality.accepted_for_processing,
        page_status="retake_required" if quality.retake_required else "accepted",
        upload_complete=True,
    )
    db.add(page)

    # Update session captured count
    session.captured_students = (session.captured_students or 0) + (1 if not submission_id else 0)
    session.status = "uploading"
    session.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(page)

    return PageUploadResponse(
        page_id=str(page.page_id),
        submission_id=str(submission.submission_id),
        session_id=session_id,
        page_number=page_number,
        storage_key=key,
        quality_score=quality.quality_score,
        quality_warnings=quality.warnings,
        retake_required=quality.retake_required,
        accepted_for_processing=quality.accepted_for_processing,
        page_status=page.page_status,
    )


async def _save_upload_bytes(storage_key: str, content: bytes) -> None:
    path = Path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ── Page Deletion ─────────────────────────────────────────────────────────────

@router.delete("/sessions/{session_id}/pages/{page_id}", status_code=204)
async def delete_page(
    session_id: str,
    page_id: str,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scanned page (tenant-isolated)."""
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(ScannedPage).where(
            ScannedPage.page_id == uuid.UUID(page_id),
            ScannedPage.session_id == uuid.UUID(session_id),
            ScannedPage.tenant_id == tenant.id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found.")

    # Remove file from local storage (best-effort)
    try:
        Path(page.storage_key).unlink(missing_ok=True)
    except Exception:
        pass

    await db.delete(page)
    await db.commit()


# ── Student Complete ──────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/students/{submission_id}/complete", status_code=200)
async def mark_student_complete(
    session_id: str,
    submission_id: str,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Mark a student's scanning as complete and advance the session queue."""
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(AssessmentSubmission).where(
            AssessmentSubmission.submission_id == uuid.UUID(submission_id),
            AssessmentSubmission.session_id == uuid.UUID(session_id),
            AssessmentSubmission.tenant_id == tenant.id,
        )
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")

    submission.status = "pending"
    submission.updated_at = datetime.now(timezone.utc)

    # Update session queue entry
    sess_result = await db.execute(
        select(MarkingSession).where(MarkingSession.session_id == uuid.UUID(session_id))
    )
    session = sess_result.scalar_one_or_none()
    if session and session.student_queue:
        queue = list(session.student_queue)
        for entry in queue:
            if str(entry.get("submission_id")) == submission_id:
                entry["status"] = "captured"
                break
        session.student_queue = queue
        session.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return {"message": "Student scanning complete.", "submission_id": submission_id}


# ── Process (trigger LangGraph) ───────────────────────────────────────────────

@router.post("/sessions/{session_id}/process")
async def process_session(
    session_id: str,
    body: ProcessSessionRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger LangGraph exam_marking workflow for submissions in this session.

    Reuses POST /ai/copilot/run under the hood.
    Returns copilot_request_id for status polling.
    """
    await set_tenant_context(db, tenant.id)
    teacher_id = _resolve_teacher(request)

    # Validate session
    sess_result = await db.execute(
        select(MarkingSession).where(
            MarkingSession.session_id == uuid.UUID(session_id),
            MarkingSession.tenant_id == tenant.id,
        )
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Gather pages for pending submissions
    submission_uuids = [uuid.UUID(sid) for sid in body.submission_ids] if body.submission_ids else []
    page_query = select(ScannedPage).where(
        ScannedPage.session_id == uuid.UUID(session_id),
        ScannedPage.tenant_id == tenant.id,
        ScannedPage.accepted_for_processing == True,
    )
    if submission_uuids:
        page_query = page_query.where(ScannedPage.submission_id.in_(submission_uuids))
    pages_result = await db.execute(page_query)
    pages = pages_result.scalars().all()

    pages_payload = [
        {
            "page_id": str(p.page_id),
            "storage_key": p.storage_key,
            "page_number": p.page_number,
            "submission_id": str(p.submission_id),
        }
        for p in pages
    ]

    # Invoke CopilotOrchestratorService
    from services.gateway.ai.copilot.service import CopilotOrchestratorService

    svc = CopilotOrchestratorService()
    response = await svc.run(
        db=db,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        school_context={"school_name": tenant.name, "term": ""},
        user_id=teacher_id,
        user_role="teacher",
        intent="exam_marking",
        message=f"Process exam marking session {session_id}",
        structured_input={
            "session_id": session_id,
            "exam_title": session.exam_title,
            "subject": session.subject or "",
            "grade": session.grade or "",
            "curriculum": session.curriculum or "",
            "paper_type": body.paper_type_override or session.paper_type,
            "expected_question_count": len(body.answer_key) or 1,
            "answer_key": body.answer_key,
            "marking_scheme": body.marking_scheme,
            "teacher_guidance": body.teacher_guidance,
            "pages": pages_payload,
            "expected_pages_per_student": session.expected_pages_per_student,
            "total_marks": session.total_marks or 0,
        },
        conversation_id=None,
    )

    # Update session with request_id
    session.copilot_request_id = response.request_id
    session.status = "processing"
    session.updated_at = datetime.now(timezone.utc)

    # ── Auto-persist QuestionResponse records ─────────────────────────────────
    # When the graph returns pending_review, write per-question rows to DB so
    # the teacher review endpoint (PATCH /review) can address them directly
    # without depending on the ephemeral checkpoint state.
    if response.status == "pending_review" and response.result and submission_uuids:
        result_data: dict = response.result if isinstance(response.result, dict) else {}
        qrs: list[dict] = result_data.get("question_responses", [])
        primary_sub_id = submission_uuids[0]

        for qr_data in qrs:
            q_num = int(qr_data.get("question_number", 0))
            if not q_num:
                continue

            # Upsert: fetch existing row first (unique on submission_id + question_number)
            existing_result = await db.execute(
                select(QuestionResponse).where(
                    QuestionResponse.submission_id == primary_sub_id,
                    QuestionResponse.question_number == q_num,
                    QuestionResponse.tenant_id == tenant.id,
                )
            )
            existing_qr = existing_result.scalar_one_or_none()

            grading_method = qr_data.get("grading_method", "rubric_ai")
            # Guard against values not in the DB check constraint
            _valid_methods = {"omr", "vision", "deterministic", "rubric_ai"}
            if grading_method not in _valid_methods:
                grading_method = "rubric_ai"

            if existing_qr:
                existing_qr.extracted_answer = qr_data.get("extracted_answer", "")
                existing_qr.extraction_confidence = qr_data.get("extraction_confidence")
                existing_qr.correct_answer = qr_data.get("correct_answer", "")
                existing_qr.proposed_marks = qr_data.get("proposed_marks")
                existing_qr.max_marks = qr_data.get("max_marks")
                existing_qr.grading_method = grading_method
                existing_qr.confidence = qr_data.get("confidence")
                existing_qr.ambiguous_mark = bool(qr_data.get("ambiguous_mark", False))
                existing_qr.requires_teacher_review = bool(qr_data.get("requires_teacher_review", True))
                existing_qr.evidence = qr_data.get("evidence", {})
                existing_qr.rubric_result = qr_data.get("rubric_result", {})
                existing_qr.manual_edit_required = bool(qr_data.get("manual_edit_required", False))
                existing_qr.status = qr_data.get("status", "proposed")
                existing_qr.updated_at = datetime.now(timezone.utc)
            else:
                new_qr = QuestionResponse(
                    submission_id=primary_sub_id,
                    session_id=uuid.UUID(session_id),
                    tenant_id=tenant.id,
                    question_number=q_num,
                    question_type=qr_data.get("question_type", "short_answer"),
                    extracted_answer=qr_data.get("extracted_answer", ""),
                    extraction_confidence=qr_data.get("extraction_confidence"),
                    source_page=qr_data.get("source_page"),
                    source_reference=qr_data.get("source_reference", ""),
                    correct_answer=qr_data.get("correct_answer", ""),
                    proposed_marks=qr_data.get("proposed_marks"),
                    max_marks=qr_data.get("max_marks"),
                    grading_method=grading_method,
                    confidence=qr_data.get("confidence"),
                    ambiguous_mark=bool(qr_data.get("ambiguous_mark", False)),
                    requires_teacher_review=bool(qr_data.get("requires_teacher_review", True)),
                    teacher_overridden=False,
                    evidence=qr_data.get("evidence", {}),
                    rubric_result=qr_data.get("rubric_result", {}),
                    manual_edit_required=bool(qr_data.get("manual_edit_required", False)),
                    status=qr_data.get("status", "proposed"),
                )
                db.add(new_qr)

        # Update AssessmentSubmission aggregate fields
        sub_lookup_result = await db.execute(
            select(AssessmentSubmission).where(
                AssessmentSubmission.submission_id == primary_sub_id,
                AssessmentSubmission.tenant_id == tenant.id,
            )
        )
        sub_record = sub_lookup_result.scalar_one_or_none()
        if sub_record:
            sub_record.proposed_total = result_data.get("proposed_total")
            sub_record.max_marks = result_data.get("max_marks")
            sub_record.percentage = result_data.get("percentage")
            sub_record.confidence_score = result_data.get("confidence_summary", {}).get("flagged_count") and None
            sub_record.processing_pipeline = result_data.get("processing_pipeline")
            sub_record.ai_graded_count = int(result_data.get("ai_graded_count", 0))
            sub_record.deterministic_count = int(result_data.get("deterministic_count", 0))
            sub_record.objective_question_count = int(result_data.get("objective_question_count", 0))
            sub_record.unresolved_count = int(result_data.get("unresolved_count", 0))
            sub_record.low_confidence_count = int(result_data.get("low_confidence_count", 0))
            sub_record.tokens_used = int(result_data.get("token_usage", {}).get("total_tokens", 0) if isinstance(result_data.get("token_usage"), dict) else 0)
            sub_record.estimated_cost_usd = float(result_data.get("estimated_cost_usd", 0.0))
            sub_record.copilot_request_id = response.request_id
            sub_record.status = "pending_review"
            sub_record.updated_at = datetime.now(timezone.utc)

        # Update session aggregate
        session.status = "pending_review"

    await db.commit()

    return {
        "copilot_request_id": response.request_id,
        "status": response.status,
        "message": response.message,
        "session_id": session_id,
    }


# ── Teacher Review (overrides) ────────────────────────────────────────────────

@router.patch("/sessions/{session_id}/review")
async def submit_review(
    session_id: str,
    body: SubmitReviewRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit teacher mark overrides for a submission.
    Every override is persisted and audited.
    """
    await set_tenant_context(db, tenant.id)
    teacher_id = _resolve_teacher(request)

    sub_result = await db.execute(
        select(AssessmentSubmission).where(
            AssessmentSubmission.submission_id == uuid.UUID(body.submission_id),
            AssessmentSubmission.session_id == uuid.UUID(session_id),
            AssessmentSubmission.tenant_id == tenant.id,
        )
    )
    submission = sub_result.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")

    override_count = 0
    for override in body.overrides:
        qr_result = await db.execute(
            select(QuestionResponse).where(
                QuestionResponse.submission_id == submission.submission_id,
                QuestionResponse.question_number == override.question_number,
                QuestionResponse.tenant_id == tenant.id,
            )
        )
        qr = qr_result.scalar_one_or_none()
        if qr:
            qr.teacher_final_marks = override.teacher_final_marks
            qr.teacher_overridden = True
            qr.teacher_comment = override.teacher_comment
            qr.status = "teacher_approved"
            qr.updated_at = datetime.now(timezone.utc)
            override_count += 1

    if body.teacher_comments:
        submission.teacher_comments = body.teacher_comments
    submission.teacher_overridden = override_count > 0
    submission.updated_at = datetime.now(timezone.utc)

    # Audit every override (no raw student answers in log)
    db.add(AuditLog(
        tenant_id=tenant.id,
        action="exam_marking.teacher_override",
        entity_type="assessment_submission",
        entity_id=submission.submission_id,
        details={
            "teacher_id": teacher_id,
            "override_count": override_count,
            "session_id": session_id,
        },
    ))
    await db.commit()

    return {"message": f"{override_count} override(s) saved.", "submission_id": body.submission_id}


# ── Approval ──────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/approve")
async def approve_submissions(
    session_id: str,
    body: ApproveSubmissionRequest,
    request: Request,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve or reject assessed submissions.
    Marks can never be published without teacher approval.
    """
    await set_tenant_context(db, tenant.id)
    teacher_id = _resolve_teacher(request)

    updated: list[str] = []
    for sub_id in body.submission_ids:
        sub_result = await db.execute(
            select(AssessmentSubmission).where(
                AssessmentSubmission.submission_id == uuid.UUID(sub_id),
                AssessmentSubmission.session_id == uuid.UUID(session_id),
                AssessmentSubmission.tenant_id == tenant.id,
            )
        )
        submission = sub_result.scalar_one_or_none()
        if not submission:
            continue

        # Block approval if unresolved items exist
        if body.approved:
            unresolved = sum(
                1 for qr in (await db.execute(
                    select(QuestionResponse).where(
                        QuestionResponse.submission_id == submission.submission_id,
                        QuestionResponse.status == "unresolved",
                    )
                )).scalars().all()
            )
            if unresolved:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Submission {sub_id} has {unresolved} unresolved question(s). Resolve before approving.",
                )

        new_status = "approved" if body.approved else "rejected"
        submission.status = new_status
        submission.approved_by = teacher_id if body.approved else None
        submission.approved_at = datetime.now(timezone.utc) if body.approved else None
        submission.updated_at = datetime.now(timezone.utc)

        db.add(AuditLog(
            tenant_id=tenant.id,
            action=f"exam_marking.submission_{new_status}",
            entity_type="assessment_submission",
            entity_id=submission.submission_id,
            details={
                "teacher_id": teacher_id,
                "approved": body.approved,
                "notes": body.notes,
                "session_id": session_id,
            },
        ))
        updated.append(sub_id)

    # Update session aggregate status
    sess_result = await db.execute(
        select(MarkingSession).where(
            MarkingSession.session_id == uuid.UUID(session_id),
            MarkingSession.tenant_id == tenant.id,
        )
    )
    session = sess_result.scalar_one_or_none()
    if session:
        all_subs = (await db.execute(
            select(AssessmentSubmission).where(
                AssessmentSubmission.session_id == uuid.UUID(session_id),
                AssessmentSubmission.tenant_id == tenant.id,
            )
        )).scalars().all()
        approved_n = sum(1 for s in all_subs if s.status == "approved")
        total_n = len(all_subs)
        session.approved_students = approved_n
        if approved_n == total_n and total_n > 0:
            session.status = "approved"
        elif approved_n > 0:
            session.status = "partially_approved"
        session.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "message": f"{len(updated)} submission(s) {'approved' if body.approved else 'rejected'}.",
        "updated": updated,
    }


# ── Submissions List ──────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/submissions", response_model=list[SubmissionSummary])
async def list_submissions(
    session_id: str,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all submissions for a session (tenant-isolated)."""
    await set_tenant_context(db, tenant.id)
    result = await db.execute(
        select(AssessmentSubmission).where(
            AssessmentSubmission.session_id == uuid.UUID(session_id),
            AssessmentSubmission.tenant_id == tenant.id,
        ).order_by(AssessmentSubmission.created_at)
    )
    subs = result.scalars().all()
    return [
        SubmissionSummary(
            submission_id=str(s.submission_id),
            session_id=str(s.session_id),
            student_name=s.student_name or "",
            student_code=s.student_code or "",
            paper_type=s.paper_type,
            status=s.status,
            proposed_total=s.proposed_total,
            teacher_final_total=s.teacher_final_total,
            max_marks=s.max_marks,
            percentage=s.percentage,
            confidence_score=s.confidence_score,
            copilot_request_id=s.copilot_request_id,
        )
        for s in subs
    ]
