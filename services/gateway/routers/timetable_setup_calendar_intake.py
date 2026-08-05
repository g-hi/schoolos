from __future__ import annotations

import hashlib
import io
import os
import re
import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.audit import log_action
from services.gateway.calendar.impact import calculate_event_impact
from services.gateway.timetable_setup.readiness import compute_timetable_input_readiness
from shared.auth.dependencies import resolve_authenticated_leadership
from shared.auth.tenant import resolve_tenant
from shared.config import settings
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import (
    CalendarEventCandidate,
    CalendarEventVersion,
    CalendarNotificationPlan,
    CalendarSourceDocument,
    CalendarSourcePage,
    Campus,
    Class,
    ImportBatch,
    ImportRowResult,
    Notification,
    OperationalCalendarEvent,
    Tenant,
    User,
)

router = APIRouter(prefix="/leadership/timetable-setup", tags=["Timetable Setup"])

_SCOPE_TYPES = {
    "whole_school",
    "campus",
    "grade_levels",
    "classes",
    "departments",
    "staff_roles",
    "selected_users",
    "public_information",
}

_DATE_YYYY_MM_DD = re.compile(r"(\d{4}-\d{2}-\d{2})")
_DATE_RANGE_YYYY_MM_DD = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:to|–|-|until)\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF]")
_HIJRI_MARKERS = re.compile(r"\b(hijri|ah|muharram|safar|ramadan|shawwal|dhul)\b", re.IGNORECASE)


class EventScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: str
    campus: uuid.UUID | None = None
    grade_levels: list[str] = []
    classes: list[uuid.UUID] = []
    departments: list[str] = []
    staff_roles: list[str] = []
    selected_users: list[uuid.UUID] = []
    public_information: bool = False
    contains_confidential_staffing: bool = False


class ManualEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str
    description: str | None = None
    start_date: date_type
    end_date: date_type
    event_type: str
    teaching_day_effect: str = "no_change"
    scope: EventScope
    source_reference: str | None = None


class ManualEventPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str | None = None
    description: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    event_type: str | None = None
    teaching_day_effect: str | None = None
    scope: EventScope | None = None
    reason: str | None = None


class EventRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_start_date: date_type
    new_end_date: date_type
    reason: str


class EventStatusReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class NotificationPlanDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_reason: str
    subject: str
    proposed_message: str
    channels: list[str]
    urgency: Literal["low", "normal", "high", "critical"] = "normal"
    scheduled_at: datetime | None = None
    reminder_settings: dict[str, Any] | None = None


class CandidateEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_event_name: str | None = None
    proposed_description: str | None = None
    proposed_start_date: date_type | None = None
    proposed_end_date: date_type | None = None
    proposed_event_type: str | None = None
    proposed_teaching_day_effect: str | None = None


class CommitApprovedCandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_scope: EventScope | None = None


class ValidatePdfBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_approved_only: bool = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_required_text(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must not be blank.")
    return cleaned


def _ensure_actor_tenant(actor: User, tenant: Tenant) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive users cannot access this resource.")
    if actor.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _event_payload(event: OperationalCalendarEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_name": event.event_name,
        "description": event.description,
        "start_date": event.start_date,
        "end_date": event.end_date,
        "event_type": event.event_type,
        "teaching_day_effect": event.teaching_day_effect,
        "source_type": event.source_type,
        "review_status": event.review_status,
        "lifecycle_status": event.lifecycle_status,
        "version_number": event.version_number,
        "change_reason": event.change_reason,
        "impact_scope_json": event.impact_scope_json,
        "notification_plan_status": event.notification_plan_status,
        "notification_plan_json": event.notification_plan_json,
        "published_at": event.published_at,
        "is_active": event.is_active,
    }


def _version_payload(version: CalendarEventVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "event_id": str(version.event_id),
        "version_number": version.version_number,
        "change_type": version.change_type,
        "reason": version.reason,
        "previous_values": version.previous_values,
        "new_values": version.new_values,
        "changed_fields": version.changed_fields,
        "source_type": version.source_type,
        "affected_stakeholder_summary": version.affected_stakeholder_summary,
        "notification_plan_id": str(version.notification_plan_id) if version.notification_plan_id else None,
        "created_at": version.created_at,
    }


def _candidate_payload(candidate: CalendarEventCandidate) -> dict[str, Any]:
    return {
        "id": str(candidate.id),
        "source_document_id": str(candidate.source_document_id) if candidate.source_document_id else None,
        "source_page_id": str(candidate.source_page_id) if candidate.source_page_id else None,
        "proposed_event_name": candidate.proposed_event_name,
        "proposed_description": candidate.proposed_description,
        "proposed_start_date": candidate.proposed_start_date,
        "proposed_end_date": candidate.proposed_end_date,
        "proposed_event_type": candidate.proposed_event_type,
        "proposed_teaching_day_effect": candidate.proposed_teaching_day_effect,
        "confidence_score": candidate.confidence_score,
        "candidate_status": candidate.candidate_status,
        "date_parse_status": candidate.date_parse_status,
        "uncertainty_note": candidate.uncertainty_note,
        "classification_json": candidate.classification_json,
        "validation_issues_json": candidate.validation_issues_json,
        "source_payload": candidate.source_payload,
        "applied_event_id": str(candidate.applied_event_id) if candidate.applied_event_id else None,
    }


def _is_high_impact(*, trigger_reason: str, event_type: str, scope: dict[str, Any]) -> bool:
    high_impact_trigger = trigger_reason in {"event_cancelled", "event_rescheduled", "urgent_change"}
    high_impact_event = event_type in {"examination_period", "public_holiday", "teaching_day_override", "special_schedule"}
    whole_school = str(scope.get("scope_type") or "") == "whole_school"
    return high_impact_trigger or high_impact_event or whole_school


def _event_snapshot(event: OperationalCalendarEvent) -> dict[str, Any]:
    return {
        "event_name": event.event_name,
        "description": event.description,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat(),
        "event_type": event.event_type,
        "teaching_day_effect": event.teaching_day_effect,
        "review_status": event.review_status,
        "lifecycle_status": event.lifecycle_status,
        "version_number": event.version_number,
        "impact_scope_json": event.impact_scope_json,
        "notification_plan_status": event.notification_plan_status,
        "notification_plan_json": event.notification_plan_json,
        "is_active": event.is_active,
    }


async def _validate_scope(*, db: AsyncSession, tenant_id: uuid.UUID, scope: EventScope) -> dict[str, Any]:
    if scope.scope_type not in _SCOPE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported scope_type.")

    normalized = scope.model_dump()

    if scope.scope_type == "campus":
        if scope.campus is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="campus scope requires campus id.")
        campus_exists = await db.scalar(select(Campus.id).where(Campus.tenant_id == tenant_id, Campus.id == scope.campus))
        if campus_exists is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="campus reference is outside tenant scope.")

    if scope.scope_type == "classes":
        if not scope.classes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="classes scope requires class ids.")
        rows = (
            await db.execute(
                select(Class.id).where(Class.tenant_id == tenant_id, Class.id.in_(scope.classes), Class.is_active.is_(True))
            )
        ).scalars().all()
        if len(rows) != len(set(scope.classes)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more class references are outside tenant scope.")

    if scope.scope_type == "selected_users":
        if not scope.selected_users:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="selected_users scope requires user ids.")
        rows = (
            await db.execute(
                select(User.id).where(User.tenant_id == tenant_id, User.id.in_(scope.selected_users), User.is_active.is_(True))
            )
        ).scalars().all()
        if len(rows) != len(set(scope.selected_users)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more selected_users references are outside tenant scope.")

    return normalized


async def _append_version(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    event: OperationalCalendarEvent,
    change_type: str,
    actor: User,
    previous_values: dict[str, Any],
    reason: str | None,
    source_type: str,
    impacted: dict[str, Any] | None,
    approval_actor_id: uuid.UUID | None = None,
    notification_plan_id: uuid.UUID | None = None,
) -> None:
    new_values = _event_snapshot(event)
    changed_fields = sorted([key for key in new_values.keys() if previous_values.get(key) != new_values.get(key)])
    version = CalendarEventVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event.id,
        version_number=event.version_number,
        previous_values=previous_values,
        new_values=new_values,
        changed_fields=changed_fields,
        change_type=change_type,
        reason=reason,
        actor_user_id=actor.id,
        approval_actor_user_id=approval_actor_id,
        source_type=source_type,
        affected_stakeholder_summary=(impacted or {}),
        notification_plan_id=notification_plan_id,
    )
    db.add(version)


async def _create_notification_plan(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor: User,
    event: OperationalCalendarEvent,
    trigger_reason: str,
    impact: dict[str, Any],
    subject: str,
    message: str,
    channels: list[str] | None = None,
    urgency: str = "normal",
    scheduled_at: datetime | None = None,
    reminder_settings: dict[str, Any] | None = None,
) -> CalendarNotificationPlan:
    scope = dict(event.impact_scope_json or {})
    channels_value = channels or impact.get("recommended_channels") or ["in_app"]
    approval_required = _is_high_impact(trigger_reason=trigger_reason, event_type=event.event_type, scope=scope)
    status_value = "pending_approval" if approval_required else "approved"

    plan = CalendarNotificationPlan(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event.id,
        event_version_number=event.version_number,
        trigger_reason=trigger_reason,
        audience_scope=scope,
        affected_count=int(impact.get("affected_count") or 0),
        subject=_clean_required_text(subject, label="subject"),
        proposed_message=_clean_required_text(message, label="proposed_message"),
        channels=channels_value,
        scheduled_at=scheduled_at,
        reminder_settings=reminder_settings or {"hours_before": settings.timetable_calendar_default_reminder_hours},
        urgency=urgency,
        approval_required=approval_required,
        approval_status=status_value,
        approved_by_user_id=(actor.id if not approval_required else None),
        approved_at=(_now() if not approval_required else None),
        outbox_status=status_value,
        delivery_summary={"sent": 0, "failed": 0, "skipped": 0},
        audit_reference_json={},
        created_by_user_id=actor.id,
    )
    db.add(plan)

    if not approval_required:
        notification = Notification(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            recipient_user_id=actor.id,
            source_type="calendar_notification_plan",
            source_id=plan.id,
            category="calendar_update_plan",
            title=plan.subject,
            body=plan.proposed_message,
            delivery_status="pending",
            attempt_count=0,
        )
        db.add(notification)
        plan.related_notification_id = notification.id

    return plan


def _classify_event(text: str) -> dict[str, Any]:
    lowered = text.casefold()
    rules: list[tuple[str, str, str, int]] = [
        ("public_holiday", "holiday", "Contains keyword 'holiday'.", 90),
        ("school_holiday", "vacation", "Contains keyword 'vacation'.", 84),
        ("examination_period", "exam", "Contains keyword 'exam'.", 90),
        ("professional_development", "development", "Contains keyword 'development'.", 80),
        ("parent_conference", "conference", "Contains keyword 'conference'.", 85),
        ("half_day", "half", "Contains keyword 'half'.", 80),
        ("term_boundary", "term", "Contains keyword 'term'.", 78),
        ("special_schedule", "special", "Contains keyword 'special'.", 76),
        ("teaching_day_override", "override", "Contains keyword 'override'.", 82),
        ("information_only", "notice", "Contains keyword 'notice'.", 74),
    ]
    for event_type, token, explanation, confidence in rules:
        if token in lowered:
            return {
                "proposed_type": event_type,
                "confidence": confidence,
                "matched_rule": token,
                "explanation": explanation,
                "uncertainty": None,
            }
    return {
        "proposed_type": "school_event",
        "confidence": 60,
        "matched_rule": "fallback",
        "explanation": "No specific keyword matched. Defaulted to school_event.",
        "uncertainty": "Review recommended.",
    }


def _parse_dates(raw_line: str) -> tuple[date_type | None, date_type | None, str, str | None, list[str]]:
    warnings: list[str] = []
    line = raw_line.strip()

    if _ARABIC_SCRIPT.search(line) or _HIJRI_MARKERS.search(line):
        # Preserve raw text and require manual confirmation for Hijri/non-Gregorian hints.
        if _DATE_YYYY_MM_DD.search(line):
            warnings.append("mixed_calendar_warning")
            date_value = datetime.strptime(_DATE_YYYY_MM_DD.search(line).group(1), "%Y-%m-%d").date()
            return date_value, date_value, "parsed", "Mixed calendars detected; verify conversion intent.", warnings
        return None, None, "hijri_unresolved", "Hijri/Arabic date requires manual interpretation.", warnings

    range_match = _DATE_RANGE_YYYY_MM_DD.search(line)
    if range_match:
        start = datetime.strptime(range_match.group(1), "%Y-%m-%d").date()
        end = datetime.strptime(range_match.group(2), "%Y-%m-%d").date()
        if end < start:
            return start, end, "invalid_range", "End date is before start date.", warnings
        return start, end, "parsed", None, warnings

    single_match = _DATE_YYYY_MM_DD.search(line)
    if single_match:
        single_date = datetime.strptime(single_match.group(1), "%Y-%m-%d").date()
        return single_date, single_date, "parsed", None, warnings

    numeric = _DATE_NUMERIC.search(line)
    if numeric:
        return None, None, "ambiguous", "Ambiguous numeric date format needs clarification.", warnings

    return None, None, "missing", "No Gregorian date found.", warnings


def _extract_lines(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_number, text in pages:
        for line in [chunk.strip() for chunk in text.splitlines() if chunk.strip()]:
            start_date, end_date, parse_status, note, warnings = _parse_dates(line)
            classification = _classify_event(line)
            issues: dict[str, list[str]] = {"warnings": warnings.copy(), "blockers": []}
            if parse_status in {"ambiguous", "hijri_unresolved", "missing"}:
                issues["warnings"].append(parse_status)
            if parse_status == "invalid_range":
                issues["blockers"].append("invalid_range")
            teaching_day_effect = "no_change"
            if classification["proposed_type"] in {"public_holiday", "school_holiday", "professional_development"}:
                teaching_day_effect = "non_teaching_day"
            if classification["proposed_type"] in {"examination_period", "special_schedule", "half_day", "parent_conference"}:
                teaching_day_effect = "special_schedule"
            rows.append(
                {
                    "page_number": page_number,
                    "line": line,
                    "name": line[:255],
                    "description": line,
                    "start_date": start_date,
                    "end_date": end_date,
                    "date_parse_status": parse_status,
                    "uncertainty_note": note,
                    "classification": classification,
                    "event_type": classification["proposed_type"],
                    "teaching_day_effect": teaching_day_effect,
                    "issues": issues,
                }
            )
    return rows


def _sanitize_filename(name: str) -> str:
    cleaned = os.path.basename(name).strip()
    if not cleaned:
        return "calendar.pdf"
    return cleaned


@router.post("/calendar/events", summary="Create manual calendar event draft")
async def create_manual_event(
    body: ManualEventCreateRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    if body.end_date < body.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date cannot be after end_date.")
    scope = await _validate_scope(db=db, tenant_id=tenant.id, scope=body.scope)

    item = OperationalCalendarEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        event_name=_clean_required_text(body.event_name, label="event_name"),
        description=body.description,
        start_date=body.start_date,
        end_date=body.end_date,
        is_all_day=True,
        event_type=body.event_type,
        teaching_day_effect=body.teaching_day_effect,
        source_type="manual",
        review_status="pending_review",
        lifecycle_status="draft",
        version_number=1,
        source_reference=body.source_reference,
        impact_scope_json=scope,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(item)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="created",
        actor=actor,
        previous_values={},
        reason="manual_draft_created",
        source_type="manual",
        impacted={},
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.created",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"lifecycle_status": "draft"},
    )
    await db.commit()
    await db.refresh(item)
    return _event_payload(item)


@router.get("/calendar/events", summary="List manual calendar events")
async def list_manual_events(
    lifecycle_status: str | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id)
    if lifecycle_status:
        stmt = stmt.where(OperationalCalendarEvent.lifecycle_status == lifecycle_status)
    rows = (await db.execute(stmt.order_by(OperationalCalendarEvent.start_date.asc(), OperationalCalendarEvent.created_at.asc()))).scalars().all()
    return [_event_payload(item) for item in rows]


@router.get("/calendar/events/{event_id}", summary="Get manual calendar event")
async def get_manual_event(
    event_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")
    return _event_payload(item)


@router.patch("/calendar/events/{event_id}", summary="Edit calendar event")
async def patch_manual_event(
    event_id: uuid.UUID,
    body: ManualEventPatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")
    previous = _event_snapshot(item)

    if body.event_name is not None:
        item.event_name = _clean_required_text(body.event_name, label="event_name")
    if body.description is not None:
        item.description = body.description
    if body.start_date is not None:
        item.start_date = body.start_date
    if body.end_date is not None:
        item.end_date = body.end_date
    if item.end_date < item.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date cannot be after end_date.")
    if body.event_type is not None:
        item.event_type = body.event_type
    if body.teaching_day_effect is not None:
        item.teaching_day_effect = body.teaching_day_effect
    if body.scope is not None:
        item.impact_scope_json = await _validate_scope(db=db, tenant_id=tenant.id, scope=body.scope)

    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="edited",
        actor=actor,
        previous_values=previous,
        reason=body.reason or "manual_edit",
        source_type=item.source_type,
        impacted=impact,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.edited",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number},
    )
    await db.commit()
    await db.refresh(item)
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/submit", summary="Submit calendar event for review")
async def submit_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    previous = _event_snapshot(item)
    item.lifecycle_status = "pending_review"
    item.review_status = "pending_review"
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="submitted",
        actor=actor,
        previous_values=previous,
        reason=_clean_required_text(body.reason, label="reason"),
        source_type=item.source_type,
        impacted=impact,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.submitted",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number},
    )
    await db.commit()
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/approve", summary="Approve calendar event")
async def approve_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    previous = _event_snapshot(item)
    item.review_status = "approved"
    item.lifecycle_status = "approved"
    item.reviewed_by_user_id = actor.id
    item.approved_by_user_id = actor.id
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="approved",
        actor=actor,
        previous_values=previous,
        reason=_clean_required_text(body.reason, label="reason"),
        source_type=item.source_type,
        impacted=impact,
        approval_actor_id=actor.id,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.approved",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number},
    )
    await db.commit()
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/publish", summary="Publish calendar event")
async def publish_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")
    if item.review_status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only approved events can be published.")

    previous = _event_snapshot(item)
    item.lifecycle_status = "published"
    item.published_at = _now()
    item.published_by_user_id = actor.id
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    plan = await _create_notification_plan(
        db=db,
        tenant_id=tenant.id,
        actor=actor,
        event=item,
        trigger_reason="event_published",
        impact=impact,
        subject=f"Calendar update: {item.event_name}",
        message=f"{item.event_name} has been published for {item.start_date.isoformat()}.",
        channels=impact.get("recommended_channels") or ["in_app"],
    )
    item.notification_plan_status = "planned"
    item.notification_plan_json = {"plan_id": str(plan.id), "approval_status": plan.approval_status}
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="published",
        actor=actor,
        previous_values=previous,
        reason=_clean_required_text(body.reason, label="reason"),
        source_type=item.source_type,
        impacted=impact,
        notification_plan_id=plan.id,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.published",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number, "notification_plan_id": str(plan.id)},
    )
    await db.commit()
    await db.refresh(item)
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/reschedule", summary="Reschedule published calendar event")
async def reschedule_manual_event(
    event_id: uuid.UUID,
    body: EventRescheduleRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")
    if body.new_end_date < body.new_start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="new_start_date cannot be after new_end_date.")

    previous = _event_snapshot(item)
    old_dates = {"start_date": item.start_date.isoformat(), "end_date": item.end_date.isoformat()}
    item.start_date = body.new_start_date
    item.end_date = body.new_end_date
    item.lifecycle_status = "rescheduled"
    item.change_reason = _clean_required_text(body.reason, label="reason")
    item.version_number += 1

    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    plan = await _create_notification_plan(
        db=db,
        tenant_id=tenant.id,
        actor=actor,
        event=item,
        trigger_reason="event_rescheduled",
        impact=impact,
        subject=f"Event rescheduled: {item.event_name}",
        message=f"{item.event_name} moved from {old_dates['start_date']} to {item.start_date.isoformat()}.",
        urgency="high",
    )
    item.notification_plan_status = "planned"
    item.notification_plan_json = {
        "plan_id": str(plan.id),
        "old_dates": old_dates,
        "new_dates": {"start_date": item.start_date.isoformat(), "end_date": item.end_date.isoformat()},
    }

    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="rescheduled",
        actor=actor,
        previous_values=previous,
        reason=item.change_reason,
        source_type=item.source_type,
        impacted=impact,
        notification_plan_id=plan.id,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.rescheduled",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number, "old_dates": old_dates},
    )
    await db.commit()
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/cancel", summary="Cancel calendar event")
async def cancel_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    previous = _event_snapshot(item)
    item.lifecycle_status = "cancelled"
    item.change_reason = _clean_required_text(body.reason, label="reason")
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    plan = await _create_notification_plan(
        db=db,
        tenant_id=tenant.id,
        actor=actor,
        event=item,
        trigger_reason="event_cancelled",
        impact=impact,
        subject=f"Event cancelled: {item.event_name}",
        message=f"{item.event_name} on {item.start_date.isoformat()} was cancelled.",
        urgency="critical",
    )
    item.notification_plan_status = "planned"
    item.notification_plan_json = {"plan_id": str(plan.id), "reason": item.change_reason}
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="cancelled",
        actor=actor,
        previous_values=previous,
        reason=item.change_reason,
        source_type=item.source_type,
        impacted=impact,
        notification_plan_id=plan.id,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.cancelled",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number, "reason": item.change_reason},
    )
    await db.commit()
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/restore", summary="Restore cancelled/archived event")
async def restore_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    previous = _event_snapshot(item)
    item.lifecycle_status = "approved"
    item.review_status = "approved"
    item.is_active = True
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="restored",
        actor=actor,
        previous_values=previous,
        reason=_clean_required_text(body.reason, label="reason"),
        source_type=item.source_type,
        impacted=impact,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.restored",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number},
    )
    await db.commit()
    return _event_payload(item)


@router.post("/calendar/events/{event_id}/archive", summary="Archive event without deleting")
async def archive_manual_event(
    event_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    previous = _event_snapshot(item)
    item.lifecycle_status = "archived"
    item.is_active = False
    item.version_number += 1
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="archived",
        actor=actor,
        previous_values=previous,
        reason=_clean_required_text(body.reason, label="reason"),
        source_type=item.source_type,
        impacted=impact,
    )
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_event.archived",
        entity_type="OperationalCalendarEvent",
        entity_id=item.id,
        actor_id=actor.id,
        details={"version_number": item.version_number},
    )
    await db.commit()
    return _event_payload(item)


@router.get("/calendar/events/{event_id}/versions", summary="Get immutable event versions")
async def list_event_versions(
    event_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(CalendarEventVersion)
            .where(CalendarEventVersion.tenant_id == tenant.id, CalendarEventVersion.event_id == event_id)
            .order_by(CalendarEventVersion.created_at.asc())
        )
    ).scalars().all()
    return [_version_payload(row) for row in rows]


@router.get("/calendar/events/{event_id}/impact", summary="Calculate deterministic stakeholder impact")
async def get_event_impact(
    event_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")
    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    return {"event_id": str(item.id), "impact": impact}


@router.post("/calendar/pdf-intake/upload", summary="Upload timetable calendar PDF")
async def upload_calendar_pdf(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    safe_name = _sanitize_filename(file.filename or "calendar.pdf")
    if not safe_name.casefold().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only .pdf uploads are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded PDF file is empty.")
    if len(content) > settings.timetable_calendar_pdf_max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Uploaded PDF exceeds configured size limit.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid PDF signature.")

    file_sha256 = hashlib.sha256(content).hexdigest()
    existing = await db.scalar(
        select(CalendarSourceDocument).where(
            CalendarSourceDocument.tenant_id == tenant.id,
            CalendarSourceDocument.file_sha256 == file_sha256,
            CalendarSourceDocument.extraction_status.in_(["review_ready", "ocr_required", "processed", "committed"]),
        )
    )
    if existing is not None:
        batch_id = await db.scalar(
            select(ImportBatch.id).where(ImportBatch.tenant_id == tenant.id, ImportBatch.id == existing.import_batch_id)
        )
        return {
            "document_id": str(existing.id),
            "import_batch_id": str(batch_id) if batch_id else None,
            "status": existing.extraction_status,
            "deduplicated": True,
        }

    batch = ImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        entity_type="calendar_pdf",
        original_filename=safe_name,
        file_sha256=file_sha256,
        status="uploaded",
        mode="workbook",
        created_by_user_id=actor.id,
        import_format="pdf",
        metadata_json={"workflow": "calendar_pdf_intake"},
    )
    db.add(batch)

    document = CalendarSourceDocument(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=batch.id,
        original_filename=safe_name,
        file_sha256=file_sha256,
        source_type="pdf_upload",
        extraction_status="processing",
        uploaded_by_user_id=actor.id,
    )
    db.add(document)

    try:
        reader = PdfReader(io.BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            document.extraction_status = "failed"
            document.extraction_error = "Encrypted PDF is not supported in this batch."
            batch.status = "failed"
            await db.commit()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Encrypted PDF is not supported.")
    except HTTPException:
        raise
    except Exception as exc:
        document.extraction_status = "failed"
        document.extraction_error = f"PDF parse failed: {exc}"
        batch.status = "failed"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PDF could not be parsed safely.") from exc

    page_count = len(reader.pages)
    if page_count > settings.timetable_calendar_pdf_max_pages:
        document.extraction_status = "failed"
        document.extraction_error = "Page count exceeds configured maximum."
        batch.status = "failed"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PDF has too many pages for intake processing.")

    total_chars = 0
    has_text = False
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            has_text = True
        if len(text) > settings.timetable_calendar_pdf_max_chars_per_page:
            text = text[: settings.timetable_calendar_pdf_max_chars_per_page]
        total_chars += len(text)
        page_model = CalendarSourcePage(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            source_document_id=document.id,
            page_number=idx,
            extracted_text=text,
            text_excerpt=text[: settings.timetable_calendar_pdf_source_excerpt_max_length] or None,
            extracted_char_count=len(text),
        )
        db.add(page_model)

    document.page_count = page_count
    document.extracted_char_count = total_chars
    document.processed_at = _now()

    if not has_text:
        document.extraction_status = "ocr_required"
        batch.status = "validation_failed"
        batch.completed_at = _now()
    else:
        document.extraction_status = "review_ready"
        batch.status = "uploaded"

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_pdf.uploaded",
        entity_type="CalendarSourceDocument",
        entity_id=document.id,
        actor_id=actor.id,
        details={"page_count": page_count, "has_text": has_text},
    )
    await db.commit()

    return {
        "document_id": str(document.id),
        "import_batch_id": str(batch.id),
        "status": document.extraction_status,
        "page_count": page_count,
        "deduplicated": False,
    }


@router.get("/calendar/pdf-intake/imports", summary="List calendar PDF imports")
async def list_calendar_pdf_imports(
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    rows = (
        await db.execute(
            select(CalendarSourceDocument)
            .where(CalendarSourceDocument.tenant_id == tenant.id)
            .order_by(CalendarSourceDocument.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "document_id": str(row.id),
            "import_batch_id": str(row.import_batch_id) if row.import_batch_id else None,
            "filename": row.original_filename,
            "status": row.extraction_status,
            "page_count": row.page_count,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/calendar/pdf-intake/imports/{document_id}", summary="Get calendar PDF import")
async def get_calendar_pdf_import(
    document_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)
    row = await db.scalar(select(CalendarSourceDocument).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")
    return {
        "document_id": str(row.id),
        "import_batch_id": str(row.import_batch_id) if row.import_batch_id else None,
        "filename": row.original_filename,
        "status": row.extraction_status,
        "page_count": row.page_count,
        "extracted_char_count": row.extracted_char_count,
        "error": row.extraction_error,
    }


@router.get("/calendar/pdf-intake/imports/{document_id}/pages", summary="Get paginated PDF page evidence")
async def get_calendar_pdf_pages(
    document_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    exists = await db.scalar(
        select(CalendarSourceDocument.id).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id)
    )
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            select(CalendarSourcePage)
            .where(CalendarSourcePage.tenant_id == tenant.id, CalendarSourcePage.source_document_id == document_id)
            .order_by(CalendarSourcePage.page_number.asc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    total = await db.scalar(
        select(func.count(CalendarSourcePage.id)).where(CalendarSourcePage.tenant_id == tenant.id, CalendarSourcePage.source_document_id == document_id)
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "items": [
            {
                "page_number": row.page_number,
                "text_excerpt": row.text_excerpt,
                "extracted_char_count": row.extracted_char_count,
            }
            for row in rows
        ],
    }


@router.post("/calendar/pdf-intake/imports/{document_id}/extract", summary="Extract calendar candidates from parsed PDF pages")
async def extract_calendar_pdf_candidates(
    document_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    document = await db.scalar(
        select(CalendarSourceDocument).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id)
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")
    if document.extraction_status == "ocr_required":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="OCR is required for this document and is intentionally deferred.")

    batch = await db.scalar(select(ImportBatch).where(ImportBatch.tenant_id == tenant.id, ImportBatch.id == document.import_batch_id))
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")

    # Idempotent extraction: clear previous proposed/edited candidates only.
    stale = (
        await db.execute(
            select(CalendarEventCandidate).where(
                CalendarEventCandidate.tenant_id == tenant.id,
                CalendarEventCandidate.source_document_id == document_id,
                CalendarEventCandidate.candidate_status.in_(["proposed", "edited"]),
            )
        )
    ).scalars().all()
    for row in stale:
        row.candidate_status = "rejected"

    pages = (
        await db.execute(
            select(CalendarSourcePage)
            .where(CalendarSourcePage.tenant_id == tenant.id, CalendarSourcePage.source_document_id == document_id)
            .order_by(CalendarSourcePage.page_number.asc())
        )
    ).scalars().all()
    extracted = _extract_lines([(row.page_number, row.extracted_text) for row in pages])

    created_count = 0
    for row_number, row in enumerate(extracted[: settings.timetable_calendar_pdf_max_candidates], start=1):
        source_page = next((page for page in pages if page.page_number == row["page_number"]), None)
        candidate = CalendarEventCandidate(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            source_document_id=document.id,
            source_page_id=(source_page.id if source_page else None),
            proposed_event_name=row["name"],
            proposed_description=row["description"],
            proposed_start_date=row["start_date"],
            proposed_end_date=row["end_date"],
            proposed_event_type=row["event_type"],
            proposed_teaching_day_effect=row["teaching_day_effect"],
            confidence_score=int(row["classification"].get("confidence", 60)),
            candidate_status="proposed",
            date_parse_status=row["date_parse_status"],
            uncertainty_note=row["uncertainty_note"],
            classification_json=row["classification"],
            validation_issues_json=row["issues"],
            source_payload={"line": row["line"], "page_number": row["page_number"]},
        )
        db.add(candidate)
        db.add(
            ImportRowResult(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                import_batch_id=batch.id,
                row_number=row_number,
                status="valid" if not row["issues"]["blockers"] else "invalid",
                action="none",
                entity_reference_id=candidate.id,
                severity="warning" if row["issues"]["warnings"] else "information",
                sheet_name=f"page_{row['page_number']}",
                error_code=(row["issues"]["blockers"][0] if row["issues"]["blockers"] else None),
                error_message=row["uncertainty_note"],
                normalized_data={"event_type": row["event_type"]},
                row_data={"line": row["line"], "page_number": row["page_number"]},
            )
        )
        created_count += 1

    document.extraction_status = "processed"
    batch.status = "parsing"
    batch.total_rows = created_count
    batch.valid_rows = created_count
    batch.completed_at = _now()

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_pdf.extracted",
        entity_type="CalendarSourceDocument",
        entity_id=document.id,
        actor_id=actor.id,
        details={"candidates_created": created_count},
    )
    await db.commit()

    return {"document_id": str(document.id), "candidate_count": created_count, "status": document.extraction_status}


@router.get("/calendar/pdf-intake/imports/{document_id}/candidates", summary="Get paginated extracted candidates")
async def list_calendar_pdf_candidates(
    document_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            select(CalendarEventCandidate)
            .where(CalendarEventCandidate.tenant_id == tenant.id, CalendarEventCandidate.source_document_id == document_id)
            .order_by(CalendarEventCandidate.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    total = await db.scalar(
        select(func.count(CalendarEventCandidate.id)).where(
            CalendarEventCandidate.tenant_id == tenant.id,
            CalendarEventCandidate.source_document_id == document_id,
        )
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "items": [_candidate_payload(row) for row in rows],
    }


@router.patch("/calendar/pdf-intake/candidates/{candidate_id}", summary="Edit extracted calendar candidate")
async def edit_calendar_candidate(
    candidate_id: uuid.UUID,
    body: CandidateEditRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarEventCandidate).where(CalendarEventCandidate.tenant_id == tenant.id, CalendarEventCandidate.id == candidate_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    if row.candidate_status in {"approved", "committed", "rejected"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate is finalized and cannot be edited.")

    if body.proposed_event_name is not None:
        row.proposed_event_name = _clean_required_text(body.proposed_event_name, label="proposed_event_name")
    if body.proposed_description is not None:
        row.proposed_description = body.proposed_description
    if body.proposed_start_date is not None:
        row.proposed_start_date = body.proposed_start_date
    if body.proposed_end_date is not None:
        row.proposed_end_date = body.proposed_end_date
    if body.proposed_event_type is not None:
        row.proposed_event_type = body.proposed_event_type
    if body.proposed_teaching_day_effect is not None:
        row.proposed_teaching_day_effect = body.proposed_teaching_day_effect

    if row.proposed_end_date and row.proposed_start_date and row.proposed_end_date < row.proposed_start_date:
        row.date_parse_status = "invalid_range"
        row.validation_issues_json = {"warnings": [], "blockers": ["invalid_range"]}
    row.candidate_status = "edited"
    row.reviewed_by_user_id = actor.id
    row.reviewed_at = _now()

    await db.commit()
    return _candidate_payload(row)


@router.post("/calendar/pdf-intake/candidates/{candidate_id}/approve", summary="Approve extracted candidate")
async def approve_calendar_candidate(
    candidate_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarEventCandidate).where(CalendarEventCandidate.tenant_id == tenant.id, CalendarEventCandidate.id == candidate_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    blockers = list((row.validation_issues_json or {}).get("blockers", []))
    if blockers:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate has blockers and cannot be approved.")

    row.candidate_status = "approved"
    row.approved_by_user_id = actor.id
    row.approved_at = _now()
    await db.commit()
    return _candidate_payload(row)


@router.post("/calendar/pdf-intake/candidates/{candidate_id}/reject", summary="Reject extracted candidate")
async def reject_calendar_candidate(
    candidate_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarEventCandidate).where(CalendarEventCandidate.tenant_id == tenant.id, CalendarEventCandidate.id == candidate_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    row.candidate_status = "rejected"
    row.uncertainty_note = _clean_required_text(body.reason, label="reason")
    row.reviewed_by_user_id = actor.id
    row.reviewed_at = _now()
    await db.commit()
    return _candidate_payload(row)


@router.post("/calendar/pdf-intake/imports/{document_id}/validate", summary="Validate approved candidates")
async def validate_calendar_pdf_batch(
    document_id: uuid.UUID,
    body: ValidatePdfBatchRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    document = await db.scalar(select(CalendarSourceDocument).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")

    batch = await db.scalar(select(ImportBatch).where(ImportBatch.tenant_id == tenant.id, ImportBatch.id == document.import_batch_id))
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")

    rows = (
        await db.execute(
            select(CalendarEventCandidate).where(
                CalendarEventCandidate.tenant_id == tenant.id,
                CalendarEventCandidate.source_document_id == document.id,
            )
        )
    ).scalars().all()

    blockers = 0
    warnings = 0
    approved_count = 0
    for row in rows:
        issues = row.validation_issues_json or {}
        blockers += len(issues.get("blockers", []))
        warnings += len(issues.get("warnings", []))
        if row.candidate_status == "approved":
            approved_count += 1

    if body.require_approved_only and approved_count == 0:
        blockers += 1

    batch.status = "validated" if blockers == 0 else "validation_failed"
    batch.invalid_rows = blockers
    batch.valid_rows = max(0, len(rows) - blockers)
    batch.completed_at = _now()
    await db.commit()

    return {
        "document_id": str(document.id),
        "batch_id": str(batch.id),
        "status": batch.status,
        "approved_candidates": approved_count,
        "blocker_count": blockers,
        "warning_count": warnings,
    }


@router.post("/calendar/pdf-intake/imports/{document_id}/commit", summary="Commit approved candidates to operational calendar")
async def commit_calendar_pdf_batch(
    document_id: uuid.UUID,
    body: CommitApprovedCandidatesRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    document = await db.scalar(select(CalendarSourceDocument).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")

    batch = await db.scalar(select(ImportBatch).where(ImportBatch.tenant_id == tenant.id, ImportBatch.id == document.import_batch_id))
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")

    if batch.committed_at is not None:
        return {
            "batch_id": str(batch.id),
            "status": "already_committed",
            "created_events": batch.created_rows,
            "skipped": batch.skipped_rows,
        }
    if batch.status != "validated":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch must be validated before commit.")

    candidates = (
        await db.execute(
            select(CalendarEventCandidate)
            .where(
                CalendarEventCandidate.tenant_id == tenant.id,
                CalendarEventCandidate.source_document_id == document.id,
                CalendarEventCandidate.candidate_status == "approved",
            )
            .order_by(CalendarEventCandidate.created_at.asc())
        )
    ).scalars().all()
    if not candidates:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No approved candidates available for commit.")

    default_scope = body.default_scope or EventScope(scope_type="public_information", public_information=True)
    validated_scope = await _validate_scope(db=db, tenant_id=tenant.id, scope=default_scope)

    created_events = 0
    for candidate in candidates:
        if candidate.proposed_start_date is None or candidate.proposed_end_date is None:
            continue
        event = OperationalCalendarEvent(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            event_name=_clean_required_text(candidate.proposed_event_name, label="proposed_event_name"),
            description=candidate.proposed_description,
            start_date=candidate.proposed_start_date,
            end_date=candidate.proposed_end_date,
            is_all_day=True,
            event_type=candidate.proposed_event_type,
            teaching_day_effect=candidate.proposed_teaching_day_effect,
            source_type="pdf_extraction",
            review_status="approved",
            lifecycle_status="approved",
            version_number=1,
            source_reference=str(document.id),
            import_batch_id=batch.id,
            original_source_text=str(candidate.source_payload.get("line") or ""),
            impact_scope_json=validated_scope,
            created_by_user_id=actor.id,
            reviewed_by_user_id=actor.id,
            approved_by_user_id=actor.id,
            is_active=True,
        )
        db.add(event)
        impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=validated_scope)
        plan = await _create_notification_plan(
            db=db,
            tenant_id=tenant.id,
            actor=actor,
            event=event,
            trigger_reason="event_updated",
            impact=impact,
            subject=f"Calendar intake candidate committed: {event.event_name}",
            message=f"Committed from PDF intake for {event.start_date.isoformat()}.",
            channels=impact.get("recommended_channels") or ["in_app"],
        )
        event.notification_plan_status = "planned"
        event.notification_plan_json = {"plan_id": str(plan.id)}
        await _append_version(
            db=db,
            tenant_id=tenant.id,
            event=event,
            change_type="created",
            actor=actor,
            previous_values={},
            reason="pdf_commit",
            source_type="pdf_extraction",
            impacted=impact,
            notification_plan_id=plan.id,
        )

        candidate.candidate_status = "committed"
        candidate.applied_event_id = event.id
        created_events += 1

    batch.created_rows = created_events
    batch.updated_rows = 0
    batch.skipped_rows = len(candidates) - created_events
    batch.status = "committed"
    batch.committed_at = _now()
    batch.completed_at = _now()
    document.extraction_status = "committed"

    readiness = await compute_timetable_input_readiness(db, tenant.id)

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_pdf.committed",
        entity_type="ImportBatch",
        entity_id=batch.id,
        actor_id=actor.id,
        details={"created_events": created_events, "readiness_blockers": readiness.get("blocker_count", 0)},
    )
    await db.commit()

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "created_events": created_events,
        "skipped": batch.skipped_rows,
        "readiness": readiness,
    }


@router.post("/calendar/pdf-intake/imports/{document_id}/cancel", summary="Cancel calendar PDF intake batch")
async def cancel_calendar_pdf_batch(
    document_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    document = await db.scalar(select(CalendarSourceDocument).where(CalendarSourceDocument.tenant_id == tenant.id, CalendarSourceDocument.id == document_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar PDF import not found.")

    batch = await db.scalar(select(ImportBatch).where(ImportBatch.tenant_id == tenant.id, ImportBatch.id == document.import_batch_id))
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    if batch.committed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Committed batches cannot be cancelled.")

    document.extraction_status = "cancelled"
    batch.status = "cancelled"
    batch.completed_at = _now()
    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="timetable_setup.calendar_pdf.cancelled",
        entity_type="ImportBatch",
        entity_id=batch.id,
        actor_id=actor.id,
        details={"reason": _clean_required_text(body.reason, label="reason")},
    )
    await db.commit()

    return {"batch_id": str(batch.id), "status": batch.status}


@router.get("/calendar/pdf-intake/imports/{document_id}/diagnostics", summary="Diagnostics for extracted candidates")
async def get_calendar_pdf_diagnostics(
    document_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    rows = (
        await db.execute(
            select(CalendarEventCandidate).where(
                CalendarEventCandidate.tenant_id == tenant.id,
                CalendarEventCandidate.source_document_id == document_id,
            )
        )
    ).scalars().all()

    diagnostics: list[dict[str, Any]] = []
    for row in rows:
        issues = row.validation_issues_json or {}
        warnings = list(issues.get("warnings", []))
        blockers = list(issues.get("blockers", []))
        diagnostics.append(
            {
                "candidate_id": str(row.id),
                "status": row.candidate_status,
                "warnings": warnings,
                "blockers": blockers,
                "date_parse_status": row.date_parse_status,
                "uncertainty_note": row.uncertainty_note,
            }
        )

    return {
        "document_id": str(document_id),
        "diagnostics": diagnostics,
        "blocker_count": sum(len(item["blockers"]) for item in diagnostics),
        "warning_count": sum(len(item["warnings"]) for item in diagnostics),
    }


@router.get("/calendar/notification-plans", summary="List notification plans")
async def list_notification_plans(
    event_id: uuid.UUID | None = Query(default=None),
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    stmt = select(CalendarNotificationPlan).where(CalendarNotificationPlan.tenant_id == tenant.id)
    if event_id is not None:
        stmt = stmt.where(CalendarNotificationPlan.event_id == event_id)
    rows = (await db.execute(stmt.order_by(CalendarNotificationPlan.created_at.desc()))).scalars().all()
    return [
        {
            "id": str(row.id),
            "event_id": str(row.event_id),
            "event_version_number": row.event_version_number,
            "trigger_reason": row.trigger_reason,
            "affected_count": row.affected_count,
            "approval_required": row.approval_required,
            "approval_status": row.approval_status,
            "outbox_status": row.outbox_status,
        }
        for row in rows
    ]


@router.get("/calendar/notification-plans/{plan_id}", summary="Get notification plan")
async def get_notification_plan(
    plan_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarNotificationPlan).where(CalendarNotificationPlan.tenant_id == tenant.id, CalendarNotificationPlan.id == plan_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification plan not found.")
    return {
        "id": str(row.id),
        "event_id": str(row.event_id),
        "event_version_number": row.event_version_number,
        "trigger_reason": row.trigger_reason,
        "audience_scope": row.audience_scope,
        "affected_count": row.affected_count,
        "subject": row.subject,
        "proposed_message": row.proposed_message,
        "channels": row.channels,
        "scheduled_at": row.scheduled_at,
        "reminder_settings": row.reminder_settings,
        "urgency": row.urgency,
        "approval_required": row.approval_required,
        "approval_status": row.approval_status,
        "outbox_status": row.outbox_status,
        "delivery_summary": row.delivery_summary,
        "audit_reference_json": row.audit_reference_json,
    }


@router.post("/calendar/notification-plans/{plan_id}/approve", summary="Approve notification plan")
async def approve_notification_plan(
    plan_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarNotificationPlan).where(CalendarNotificationPlan.tenant_id == tenant.id, CalendarNotificationPlan.id == plan_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification plan not found.")

    row.approval_status = "approved"
    row.outbox_status = "ready"
    row.approved_by_user_id = actor.id
    row.approved_at = _now()
    row.audit_reference_json = {"approval_reason": _clean_required_text(body.reason, label="reason")}

    notification = Notification(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        recipient_user_id=actor.id,
        source_type="calendar_notification_plan",
        source_id=row.id,
        category="calendar_update_plan",
        title=row.subject,
        body=row.proposed_message,
        delivery_status="pending",
        attempt_count=0,
    )
    db.add(notification)
    row.related_notification_id = notification.id

    await db.commit()
    return {"id": str(row.id), "approval_status": row.approval_status, "outbox_status": row.outbox_status}


@router.post("/calendar/notification-plans/{plan_id}/cancel", summary="Cancel notification plan")
async def cancel_notification_plan(
    plan_id: uuid.UUID,
    body: EventStatusReasonRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    row = await db.scalar(select(CalendarNotificationPlan).where(CalendarNotificationPlan.tenant_id == tenant.id, CalendarNotificationPlan.id == plan_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification plan not found.")

    row.approval_status = "cancelled"
    row.outbox_status = "cancelled"
    row.audit_reference_json = {"cancel_reason": _clean_required_text(body.reason, label="reason")}
    await db.commit()
    return {"id": str(row.id), "approval_status": row.approval_status, "outbox_status": row.outbox_status}


@router.post("/calendar/events/{event_id}/notification-plan", summary="Draft a notification plan for an event")
async def draft_event_notification_plan(
    event_id: uuid.UUID,
    body: NotificationPlanDraftRequest,
    tenant: Tenant = Depends(resolve_tenant),
    actor: User = Depends(resolve_authenticated_leadership),
    db: AsyncSession = Depends(get_db),
):
    _ensure_actor_tenant(actor, tenant)
    await set_tenant_context(db, tenant.id)

    item = await db.scalar(select(OperationalCalendarEvent).where(OperationalCalendarEvent.tenant_id == tenant.id, OperationalCalendarEvent.id == event_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

    impact = await calculate_event_impact(db=db, tenant_id=tenant.id, scope=item.impact_scope_json)
    plan = await _create_notification_plan(
        db=db,
        tenant_id=tenant.id,
        actor=actor,
        event=item,
        trigger_reason=body.trigger_reason,
        impact=impact,
        subject=body.subject,
        message=body.proposed_message,
        channels=body.channels,
        urgency=body.urgency,
        scheduled_at=body.scheduled_at,
        reminder_settings=body.reminder_settings,
    )

    previous = _event_snapshot(item)
    item.notification_plan_status = "planned"
    item.notification_plan_json = {"plan_id": str(plan.id), "approval_status": plan.approval_status}
    item.version_number += 1
    await _append_version(
        db=db,
        tenant_id=tenant.id,
        event=item,
        change_type="scope_changed" if body.trigger_reason == "event_updated" else "edited",
        actor=actor,
        previous_values=previous,
        reason=f"notification_plan:{body.trigger_reason}",
        source_type=item.source_type,
        impacted=impact,
        notification_plan_id=plan.id,
    )
    await db.commit()

    return {"plan_id": str(plan.id), "approval_required": plan.approval_required, "approval_status": plan.approval_status}
