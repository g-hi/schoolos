from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.candidates import CandidateGenerationOptions, generate_timetable_candidates
from services.gateway.timetable_setup.problem_builder import SchedulingProblemBuildError, build_scheduling_problem
from shared.db.models import (
    Timetable,
    TimetableGenerationConfiguration,
    TimetableGenerationLock,
    TimetableVersion,
    TimetableVersionAssignment,
    User,
)


LIFECYCLE_STATUSES = {"candidate", "under_review", "approved", "published", "superseded", "cancelled"}
REPAIR_SCOPE_LEVELS = {"minimum", "affected_entities", "grade", "whole_school"}


class TimetableVersionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class MaterializedVersionResult:
    timetable: Timetable
    version: TimetableVersion
    assignment_count: int


def _now() -> datetime:
    return datetime.now(UTC)


def _assignment_key(assignment: dict[str, Any]) -> str:
    return f"{assignment['occurrence_id']}|{assignment.get('parallel_child_id') or ''}"


def _normalize_occupied_keys(assignment: dict[str, Any]) -> list[str]:
    occupied = assignment.get("occupied_period_keys") or []
    if not occupied:
        occupied = [assignment["period_key"]]
    return [str(item) for item in occupied]


def _ensure_principal(actor: User) -> None:
    if actor.role != "principal":
        raise TimetableVersionError(
            code="principal_required",
            message="Principal authority is required for this action.",
            status_code=403,
        )


async def _get_configuration(db: AsyncSession, *, tenant_id: uuid.UUID, configuration_id: uuid.UUID) -> TimetableGenerationConfiguration:
    configuration = await db.scalar(
        select(TimetableGenerationConfiguration).where(
            TimetableGenerationConfiguration.id == configuration_id,
            TimetableGenerationConfiguration.tenant_id == tenant_id,
        )
    )
    if configuration is None:
        raise TimetableVersionError(code="configuration_not_found", message="Generation configuration not found.", status_code=404)
    return configuration


async def _get_version(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> TimetableVersion:
    version = await db.scalar(
        select(TimetableVersion).where(
            TimetableVersion.id == version_id,
            TimetableVersion.tenant_id == tenant_id,
        )
    )
    if version is None:
        raise TimetableVersionError(code="timetable_version_not_found", message="Timetable version not found.", status_code=404)
    return version


async def _get_or_create_timetable(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    academic_year_id: uuid.UUID,
    term_id: uuid.UUID,
    campus_id: uuid.UUID | None,
    created_by_user_id: uuid.UUID,
) -> Timetable:
    timetable = await db.scalar(
        select(Timetable).where(
            Timetable.tenant_id == tenant_id,
            Timetable.academic_year_id == academic_year_id,
            Timetable.term_id == term_id,
            Timetable.campus_id == campus_id,
        )
    )
    if timetable is not None:
        return timetable

    timetable = Timetable(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        term_id=term_id,
        campus_id=campus_id,
        name=f"{term_id} timetable",
        status="active",
        created_by_user_id=created_by_user_id,
        is_active=True,
    )
    db.add(timetable)
    await db.flush()
    return timetable


async def _next_version_number(db: AsyncSession, *, timetable_id: uuid.UUID) -> int:
    value = await db.scalar(select(func.max(TimetableVersion.version_number)).where(TimetableVersion.timetable_id == timetable_id))
    return int(value or 0) + 1


def _validate_candidate_assignments(problem: Any, assignments: tuple[dict[str, Any], ...]) -> None:
    class_ids = {item.class_id for item in problem.classes}
    subject_ids = {item.subject_id for item in problem.subjects}
    teacher_ids = {item.teacher_id for item in problem.teachers}
    room_ids = {item.room_id for item in problem.rooms}
    requirement_ids = {item.requirement_id for item in problem.teaching_requirements}

    for row in assignments:
        if row["class_id"] not in class_ids:
            raise TimetableVersionError(
                code="candidate_assignment_scope_invalid",
                message="Candidate assignment includes unknown class reference.",
                status_code=409,
                details={"class_id": row["class_id"]},
            )
        if row.get("subject_id") and row["subject_id"] not in subject_ids:
            raise TimetableVersionError(
                code="candidate_assignment_scope_invalid",
                message="Candidate assignment includes unknown subject reference.",
                status_code=409,
                details={"subject_id": row["subject_id"]},
            )
        if row.get("teacher_id") and row["teacher_id"] not in teacher_ids:
            raise TimetableVersionError(
                code="candidate_assignment_scope_invalid",
                message="Candidate assignment includes unknown teacher reference.",
                status_code=409,
                details={"teacher_id": row["teacher_id"]},
            )
        if row.get("room_id") and row["room_id"] not in room_ids:
            raise TimetableVersionError(
                code="candidate_assignment_scope_invalid",
                message="Candidate assignment includes unknown room reference.",
                status_code=409,
                details={"room_id": row["room_id"]},
            )
        if row.get("requirement_id") and row["requirement_id"] not in requirement_ids:
            raise TimetableVersionError(
                code="candidate_assignment_scope_invalid",
                message="Candidate assignment includes unknown requirement reference.",
                status_code=409,
                details={"requirement_id": row["requirement_id"]},
            )


async def materialize_candidate_version(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: User,
    configuration_id: uuid.UUID,
    candidate_id: str,
    expected_problem_fingerprint: str,
    candidate_profiles: tuple[str, ...] = ("configured",),
    candidate_count: int = 3,
    candidate_profile: str | None = None,
    effective_from: date_type | None = None,
    label: str | None = None,
    expected_assignment_fingerprint: str | None = None,
) -> MaterializedVersionResult:
    configuration = await _get_configuration(db, tenant_id=tenant_id, configuration_id=configuration_id)

    try:
        build = await build_scheduling_problem(db=db, tenant_id=tenant_id, configuration_id=configuration_id)
    except SchedulingProblemBuildError as exc:
        raise TimetableVersionError(code="problem_build_failed", message=str(exc), status_code=422) from exc

    if build.problem.source_fingerprint != expected_problem_fingerprint:
        raise TimetableVersionError(
            code="stale_candidate_preview",
            message="Scheduling problem changed since candidate preview.",
            status_code=409,
            details={
                "expected_problem_fingerprint": expected_problem_fingerprint,
                "actual_problem_fingerprint": build.problem.source_fingerprint,
            },
        )

    options = CandidateGenerationOptions(
        candidate_count=max(1, int(candidate_count)),
        deterministic=True,
        candidate_profiles=tuple(candidate_profiles),
        include_comparison=True,
        include_explanation_facts=True,
        response_mode="detailed",
    ).normalized()

    generated = generate_timetable_candidates(build.problem, options=options)
    selected = next((item for item in generated.candidates if item.candidate_id == candidate_id), None)
    if selected is None:
        raise TimetableVersionError(
            code="candidate_not_found",
            message="Candidate is unavailable for the current deterministic preview context.",
            status_code=404,
        )

    if expected_assignment_fingerprint and selected.assignment_fingerprint != expected_assignment_fingerprint:
        raise TimetableVersionError(
            code="stale_candidate_preview",
            message="Candidate assignment fingerprint no longer matches preview.",
            status_code=409,
            details={
                "expected_assignment_fingerprint": expected_assignment_fingerprint,
                "actual_assignment_fingerprint": selected.assignment_fingerprint,
            },
        )

    _validate_candidate_assignments(build.problem, selected.assignments)

    timetable = await _get_or_create_timetable(
        db,
        tenant_id=tenant_id,
        academic_year_id=configuration.academic_year_id,
        term_id=configuration.term_id,
        campus_id=configuration.campus_id,
        created_by_user_id=actor.id,
    )
    version_number = await _next_version_number(db, timetable_id=timetable.id)

    version = TimetableVersion(
        id=uuid.uuid4(),
        timetable_id=timetable.id,
        tenant_id=tenant_id,
        version_number=version_number,
        generation_configuration_id=configuration.id,
        source_candidate_id=selected.candidate_id,
        source_problem_id=selected.problem_id,
        source_problem_fingerprint=selected.problem_fingerprint,
        source_assignment_fingerprint=selected.assignment_fingerprint,
        generation_mode=selected.generation_mode,
        baseline_version_id=configuration.baseline_timetable_version_id,
        lifecycle_status="candidate",
        effective_from=effective_from,
        candidate_profile=candidate_profile or selected.candidate_profile,
        quality_snapshot_json={
            "quality_score": selected.quality_score,
            "quality_band": selected.quality_band,
            "quality_components": [
                {
                    "key": item.key,
                    "score": item.score,
                    "max_score": item.max_score,
                    "weight": item.weight,
                    "priority": item.priority,
                    "status": item.status,
                    "evidence": item.evidence,
                }
                for item in selected.quality_components
            ],
            "metrics": dict(selected.metrics),
            "preference_summary": dict(selected.preference_summary),
            "fairness_summary": dict(selected.fairness_summary),
            "workload_summary": dict(selected.workload_summary),
            "gap_summary": dict(selected.gap_summary),
            "subject_distribution_summary": dict(selected.subject_distribution_summary),
            "room_summary": dict(selected.room_summary),
            "hard_constraint_summary": dict(selected.hard_constraint_summary),
            "label": label,
        },
        repair_impact_snapshot_json=dict(selected.repair_impact_summary),
        diff_summary_snapshot_json={},
        solver_provenance_json={
            "solver_status": selected.solver_status,
            "solver_runtime_ms": selected.solver_runtime_ms,
            "solver_statistics": dict(selected.solver_statistics),
            "diagnostics": list(selected.diagnostics),
            "warnings": list(selected.warnings),
            "provenance": dict(selected.provenance),
        },
        created_by_user_id=actor.id,
    )
    db.add(version)
    await db.flush()

    assignments: list[TimetableVersionAssignment] = []
    for row in selected.assignments:
        assignments.append(
            TimetableVersionAssignment(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                timetable_version_id=version.id,
                occurrence_id=row["occurrence_id"],
                requirement_id=row.get("requirement_id"),
                class_id=row["class_id"],
                subject_id=row.get("subject_id"),
                teacher_id=row.get("teacher_id"),
                room_id=row.get("room_id"),
                day_key=row["day_key"],
                period_key=row["period_key"],
                periods_per_session=max(1, int(row.get("periods_per_session") or 1)),
                occupied_period_keys_json=_normalize_occupied_keys(row),
                parallel_block_id=row.get("parallel_block_id"),
                parallel_child_id=row.get("parallel_child_id"),
                fixed=bool(row.get("fixed", False)),
                lock_state=row.get("lock_state"),
                protection_snapshot_json={"lock_state": row.get("lock_state")},
                provenance_json={"source": "phase_10c_batch5_materialized_candidate", "candidate_id": selected.candidate_id},
                assignment_key=_assignment_key(row),
            )
        )
    db.add_all(assignments)
    await db.flush()

    return MaterializedVersionResult(timetable=timetable, version=version, assignment_count=len(assignments))


async def transition_submit(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID, actor: User) -> TimetableVersion:
    version = await _get_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.lifecycle_status != "candidate":
        raise TimetableVersionError(code="invalid_transition", message="Only candidate versions can be submitted.", status_code=409)

    assignment_count = await db.scalar(
        select(func.count(TimetableVersionAssignment.id)).where(
            TimetableVersionAssignment.tenant_id == tenant_id,
            TimetableVersionAssignment.timetable_version_id == version.id,
        )
    )
    if int(assignment_count or 0) == 0:
        raise TimetableVersionError(code="version_assignments_missing", message="Version has no assignments.", status_code=409)

    version.lifecycle_status = "under_review"
    version.submitted_at = _now()
    version.submitted_by_user_id = actor.id
    await db.flush()
    return copy.copy(version)


async def transition_approve(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID, actor: User) -> TimetableVersion:
    _ensure_principal(actor)
    version = await _get_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.lifecycle_status != "under_review":
        raise TimetableVersionError(code="invalid_transition", message="Only under_review versions can be approved.", status_code=409)

    version.lifecycle_status = "approved"
    version.approved_at = _now()
    version.approved_by_user_id = actor.id
    await db.flush()
    return copy.copy(version)


async def transition_cancel(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID, actor: User) -> TimetableVersion:
    version = await _get_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.lifecycle_status not in {"candidate", "under_review", "approved"}:
        raise TimetableVersionError(code="invalid_transition", message="Version cannot be cancelled from current state.", status_code=409)

    version.lifecycle_status = "cancelled"
    version.superseded_at = _now()
    version.superseded_by_user_id = actor.id
    await db.flush()
    return copy.copy(version)


async def transition_publish(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID, actor: User, effective_from: date_type) -> TimetableVersion:
    _ensure_principal(actor)
    version = await _get_version(db, tenant_id=tenant_id, version_id=version_id)
    previous_version_state = {
        "lifecycle_status": getattr(version, "lifecycle_status", None),
        "effective_from": getattr(version, "effective_from", None),
        "effective_until": getattr(version, "effective_until", None),
        "published_at": getattr(version, "published_at", None),
        "published_by_user_id": getattr(version, "published_by_user_id", None),
    }
    previous_states: list[tuple[Any, dict[str, Any]]] = []
    try:
        if version.lifecycle_status != "approved":
            raise TimetableVersionError(code="invalid_transition", message="Only approved versions can be published.", status_code=409)

        assignment_count = await db.scalar(
            select(func.count(TimetableVersionAssignment.id)).where(
                TimetableVersionAssignment.tenant_id == tenant_id,
                TimetableVersionAssignment.timetable_version_id == version.id,
            )
        )
        if int(assignment_count or 0) == 0:
            raise TimetableVersionError(code="version_assignments_missing", message="Version has no assignments.", status_code=409)

        existing_same_start = await db.scalar(
            select(TimetableVersion).where(
                TimetableVersion.tenant_id == tenant_id,
                TimetableVersion.timetable_id == version.timetable_id,
                TimetableVersion.id != version.id,
                TimetableVersion.lifecycle_status == "published",
                TimetableVersion.effective_from == effective_from,
            )
        )
        if existing_same_start is not None and not isinstance(existing_same_start, int):
            raise TimetableVersionError(
                code="publication_overlap_same_date",
                message="A published version already exists for the same effective date.",
                status_code=409,
            )

        overlap_result = await db.execute(
            select(TimetableVersion)
            .where(
                TimetableVersion.tenant_id == tenant_id,
                TimetableVersion.timetable_id == version.timetable_id,
                TimetableVersion.id != version.id,
                TimetableVersion.lifecycle_status == "published",
                TimetableVersion.effective_from.is_not(None),
                TimetableVersion.effective_from < effective_from,
                or_(
                    TimetableVersion.effective_until.is_(None),
                    TimetableVersion.effective_until > effective_from,
                ),
            )
            .order_by(TimetableVersion.effective_from.asc())
        )
        overlapping = []
        if overlap_result is not None:
            scalars = getattr(overlap_result, "scalars", None)
            if scalars is not None:
                overlapping = scalars().all()
            elif isinstance(overlap_result, list):
                overlapping = overlap_result

        published_at = _now()
        for previous in overlapping:
            previous_states.append(
                (
                    previous,
                    {
                        "effective_until": getattr(previous, "effective_until", None),
                        "lifecycle_status": getattr(previous, "lifecycle_status", None),
                        "superseded_at": getattr(previous, "superseded_at", None),
                        "superseded_by_user_id": getattr(previous, "superseded_by_user_id", None),
                        "superseded_by_version_id": getattr(previous, "superseded_by_version_id", None),
                    },
                )
            )
            previous.effective_until = effective_from
            previous.lifecycle_status = "superseded"
            previous.superseded_at = published_at
            previous.superseded_by_user_id = actor.id
            previous.superseded_by_version_id = version.id

        version.effective_from = effective_from
        version.lifecycle_status = "published"
        version.published_at = published_at
        version.published_by_user_id = actor.id
        await db.flush()
    except Exception:
        version.lifecycle_status = previous_version_state["lifecycle_status"]
        version.effective_from = previous_version_state["effective_from"]
        version.effective_until = previous_version_state["effective_until"]
        version.published_at = previous_version_state["published_at"]
        version.published_by_user_id = previous_version_state["published_by_user_id"]
        for previous, state in previous_states:
            previous.effective_until = state["effective_until"]
            previous.lifecycle_status = state["lifecycle_status"]
            previous.superseded_at = state["superseded_at"]
            previous.superseded_by_user_id = state["superseded_by_user_id"]
            previous.superseded_by_version_id = state["superseded_by_version_id"]
        await db.rollback()
        raise
    return copy.copy(version)


async def resolve_effective_version(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    timetable_id: uuid.UUID,
    on_date: date_type,
) -> TimetableVersion | None:
    candidates = (
        await db.execute(
            select(TimetableVersion)
            .where(
                TimetableVersion.tenant_id == tenant_id,
                TimetableVersion.timetable_id == timetable_id,
                TimetableVersion.lifecycle_status.in_(("published", "superseded")),
                TimetableVersion.effective_from.is_not(None),
                TimetableVersion.effective_from <= on_date,
                or_(TimetableVersion.effective_until.is_(None), TimetableVersion.effective_until > on_date),
            )
            .order_by(TimetableVersion.effective_from.asc(), TimetableVersion.version_number.asc())
        )
    ).scalars().all()

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    last = candidates[-1]
    if last.effective_from == on_date:
        return last

    return candidates[-2]


def _assignment_row_to_dict(row: TimetableVersionAssignment) -> dict[str, Any]:
    return {
        "assignment_key": row.assignment_key,
        "occurrence_id": row.occurrence_id,
        "requirement_id": row.requirement_id,
        "class_id": row.class_id,
        "subject_id": row.subject_id,
        "teacher_id": row.teacher_id,
        "room_id": row.room_id,
        "day_key": row.day_key,
        "period_key": row.period_key,
        "periods_per_session": row.periods_per_session,
        "occupied_period_keys": list(row.occupied_period_keys_json or []),
        "parallel_block_id": row.parallel_block_id,
        "parallel_child_id": row.parallel_child_id,
        "fixed": bool(row.fixed),
        "lock_state": row.lock_state,
        "protection_snapshot": dict(row.protection_snapshot_json or {}),
        "provenance": dict(row.provenance_json or {}),
    }


async def load_version_assignments(db: AsyncSession, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> list[TimetableVersionAssignment]:
    return (
        await db.execute(
            select(TimetableVersionAssignment)
            .where(
                TimetableVersionAssignment.tenant_id == tenant_id,
                TimetableVersionAssignment.timetable_version_id == version_id,
            )
            .order_by(TimetableVersionAssignment.assignment_key.asc())
        )
    ).scalars().all()


def _class_facing_parallel_map(items: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for row in items.values():
        block_id = row.get("parallel_block_id")
        if not block_id:
            continue
        key = f"parallel_block:{block_id}"
        current = payload.get(key)
        if current is None or (row.get("period_key") or "") < (current.get("period_key") or ""):
            payload[key] = {
                "parallel_block_id": block_id,
                "class_id": row.get("class_id"),
                "period_key": row.get("period_key"),
                "occupied_period_keys": tuple(row.get("occupied_period_keys") or []),
            }
    return payload


def compute_version_diff(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    left_map = {row["assignment_key"]: row for row in left}
    right_map = {row["assignment_key"]: row for row in right}
    keys = sorted(set(left_map.keys()) | set(right_map.keys()))

    unchanged = 0
    moved = 0
    teacher_changes = 0
    room_changes = 0
    added = 0
    removed = 0

    affected_teachers: set[str] = set()
    affected_classes: set[str] = set()
    affected_rooms: set[str] = set()
    details: list[dict[str, Any]] = []

    for key in keys:
        lrow = left_map.get(key)
        rrow = right_map.get(key)
        if lrow is None and rrow is not None:
            added += 1
            affected_classes.add(rrow["class_id"])
            if rrow.get("teacher_id"):
                affected_teachers.add(rrow["teacher_id"])
            if rrow.get("room_id"):
                affected_rooms.add(rrow["room_id"])
            details.append({"kind": "added", "assignment_key": key})
            continue
        if rrow is None and lrow is not None:
            removed += 1
            affected_classes.add(lrow["class_id"])
            if lrow.get("teacher_id"):
                affected_teachers.add(lrow["teacher_id"])
            if lrow.get("room_id"):
                affected_rooms.add(lrow["room_id"])
            details.append({"kind": "removed", "assignment_key": key})
            continue

        assert lrow is not None and rrow is not None
        row_changed = False
        row_fields: dict[str, Any] = {}

        left_span = tuple(lrow.get("occupied_period_keys") or [lrow.get("period_key")])
        right_span = tuple(rrow.get("occupied_period_keys") or [rrow.get("period_key")])
        if lrow.get("period_key") != rrow.get("period_key") or left_span != right_span:
            moved += 1
            row_changed = True
            row_fields["period"] = {"left": lrow.get("period_key"), "right": rrow.get("period_key"), "left_span": list(left_span), "right_span": list(right_span)}

        if lrow.get("teacher_id") != rrow.get("teacher_id"):
            teacher_changes += 1
            row_changed = True
            row_fields["teacher"] = {"left": lrow.get("teacher_id"), "right": rrow.get("teacher_id")}
            if lrow.get("teacher_id"):
                affected_teachers.add(lrow["teacher_id"])
            if rrow.get("teacher_id"):
                affected_teachers.add(rrow["teacher_id"])

        if lrow.get("room_id") != rrow.get("room_id"):
            room_changes += 1
            row_changed = True
            row_fields["room"] = {"left": lrow.get("room_id"), "right": rrow.get("room_id")}
            if lrow.get("room_id"):
                affected_rooms.add(lrow["room_id"])
            if rrow.get("room_id"):
                affected_rooms.add(rrow["room_id"])

        if row_changed:
            affected_classes.add(lrow["class_id"])
            if "period" in row_fields and not ({"teacher", "room"} & set(row_fields.keys())):
                details.append({"kind": "moved", "assignment_key": key})
            else:
                details.append({"kind": "changed", "assignment_key": key, "fields": row_fields})
        else:
            unchanged += 1

    left_parallel = _class_facing_parallel_map(left_map)
    right_parallel = _class_facing_parallel_map(right_map)
    parallel_block_moves = 0
    for key in sorted(set(left_parallel.keys()) & set(right_parallel.keys())):
        if left_parallel[key]["period_key"] != right_parallel[key]["period_key"]:
            parallel_block_moves += 1

    base = max(len(keys), 1)
    unchanged_percentage = round((unchanged / base) * 100.0, 4)

    return {
        "moved": moved,
        "teacher_changes": teacher_changes,
        "room_changes": room_changes,
        "counts": {
            "unchanged": unchanged,
            "moved_period_or_span": moved,
            "teacher_changes": teacher_changes,
            "room_changes": room_changes,
            "added": added,
            "removed": removed,
            "parallel_block_moves": parallel_block_moves,
        },
        "affected_teachers": sorted(affected_teachers),
        "affected_classes": sorted(affected_classes),
        "affected_rooms": sorted(affected_rooms),
        "unchanged_percentage": unchanged_percentage,
        "details": details,
    }


async def version_diff(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    left_version_id: uuid.UUID,
    right_version_id: uuid.UUID,
) -> dict[str, Any]:
    left_version = await _get_version(db, tenant_id=tenant_id, version_id=left_version_id)
    right_version = await _get_version(db, tenant_id=tenant_id, version_id=right_version_id)
    if left_version.timetable_id != right_version.timetable_id:
        raise TimetableVersionError(code="incompatible_version_context", message="Versions belong to different timetable scopes.", status_code=409)

    left_rows = [_assignment_row_to_dict(item) for item in await load_version_assignments(db, tenant_id=tenant_id, version_id=left_version_id)]
    right_rows = [_assignment_row_to_dict(item) for item in await load_version_assignments(db, tenant_id=tenant_id, version_id=right_version_id)]
    return compute_version_diff(left_rows, right_rows)


async def repair_impact_preview(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    configuration_id: uuid.UUID,
    repair_reason: str,
    scope_level: str,
    trigger_teacher_ids: tuple[str, ...],
    trigger_class_ids: tuple[str, ...],
    trigger_room_ids: tuple[str, ...],
    trigger_requirement_ids: tuple[str, ...],
    trigger_occurrence_ids: tuple[str, ...],
    trigger_parallel_block_ids: tuple[str, ...],
) -> dict[str, Any]:
    if scope_level not in REPAIR_SCOPE_LEVELS:
        raise TimetableVersionError(code="repair_scope_invalid", message="Repair scope level is not supported.", status_code=422)

    configuration = await _get_configuration(db, tenant_id=tenant_id, configuration_id=configuration_id)
    baseline_id = configuration.baseline_timetable_version_id
    if baseline_id is None:
        raise TimetableVersionError(code="repair_requires_baseline", message="Repair mode requires canonical baseline_timetable_version_id.", status_code=409)

    baseline = await _get_version(db, tenant_id=tenant_id, version_id=baseline_id)
    rows = await load_version_assignments(db, tenant_id=tenant_id, version_id=baseline.id)
    assignments = [_assignment_row_to_dict(item) for item in rows]

    lock_rows = (
        await db.execute(
            select(TimetableGenerationLock).where(
                TimetableGenerationLock.tenant_id == tenant_id,
                TimetableGenerationLock.configuration_id == configuration_id,
                TimetableGenerationLock.is_active.is_(True),
                TimetableGenerationLock.is_manual_hard_lock.is_(True),
            )
        )
    ).scalars().all()

    manual_locked_keys: set[str] = set()
    for lock in lock_rows:
        reference_code = getattr(lock, "target_reference_code", None)
        if getattr(lock, "is_manual_hard_lock", False) and reference_code:
            manual_locked_keys.add(str(reference_code))

    class_grade: dict[str, str] = {}
    for row in (await build_scheduling_problem(db=db, tenant_id=tenant_id, configuration_id=configuration_id)).problem.classes:
        class_grade[row.class_id] = row.grade_reference

    direct: list[dict[str, Any]] = []
    conditional: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []

    direct_keys: set[str] = set()
    for row in assignments:
        key = row["assignment_key"]
        if key in manual_locked_keys:
            manual.append(row)
            continue

        is_direct = any(
            (
                row.get("teacher_id") in trigger_teacher_ids,
                row.get("class_id") in trigger_class_ids,
                row.get("room_id") in trigger_room_ids,
                row.get("requirement_id") in trigger_requirement_ids,
                row.get("occurrence_id") in trigger_occurrence_ids,
                row.get("parallel_block_id") in trigger_parallel_block_ids,
            )
        )
        if is_direct:
            direct.append(row)
            direct_keys.add(key)

    direct_class_ids = {row.get("class_id") for row in direct}
    direct_teacher_ids = {row.get("teacher_id") for row in direct if row.get("teacher_id")}
    direct_room_ids = {row.get("room_id") for row in direct if row.get("room_id")}
    affected_grades = {class_grade[class_id] for class_id in direct_class_ids if class_id in class_grade}

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    suggested_next_scope: str | None = None

    if manual:
        blockers.append({"code": "direct_assignment_manually_locked", "count": len(manual)})

    has_blockers = bool(blockers)

    for row in assignments:
        key = row["assignment_key"]
        if key in manual_locked_keys:
            continue

        if scope_level == "whole_school":
            conditional.append(row)
            continue

        if key in direct_keys:
            if scope_level == "minimum":
                if not blockers and not row.get("parallel_block_id"):
                    protected.append(row)
                continue
            conditional.append(row)
            continue

        if scope_level == "minimum":
            protected.append(row)
            continue

        if scope_level == "grade":
            grade = class_grade.get(row.get("class_id"))
            if grade in affected_grades:
                conditional.append(row)
            else:
                protected.append(row)
            continue

        # affected_entities
        if row.get("class_id") in direct_class_ids or row.get("teacher_id") in direct_teacher_ids or row.get("room_id") in direct_room_ids:
            conditional.append(row)
        else:
            protected.append(row)

    if scope_level == "minimum" and not blockers and len(direct) > 0 and len(conditional) == 0 and len(protected) > 0:
        warnings.append({"code": "repair_scope_tight", "message": "Minimum scope protects all non-direct assignments."})
        suggested_next_scope = "affected_entities"

    return {
        "baseline_version_id": str(baseline.id),
        "repair_reason": repair_reason,
        "repair_scope": scope_level,
        "direct_count": len(direct),
        "conditionally_movable_count": len(conditional),
        "protected_count": len(protected),
        "manual_lock_count": len(manual),
        "direct_assignments": [
            {"assignment_key": row["assignment_key"], "occurrence_id": row["occurrence_id"], "class_id": row["class_id"], "teacher_id": row.get("teacher_id"), "room_id": row.get("room_id"), "parallel_block_id": row.get("parallel_block_id")}
            for row in direct
        ],
        "affected_teachers": sorted({row.get("teacher_id") for row in direct if row.get("teacher_id")}),
        "affected_classes": sorted({row.get("class_id") for row in direct if row.get("class_id")}),
        "affected_rooms": sorted({row.get("room_id") for row in direct if row.get("room_id")}),
        "affected_parallel_blocks": sorted({row.get("parallel_block_id") for row in direct if row.get("parallel_block_id")}),
        "stability": configuration.stability_mode,
        "blockers": blockers,
        "warnings": warnings,
        "suggested_next_scope": suggested_next_scope,
    }


def version_to_summary(version: TimetableVersion, *, assignment_count: int, include_assignments: bool = False, assignments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "id": str(version.id),
        "timetable_id": str(version.timetable_id),
        "tenant_id": str(version.tenant_id),
        "version_number": version.version_number,
        "generation_configuration_id": str(version.generation_configuration_id) if version.generation_configuration_id else None,
        "source_candidate_id": version.source_candidate_id,
        "source_problem_id": version.source_problem_id,
        "source_problem_fingerprint": version.source_problem_fingerprint,
        "source_assignment_fingerprint": version.source_assignment_fingerprint,
        "generation_mode": version.generation_mode,
        "baseline_version_id": str(version.baseline_version_id) if version.baseline_version_id else None,
        "lifecycle_status": version.lifecycle_status,
        "effective_from": version.effective_from.isoformat() if version.effective_from else None,
        "effective_until": version.effective_until.isoformat() if version.effective_until else None,
        "submitted_at": version.submitted_at.isoformat() if version.submitted_at else None,
        "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "superseded_at": version.superseded_at.isoformat() if version.superseded_at else None,
        "superseded_by_version_id": str(version.superseded_by_version_id) if version.superseded_by_version_id else None,
        "candidate_profile": version.candidate_profile,
        "quality_snapshot": dict(version.quality_snapshot_json or {}),
        "repair_impact_snapshot": dict(version.repair_impact_snapshot_json or {}),
        "diff_summary_snapshot": dict(version.diff_summary_snapshot_json or {}),
        "solver_provenance": dict(version.solver_provenance_json or {}),
        "assignment_count": assignment_count,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "created_by_user_id": str(version.created_by_user_id) if version.created_by_user_id else None,
    }
    if include_assignments:
        payload["assignments"] = assignments or []
    return payload
