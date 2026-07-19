from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


SourceType = Literal["manual", "ai_generated", "staff_revision"]
ValidationStatus = Literal["passed", "failed"]


class StaffEvidenceInput(BaseModel):
    weekly_teacher_summary: str | None = Field(default=None, max_length=2000)
    strengths_observed: str | None = Field(default=None, max_length=2000)
    achievements: str | None = Field(default=None, max_length=2000)
    areas_needing_support: str | None = Field(default=None, max_length=2000)
    suggested_parent_support: str | None = Field(default=None, max_length=2000)
    additional_factual_note: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "weekly_teacher_summary",
        "strengths_observed",
        "achievements",
        "areas_needing_support",
        "suggested_parent_support",
        "additional_factual_note",
        mode="before",
    )
    @classmethod
    def _validate_staff_text_fields(cls, value: str | None):
        return ensure_plain_text(value)


class ReportSectionInput(BaseModel):
    section_type: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content", mode="before")
    @classmethod
    def _validate_section_content(cls, value: str):
        return ensure_plain_text(value)


class InitializeWeeklyReportRequest(BaseModel):
    student_id: str
    week_start: date
    timezone_override: str | None = Field(default=None, max_length=60)
    assigned_reviewer_user_id: str | None = None
    expected_row_version: int | None = None
    staff_evidence: StaffEvidenceInput | None = None


class EditWeeklyReportRequest(BaseModel):
    expected_row_version: int
    title: str | None = Field(default=None, max_length=255)
    sections: list[ReportSectionInput] = Field(default_factory=list)
    staff_evidence: StaffEvidenceInput | None = None


class GenerateDraftRequest(BaseModel):
    expected_row_version: int
    use_ai: bool = True


class StatusTransitionRequest(BaseModel):
    expected_row_version: int
    comment: str | None = Field(default=None, max_length=2000)


class WeeklyReportListItem(BaseModel):
    report_id: str
    student_id: str
    student_display_name: str
    class_name: str
    week_start: date
    week_end: date
    status: str
    current_version_number: int
    approved_version_number: int | None
    published_version_number: int | None
    row_version: int
    updated_at: datetime


class WeeklyReportStudentOption(BaseModel):
    student_id: str
    student_display_name: str
    class_name: str


class WeeklyReportVersionResponse(BaseModel):
    version_id: str
    version_number: int
    source_type: SourceType
    validation_status: ValidationStatus
    created_by_user_id: str | None
    created_at: datetime


class WeeklyReportDetailResponse(BaseModel):
    report_id: str
    student_id: str
    student_display_name: str
    class_name: str
    week_start: date
    week_end: date
    timezone_used: str
    status: str
    row_version: int
    current_version_number: int
    approved_version_number: int | None
    published_version_number: int | None
    current_content: dict
    current_evidence_snapshot: dict
    current_validation_status: ValidationStatus
    current_validation_errors: list[dict]
    versions: list[WeeklyReportVersionResponse]


class ReviewEventResponse(BaseModel):
    event_id: str
    report_id: str
    report_version_id: str | None
    actor_user_id: str | None
    event_type: str
    previous_status: str | None
    new_status: str | None
    comment: str | None
    created_at: datetime


class ParentPublishedReportListItem(BaseModel):
    report_id: str
    student_id: str
    student_display_name: str
    class_name: str
    week_start: date
    week_end: date
    title: str
    published_at: datetime


class ParentPublishedReportDetail(BaseModel):
    report_id: str
    student_id: str
    student_display_name: str
    class_name: str
    week_start: date
    week_end: date
    title: str
    sections: list[dict]
    published_at: datetime


class WeeklyReportActionResult(BaseModel):
    report_id: str
    status: str
    row_version: int
    current_version_number: int


def ensure_plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if "<" in text or ">" in text:
        raise ValueError("HTML is not allowed in report fields.")
    return text
