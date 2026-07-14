"""
Pydantic schemas for the exam marking API and LangGraph state payloads.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Marking Session ───────────────────────────────────────────────────────────

MarkingSessionStatus = Literal[
    "draft", "scanning", "uploading", "processing", "needs_clarification",
    "pending_review", "partially_approved", "approved", "rejected", "failed",
]

PaperType = Literal["scantron", "printed_mcq", "mixed", "open_ended"]
InputMethod = Literal["smart_scan", "upload", "office_scanner"]


class CreateMarkingSessionRequest(BaseModel):
    exam_title: str
    subject: str = ""
    grade: str = ""
    class_name: str = ""
    curriculum: str = ""
    academic_year: str = ""
    term: str = ""
    exam_date: str | None = None
    total_marks: int = 0
    time_allowed_minutes: int | None = None
    expected_pages_per_student: int = 1
    paper_type: PaperType = "open_ended"
    input_method: InputMethod = "upload"
    language: str = "English"
    total_students: int = 0
    teacher_notes: str = ""


class MarkingSessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    teacher_id: str
    exam_title: str
    subject: str
    grade: str
    class_name: str
    curriculum: str
    academic_year: str
    term: str
    exam_date: str | None
    total_marks: int
    paper_type: str
    input_method: str
    language: str
    total_students: int
    captured_students: int
    processed_students: int
    pending_students: int
    flagged_students: int
    approved_students: int
    average_confidence: float | None
    status: str
    teacher_notes: str
    created_at: str
    updated_at: str


# ── Page Upload ───────────────────────────────────────────────────────────────

class PageUploadResponse(BaseModel):
    page_id: str
    submission_id: str
    session_id: str
    page_number: int
    storage_key: str
    quality_score: float | None
    quality_warnings: list[str]
    retake_required: bool
    accepted_for_processing: bool
    page_status: str


# ── Submission ────────────────────────────────────────────────────────────────

class SubmissionSummary(BaseModel):
    submission_id: str
    session_id: str
    student_name: str
    student_code: str
    paper_type: str
    status: str
    proposed_total: float | None
    teacher_final_total: float | None
    max_marks: int | None
    percentage: float | None
    confidence_score: float | None
    copilot_request_id: str | None


# ── Process Request ───────────────────────────────────────────────────────────

class ProcessSessionRequest(BaseModel):
    submission_ids: list[str] = Field(default_factory=list)  # empty = all pending
    answer_key: list[dict[str, Any]] = Field(default_factory=list)
    marking_scheme: dict[str, Any] = Field(default_factory=dict)
    teacher_guidance: str = ""
    paper_type_override: PaperType | None = None


# ── Teacher Review ────────────────────────────────────────────────────────────

class QuestionOverride(BaseModel):
    question_number: int
    teacher_final_marks: float
    teacher_comment: str = ""


class SubmitReviewRequest(BaseModel):
    submission_id: str
    overrides: list[QuestionOverride] = Field(default_factory=list)
    teacher_comments: str = ""


# ── Approval ─────────────────────────────────────────────────────────────────

class ApproveSubmissionRequest(BaseModel):
    submission_ids: list[str]
    approved: bool = True
    notes: str = ""
