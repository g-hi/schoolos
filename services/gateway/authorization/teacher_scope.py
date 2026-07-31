from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Class, SubjectOffering, TeacherAssignment, TimetableEntry


@dataclass(frozen=True)
class TeacherScopeDecision:
    authorized: bool
    source: str
    scope: str
    canonical_history_exists: bool
    reason: str
    matched_assignment_id: uuid.UUID | None = None
    matched_timetable_entry_id: uuid.UUID | None = None


async def teacher_has_homeroom_scope(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    klass: Class,
    effective_date: date_type,
) -> TeacherScopeDecision:
    canonical_exists_stmt = select(TeacherAssignment.id).where(
        TeacherAssignment.tenant_id == tenant_id,
        TeacherAssignment.class_id == klass.id,
        TeacherAssignment.assignment_type == "homeroom",
    ).limit(1)
    canonical_history_exists = (await db.scalar(canonical_exists_stmt)) is not None

    if canonical_history_exists:
        canonical_match_stmt = select(TeacherAssignment.id).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.class_id == klass.id,
            TeacherAssignment.teacher_id == teacher_id,
            TeacherAssignment.assignment_type == "homeroom",
            TeacherAssignment.is_active.is_(True),
            TeacherAssignment.start_date <= effective_date,
            or_(TeacherAssignment.end_date.is_(None), TeacherAssignment.end_date >= effective_date),
        ).limit(1)
        assignment_id = await db.scalar(canonical_match_stmt)
        if assignment_id is not None:
            return TeacherScopeDecision(
                authorized=True,
                source="canonical",
                scope="homeroom",
                canonical_history_exists=True,
                reason="matched_active_homeroom_assignment",
                matched_assignment_id=assignment_id,
            )
        return TeacherScopeDecision(
            authorized=False,
            source="canonical",
            scope="homeroom",
            canonical_history_exists=True,
            reason="canonical_homeroom_assignment_not_found",
        )

    if klass.class_teacher_id == teacher_id:
        return TeacherScopeDecision(
            authorized=True,
            source="legacy",
            scope="homeroom",
            canonical_history_exists=False,
            reason="matched_legacy_class_teacher",
        )

    return TeacherScopeDecision(
        authorized=False,
        source="none",
        scope="homeroom",
        canonical_history_exists=False,
        reason="legacy_class_teacher_mismatch",
    )


async def teacher_has_subject_scope(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    klass: Class,
    subject_id: uuid.UUID,
    timetable_entry_id: uuid.UUID,
    effective_date: date_type,
) -> TeacherScopeDecision:
    canonical_exists_stmt = select(TeacherAssignment.id).where(
        TeacherAssignment.tenant_id == tenant_id,
        TeacherAssignment.class_id == klass.id,
        TeacherAssignment.assignment_type == "subject_teacher",
    ).limit(1)
    canonical_history_exists = (await db.scalar(canonical_exists_stmt)) is not None

    if canonical_history_exists:
        canonical_match_stmt = (
            select(TeacherAssignment.id)
            .join(SubjectOffering, SubjectOffering.id == TeacherAssignment.subject_offering_id)
            .where(
                TeacherAssignment.tenant_id == tenant_id,
                TeacherAssignment.class_id == klass.id,
                TeacherAssignment.teacher_id == teacher_id,
                TeacherAssignment.assignment_type == "subject_teacher",
                TeacherAssignment.is_active.is_(True),
                TeacherAssignment.start_date <= effective_date,
                or_(TeacherAssignment.end_date.is_(None), TeacherAssignment.end_date >= effective_date),
                SubjectOffering.tenant_id == tenant_id,
                SubjectOffering.subject_id == subject_id,
                SubjectOffering.is_active.is_(True),
            )
            .limit(1)
        )
        assignment_id = await db.scalar(canonical_match_stmt)
        if assignment_id is not None:
            return TeacherScopeDecision(
                authorized=True,
                source="canonical",
                scope="subject_teacher",
                canonical_history_exists=True,
                reason="matched_active_subject_assignment",
                matched_assignment_id=assignment_id,
            )
        return TeacherScopeDecision(
            authorized=False,
            source="canonical",
            scope="subject_teacher",
            canonical_history_exists=True,
            reason="canonical_subject_assignment_not_found",
        )

    timetable_stmt = select(TimetableEntry.id).where(
        TimetableEntry.id == timetable_entry_id,
        TimetableEntry.tenant_id == tenant_id,
        TimetableEntry.class_id == klass.id,
        TimetableEntry.teacher_id == teacher_id,
        TimetableEntry.subject_id == subject_id,
        TimetableEntry.academic_year == klass.academic_year,
        TimetableEntry.is_active.is_(True),
    ).limit(1)
    timetable_match = await db.scalar(timetable_stmt)

    if timetable_match is not None:
        return TeacherScopeDecision(
            authorized=True,
            source="legacy",
            scope="subject_teacher",
            canonical_history_exists=False,
            reason="matched_legacy_timetable",
            matched_timetable_entry_id=timetable_match,
        )

    return TeacherScopeDecision(
        authorized=False,
        source="none",
        scope="subject_teacher",
        canonical_history_exists=False,
        reason="legacy_timetable_assignment_not_found",
    )


async def teacher_has_weekly_report_class_scope(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    klass: Class,
    effective_date: date_type,
) -> TeacherScopeDecision:
    canonical_exists_stmt = select(TeacherAssignment.id).where(
        TeacherAssignment.tenant_id == tenant_id,
        TeacherAssignment.teacher_id == teacher_id,
        TeacherAssignment.class_id == klass.id,
    ).limit(1)
    canonical_history_exists = (await db.scalar(canonical_exists_stmt)) is not None

    if canonical_history_exists:
        active_homeroom_stmt = select(TeacherAssignment.id).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.teacher_id == teacher_id,
            TeacherAssignment.class_id == klass.id,
            TeacherAssignment.assignment_type == "homeroom",
            TeacherAssignment.is_active.is_(True),
            TeacherAssignment.start_date <= effective_date,
            or_(TeacherAssignment.end_date.is_(None), TeacherAssignment.end_date >= effective_date),
        ).limit(1)
        assignment_id = await db.scalar(active_homeroom_stmt)
        if assignment_id is not None:
            return TeacherScopeDecision(
                authorized=True,
                source="canonical",
                scope="weekly_report_class",
                canonical_history_exists=True,
                reason="matched_active_homeroom_assignment",
                matched_assignment_id=assignment_id,
            )
        return TeacherScopeDecision(
            authorized=False,
            source="canonical",
            scope="weekly_report_class",
            canonical_history_exists=True,
            reason="canonical_history_without_active_homeroom",
        )

    if klass.class_teacher_id == teacher_id:
        return TeacherScopeDecision(
            authorized=True,
            source="legacy",
            scope="weekly_report_class",
            canonical_history_exists=False,
            reason="matched_legacy_class_teacher",
        )

    timetable_stmt = select(TimetableEntry.id).where(
        TimetableEntry.tenant_id == tenant_id,
        TimetableEntry.class_id == klass.id,
        TimetableEntry.teacher_id == teacher_id,
        TimetableEntry.academic_year == klass.academic_year,
        TimetableEntry.is_active.is_(True),
    ).limit(1)
    timetable_match = await db.scalar(timetable_stmt)
    if timetable_match is not None:
        return TeacherScopeDecision(
            authorized=True,
            source="legacy",
            scope="weekly_report_class",
            canonical_history_exists=False,
            reason="matched_legacy_timetable",
            matched_timetable_entry_id=timetable_match,
        )

    return TeacherScopeDecision(
        authorized=False,
        source="none",
        scope="weekly_report_class",
        canonical_history_exists=False,
        reason="legacy_class_teacher_and_timetable_mismatch",
    )