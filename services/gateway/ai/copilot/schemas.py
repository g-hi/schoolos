from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


CopilotStatus = Literal[
    "completed",
    "unavailable",
    "needs_clarification",
    "pending_review",
    "approved",
    "unsupported_intent",
    "error",
]


class CopilotRunRequest(BaseModel):
    intent: str = Field(default="lesson_planning")
    message: str
    structured_input: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None


class CopilotContinueRequest(BaseModel):
    request_id: str
    message: str | None = None
    structured_input: dict[str, Any] = Field(default_factory=dict)


class CopilotApproveRequest(BaseModel):
    request_id: str
    approved: bool = True
    notes: str | None = None


class CopilotExecutionInfo(BaseModel):
    workflow: str
    current_step: str
    validation_passed: bool = False
    retry_count: int = 0
    tenant_slug: str | None = None


class CopilotResponseStudent(BaseModel):
    id: str | None = None
    display_name: str


class CopilotResponseSource(BaseModel):
    type: str
    label: str


class CopilotResponse(BaseModel):
    status: CopilotStatus
    request_id: str
    conversation_id: str | None = None
    intent: str | None = None
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    result: dict[str, Any] | None = None
    response_kind: str | None = None
    parent_intent: str | None = None
    requires_clarification: bool | None = None
    unavailable_reason: str | None = None
    student: CopilotResponseStudent | None = None
    sources: list[CopilotResponseSource] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    execution: CopilotExecutionInfo
