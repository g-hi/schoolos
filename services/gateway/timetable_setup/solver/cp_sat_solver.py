from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import ortools
from ortools.sat.python import cp_model

from services.gateway.timetable_setup.scheduling_problem import (
    FixedSessionRecord,
    LogicalPeriod,
    SchedulingProblem,
)
from services.gateway.timetable_setup.solver.constraint_registry import extract_constraints
from services.gateway.timetable_setup.solver.contracts import (
    SolveOptions,
    SolverAssignment,
    SolverDiagnostic,
    SolverMetrics,
    SolverObjectiveComponent,
    SolverResult,
)
from services.gateway.timetable_setup.solver.objective_registry import build_priority_coefficients, normalize_priority


@dataclass(frozen=True, slots=True)
class PlacementUnit:
    occurrence_id: str
    requirement_id: str | None
    class_id: str
    subject_id: str | None
    teacher_options: tuple[str, ...]
    room_options: tuple[str, ...]
    fixed_slot_key: str | None
    fixed: bool
    periods_per_session: int
    parallel_block_id: str | None
    parallel_children: tuple[tuple[str, str | None, str | None, str | None], ...]


def _status_to_contract(status: int, *, has_solution: bool, timed_out: bool) -> tuple[str, bool, bool]:
    if status == cp_model.OPTIMAL:
        return "optimal", True, True
    if status == cp_model.FEASIBLE:
        if timed_out:
            return "timeout_with_solution", True, False
        return "feasible", True, False
    if status == cp_model.INFEASIBLE:
        return "infeasible", False, False
    if status == cp_model.MODEL_INVALID:
        return "invalid_problem", False, False
    if timed_out and not has_solution:
        return "timeout_without_solution", False, False
    return "unknown", has_solution, False


def _day_from_slot(slot_key: str) -> int:
    return int(slot_key.split(":")[0][1:])


def _period_from_slot(slot_key: str) -> int:
    return int(slot_key.split(":")[1][1:])


def _slot_from_payload(payload: dict[str, Any]) -> str | None:
    weekday = payload.get("weekday")
    period_number = payload.get("period_number")
    if isinstance(weekday, int) and isinstance(period_number, int):
        return f"d{weekday}:p{period_number}"
    return None


def _priority_map(problem: SchedulingProblem) -> dict[str, str]:
    payload = {
        "teacher_preferences": "high",
        "workload_balance": "normal",
        "subject_distribution": "normal",
        "minimize_teacher_gaps": "normal",
        "minimize_timetable_disruption": "high",
        "preserve_existing_assignments": "high",
        "preference_fairness": "normal",
    }
    for item in problem.optimization_objectives:
        payload[item.objective_key] = normalize_priority(item.priority_level)
    return payload


def _stability_factor(mode: str) -> int:
    mapping = {
        "very_high": 8,
        "high": 4,
        "balanced": 2,
        "flexible": 1,
    }
    return mapping.get(mode, 2)


def _logical_period_maps(problem: SchedulingProblem) -> tuple[list[str], dict[tuple[int, int], LogicalPeriod]]:
    period_by_day_number: dict[tuple[int, int], LogicalPeriod] = {}
    teaching_slots: list[str] = []
    for item in sorted(problem.logical_periods, key=lambda row: (row.day_of_week, row.period_number, row.key)):
        period_by_day_number[(item.day_of_week, item.period_number)] = item
        if item.is_teaching_period:
            teaching_slots.append(item.key)
    return teaching_slots, period_by_day_number


def _consecutive_span(start_slot: str, length: int, period_by_day_number: dict[tuple[int, int], LogicalPeriod]) -> tuple[str, ...] | None:
    if length <= 0:
        return None

    day = _day_from_slot(start_slot)
    period = _period_from_slot(start_slot)
    occupied: list[str] = []
    for offset in range(length):
        row = period_by_day_number.get((day, period + offset))
        if row is None:
            return None
        if not row.is_teaching_period:
            return None
        occupied.append(row.key)
    return tuple(occupied)


def _expand_units(problem: SchedulingProblem) -> tuple[list[PlacementUnit], list[SolverDiagnostic]]:
    diagnostics: list[SolverDiagnostic] = []

    requirements = {item.requirement_id: item for item in problem.teaching_requirements}
    rooms_by_type: dict[str, list[str]] = {}
    for room in problem.rooms:
        rooms_by_type.setdefault(room.room_type, []).append(room.room_id)

    fixed_by_requirement: dict[str, list[FixedSessionRecord]] = {}
    for item in problem.fixed_sessions:
        fixed_by_requirement.setdefault(item.requirement_id, []).append(item)

    units: list[PlacementUnit] = []
    for requirement in sorted(problem.teaching_requirements, key=lambda row: row.requirement_id):
        fixed_items = sorted(fixed_by_requirement.get(requirement.requirement_id, []), key=lambda row: row.fixed_session_id)
        if len(fixed_items) > requirement.weekly_sessions:
            diagnostics.append(
                SolverDiagnostic(
                    code="fixed_sessions_exceed_weekly_sessions",
                    message="Fixed-session count exceeds required weekly sessions.",
                    severity="blocker",
                    entity_type="teaching_requirement",
                    entity_id=requirement.requirement_id,
                )
            )
            continue

        periods_per_session = max(1, int(requirement.periods_per_session))
        teacher_options = tuple(sorted({item for item in ([requirement.teacher_id] if requirement.teacher_id else list(requirement.eligible_teacher_ids)) if item}))
        if not teacher_options:
            diagnostics.append(
                SolverDiagnostic(
                    code="no_eligible_teacher",
                    message="No eligible teacher is available for requirement.",
                    severity="blocker",
                    entity_type="teaching_requirement",
                    entity_id=requirement.requirement_id,
                )
            )
            continue

        if requirement.specialist_room_type:
            room_options = tuple(sorted(rooms_by_type.get(requirement.specialist_room_type, [])))
            if not room_options:
                diagnostics.append(
                    SolverDiagnostic(
                        code="no_compatible_room",
                        message="No compatible room exists for specialist room requirement.",
                        severity="blocker",
                        entity_type="teaching_requirement",
                        entity_id=requirement.requirement_id,
                    )
                )
                continue
        else:
            room_options = tuple()

        for index in range(requirement.weekly_sessions):
            fixed_slot = fixed_items[index].period_key if index < len(fixed_items) else None
            fixed_room = fixed_items[index].room_id if index < len(fixed_items) else None
            effective_rooms = room_options
            if fixed_room:
                effective_rooms = (fixed_room,)
            units.append(
                PlacementUnit(
                    occurrence_id=f"{requirement.requirement_id}#occ{index + 1}",
                    requirement_id=requirement.requirement_id,
                    class_id=requirement.class_id,
                    subject_id=requirement.subject_id,
                    teacher_options=teacher_options,
                    room_options=effective_rooms,
                    fixed_slot_key=fixed_slot,
                    fixed=bool(fixed_slot),
                    periods_per_session=periods_per_session,
                    parallel_block_id=None,
                    parallel_children=tuple(),
                )
            )

    for block in sorted(problem.parallel_lesson_blocks, key=lambda row: row.block_id):
        if not block.children:
            diagnostics.append(
                SolverDiagnostic(
                    code="parallel_block_without_children",
                    message="Parallel block has no active children.",
                    severity="blocker",
                    entity_type="parallel_block",
                    entity_id=block.block_id,
                )
            )
            continue

        child_weekly: list[int] = []
        child_spans: list[int] = []
        children_payload: list[tuple[str, str | None, str | None, str | None]] = []
        for child in sorted(block.children, key=lambda row: (row.sequence_order or 0, row.child_id)):
            teacher_id = child.teacher_id
            subject_id = child.subject_id
            requirement_id = child.requirement_id
            room_id = child.room_id
            child_span: int | None = None
            if requirement_id and requirement_id in requirements:
                req = requirements[requirement_id]
                child_weekly.append(req.weekly_sessions)
                child_span = max(1, int(req.periods_per_session))
                if teacher_id is None and req.teacher_id:
                    teacher_id = req.teacher_id
                if teacher_id is None and req.eligible_teacher_ids:
                    teacher_id = sorted(req.eligible_teacher_ids)[0]
                if subject_id is None:
                    subject_id = req.subject_id
            else:
                child_weekly.append(1)

            if teacher_id is None:
                diagnostics.append(
                    SolverDiagnostic(
                        code="parallel_child_teacher_unresolved",
                        message="Parallel child has no resolved teacher identity.",
                        severity="blocker",
                        entity_type="parallel_child",
                        entity_id=child.child_id,
                    )
                )
            children_payload.append((child.child_id, teacher_id, subject_id, room_id))
            if child_span is not None:
                child_spans.append(child_span)

        if len(set(child_weekly)) > 1:
            diagnostics.append(
                SolverDiagnostic(
                    code="parallel_block_frequency_mismatch",
                    message="Parallel block child requirements have inconsistent weekly frequencies.",
                    severity="blocker",
                    entity_type="parallel_block",
                    entity_id=block.block_id,
                )
            )
            continue

        periods_per_session = child_spans[0] if child_spans else 1
        if any(span != periods_per_session for span in child_spans):
            diagnostics.append(
                SolverDiagnostic(
                    code="parallel_block_period_span_mismatch",
                    message="Parallel block child requirements have inconsistent periods_per_session values.",
                    severity="blocker",
                    entity_type="parallel_block",
                    entity_id=block.block_id,
                )
            )
            continue

        count = child_weekly[0] if child_weekly else 1
        for index in range(count):
            units.append(
                PlacementUnit(
                    occurrence_id=f"{block.block_id}#occ{index + 1}",
                    requirement_id=None,
                    class_id=block.class_id,
                    subject_id=None,
                    teacher_options=tuple(),
                    room_options=tuple(),
                    fixed_slot_key=None,
                    fixed=False,
                    periods_per_session=periods_per_session,
                    parallel_block_id=block.block_id,
                    parallel_children=tuple(children_payload),
                )
            )

    return sorted(units, key=lambda row: row.occurrence_id), diagnostics


def _precondition_result(problem: SchedulingProblem, diagnostics: tuple[SolverDiagnostic, ...], status: str = "invalid_problem") -> SolverResult:
    return SolverResult(
        problem_id=problem.problem_id,
        problem_fingerprint=problem.source_fingerprint,
        solver_name="or-tools-cp-sat",
        solver_version=str(ortools.__version__),
        status=status,
        feasible=False,
        optimal=False,
        assignments=tuple(),
        objective_score=None,
        objective_components=tuple(),
        hard_constraint_summary={"enforced": False},
        diagnostics=diagnostics,
        warnings=tuple(),
        metrics=SolverMetrics(
            runtime_ms=0,
            objective_score=None,
            boolean_variables=0,
            integer_variables=0,
            constraint_count=0,
            placement_unit_count=0,
            logical_slot_count=0,
            eligible_teacher_links=0,
            room_links=0,
            parallel_block_count=len(problem.parallel_lesson_blocks),
            teacher_gap_count=0,
        ),
        solver_statistics={},
        input_counts={
            "teachers": len(problem.teachers),
            "classes": len(problem.classes),
            "subjects": len(problem.subjects),
            "rooms": len(problem.rooms),
            "requirements": len(problem.teaching_requirements),
            "parallel_blocks": len(problem.parallel_lesson_blocks),
        },
    )


def solve_scheduling_problem(problem: SchedulingProblem, options: SolveOptions | None = None) -> SolverResult:
    solve_options = options or SolveOptions()

    blockers: list[SolverDiagnostic] = []
    warnings: list[SolverDiagnostic] = []

    if not problem.solver_eligible:
        blockers.append(SolverDiagnostic(code="solver_eligible_false", message="SchedulingProblem is not solver-eligible.", severity="blocker"))
    if not problem.validation_summary.valid or problem.validation_summary.blocker_count > 0:
        blockers.append(SolverDiagnostic(code="problem_validation_blockers", message="SchedulingProblem validation contains blockers.", severity="blocker"))
    if problem.generation_mode == "repair" and not problem.baseline.supported:
        blockers.append(SolverDiagnostic(code="repair_baseline_missing", message="Repair baseline is unsupported in production path.", severity="blocker"))

    constraints = extract_constraints(problem.policy_constraints)
    blockers.extend(constraints.unsupported_hard)
    warnings.extend(constraints.unsupported_soft)

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    units, unit_diagnostics = _expand_units(problem)
    blockers.extend(item for item in unit_diagnostics if item.severity == "blocker")
    warnings.extend(item for item in unit_diagnostics if item.severity != "blocker")
    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    teaching_slots, period_by_day_number = _logical_period_maps(problem)
    if not teaching_slots:
        return _precondition_result(
            problem,
            (
                SolverDiagnostic(
                    code="missing_teaching_slots",
                    message="No teaching logical slots available for solving.",
                    severity="blocker",
                ),
            ),
            status="invalid_problem",
        )

    class_unavailable = {key: set(value) for key, value in constraints.class_unavailable.items()}
    room_unavailable = {key: set(value) for key, value in constraints.room_unavailable.items()}
    teacher_unavailable = {key: set(value) for key, value in constraints.teacher_unavailable.items()}

    for override in problem.generation_overrides:
        if override.strength != "hard":
            continue
        payload = override.payload or {}
        slot = _slot_from_payload(payload)
        if slot is None:
            blockers.append(
                SolverDiagnostic(
                    code="invalid_hard_generation_override_payload",
                    message="Hard generation override payload is missing weekday/period_number.",
                    severity="blocker",
                    entity_type="generation_override",
                    entity_id=override.override_id,
                )
            )
            continue

        if override.override_type == "teacher_free_period" and override.scope_reference_id:
            teacher_unavailable.setdefault(override.scope_reference_id, set()).add(slot)
            continue
        if override.override_type == "class_free_period" and override.scope_reference_id:
            class_unavailable.setdefault(override.scope_reference_id, set()).add(slot)
            continue
        if override.override_type == "room_free_period" and override.scope_reference_id:
            room_unavailable.setdefault(override.scope_reference_id, set()).add(slot)
            continue

        blockers.append(
            SolverDiagnostic(
                code="unsupported_hard_generation_override",
                message="Unsupported hard generation override type for solver encoding.",
                severity="blocker",
                entity_type="generation_override",
                entity_id=override.override_id,
                details={"override_type": override.override_type},
            )
        )

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    for pref in problem.teacher_preferences:
        if pref.strength != "hard":
            continue
        if pref.preference_type in {"unavailable_selected_periods", "avoid_selected_periods"}:
            for weekday in pref.weekday_values or tuple(range(0, 7)):
                for period in pref.period_numbers:
                    teacher_unavailable.setdefault(pref.teacher_id, set()).add(f"d{weekday}:p{period}")
        elif pref.preference_type == "avoid_first_period":
            min_period = min(_period_from_slot(slot) for slot in teaching_slots)
            for weekday in pref.weekday_values or tuple(range(0, 7)):
                teacher_unavailable.setdefault(pref.teacher_id, set()).add(f"d{weekday}:p{min_period}")
        elif pref.preference_type == "avoid_last_period":
            max_period = max(_period_from_slot(slot) for slot in teaching_slots)
            for weekday in pref.weekday_values or tuple(range(0, 7)):
                teacher_unavailable.setdefault(pref.teacher_id, set()).add(f"d{weekday}:p{max_period}")
        elif pref.preference_type == "avoid_selected_days":
            for weekday in pref.weekday_values:
                for slot in teaching_slots:
                    if _day_from_slot(slot) == weekday:
                        teacher_unavailable.setdefault(pref.teacher_id, set()).add(slot)
        else:
            blockers.append(
                SolverDiagnostic(
                    code="unsupported_hard_preference",
                    message="Unsupported hard preference type cannot be ignored.",
                    severity="blocker",
                    entity_type="teacher_preference",
                    entity_id=pref.preference_id,
                    details={"preference_type": pref.preference_type},
                )
            )

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    baseline_by_occurrence: dict[str, dict[str, Any]] = {}
    for item in problem.baseline.assignments:
        occurrence_id = str(item.get("occurrence_id")) if item.get("occurrence_id") is not None else ""
        if occurrence_id:
            baseline_by_occurrence[occurrence_id] = item

    lock_by_occurrence: dict[str, str] = {}
    for lock in problem.locks:
        if lock.target_type != "session_reference":
            if lock.lock_state == "locked":
                blockers.append(
                    SolverDiagnostic(
                        code="unsupported_lock_target",
                        message="Only session_reference locks are currently supported by the solver.",
                        severity="blocker",
                        entity_type="lock",
                        entity_id=lock.lock_id,
                        details={"target_type": lock.target_type},
                    )
                )
            else:
                warnings.append(
                    SolverDiagnostic(
                        code="unsupported_lock_target",
                        message="Non-session lock target was ignored by the solver.",
                        severity="warning",
                        entity_type="lock",
                        entity_id=lock.lock_id,
                        details={"target_type": lock.target_type},
                    )
                )
            continue

        if lock.lock_state in {"locked", "prefer_to_keep"} and not problem.baseline.supported:
            blockers.append(
                SolverDiagnostic(
                    code="lock_requires_baseline",
                    message="Lock constraints require a supported baseline assignment set.",
                    severity="blocker",
                    entity_type="lock",
                    entity_id=lock.lock_id,
                )
            )
            continue

        if lock.target_reference_code:
            lock_by_occurrence[lock.target_reference_code] = lock.lock_state
        if lock.target_reference_id:
            lock_by_occurrence[lock.target_reference_id] = lock.lock_state

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    allowed_starts: dict[str, list[str]] = {}
    occupied_slots: dict[tuple[str, str], tuple[str, ...]] = {}
    teacher_candidates: dict[str, dict[str, tuple[str, ...]]] = {}
    room_candidates: dict[str, dict[str, tuple[str, ...]]] = {}

    class_map = {item.class_id: item for item in problem.classes}
    room_map = {item.room_id: item for item in problem.rooms}

    for unit in units:
        class_row = class_map.get(unit.class_id)
        if class_row is None:
            blockers.append(
                SolverDiagnostic(
                    code="class_not_found",
                    message="Placement unit references a missing class.",
                    severity="blocker",
                    entity_type="class",
                    entity_id=unit.class_id,
                )
            )
            continue

        possible_starts = set(teaching_slots)
        if unit.fixed_slot_key:
            possible_starts.intersection_update({unit.fixed_slot_key})

        start_to_teachers: dict[str, tuple[str, ...]] = {}
        start_to_rooms: dict[str, tuple[str, ...]] = {}

        for start in sorted(possible_starts, key=lambda row: (_day_from_slot(row), _period_from_slot(row), row)):
            span = _consecutive_span(start, unit.periods_per_session, period_by_day_number)
            if span is None:
                continue

            if not set(span).issubset(set(class_row.schedulable_period_keys)):
                continue
            if set(span) & set(class_row.unavailable_period_keys):
                continue
            if set(span) & class_unavailable.get(unit.class_id, set()):
                continue

            if unit.parallel_block_id is None:
                teachers_here = tuple(
                    sorted(
                        item
                        for item in unit.teacher_options
                        if all(slot not in teacher_unavailable.get(item, set()) for slot in span)
                    )
                )
                if not teachers_here:
                    continue

                if unit.room_options:
                    rooms_here = tuple(
                        sorted(
                            item
                            for item in unit.room_options
                            if item in room_map and all(slot not in room_unavailable.get(item, set()) for slot in span)
                        )
                    )
                    if not rooms_here:
                        continue
                else:
                    rooms_here = tuple()

                start_to_teachers[start] = teachers_here
                start_to_rooms[start] = rooms_here
                occupied_slots[(unit.occurrence_id, start)] = span
            else:
                parallel_valid = True
                for _child_id, teacher_id, _subject_id, room_id in unit.parallel_children:
                    if teacher_id and any(slot in teacher_unavailable.get(teacher_id, set()) for slot in span):
                        parallel_valid = False
                        break
                    if room_id and any(slot in room_unavailable.get(room_id, set()) for slot in span):
                        parallel_valid = False
                        break
                if not parallel_valid:
                    continue
                start_to_teachers[start] = tuple()
                start_to_rooms[start] = tuple()
                occupied_slots[(unit.occurrence_id, start)] = span

        if not start_to_teachers:
            if unit.periods_per_session > 1 and unit.fixed_slot_key:
                code = "multi_period_fixed_session_conflict"
                message = "Fixed multi-period occurrence cannot fit required consecutive teaching periods."
            elif unit.periods_per_session > 1:
                code = "no_consecutive_slot_domain"
                message = "No valid consecutive slot domain exists for multi-period occurrence."
            else:
                code = "empty_placement_domain"
                message = "Placement unit has no feasible logical slots."
            blockers.append(
                SolverDiagnostic(
                    code=code,
                    message=message,
                    severity="blocker",
                    entity_type="placement_unit",
                    entity_id=unit.occurrence_id,
                )
            )
            continue

        allowed_starts[unit.occurrence_id] = sorted(start_to_teachers.keys(), key=lambda row: (_day_from_slot(row), _period_from_slot(row), row))
        teacher_candidates[unit.occurrence_id] = start_to_teachers
        room_candidates[unit.occurrence_id] = start_to_rooms

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    model = cp_model.CpModel()
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    z_teacher: dict[tuple[str, str, str], cp_model.IntVar] = {}
    z_room: dict[tuple[str, str, str], cp_model.IntVar] = {}

    for unit in units:
        for start in allowed_starts[unit.occurrence_id]:
            x[(unit.occurrence_id, start)] = model.NewBoolVar(f"x__{unit.occurrence_id}__{start}")

    for unit in units:
        occ = unit.occurrence_id
        for start in allowed_starts[occ]:
            slot_var = x[(occ, start)]
            if unit.parallel_block_id is None:
                teachers_here = teacher_candidates[occ][start]
                if len(teachers_here) == 1:
                    z_teacher[(occ, start, teachers_here[0])] = slot_var
                else:
                    terms: list[cp_model.IntVar] = []
                    for teacher_id in teachers_here:
                        term = model.NewBoolVar(f"teacher__{occ}__{start}__{teacher_id}")
                        z_teacher[(occ, start, teacher_id)] = term
                        terms.append(term)
                    model.Add(sum(terms) == slot_var)

                rooms_here = room_candidates[occ][start]
                if len(rooms_here) == 1:
                    z_room[(occ, start, rooms_here[0])] = slot_var
                elif len(rooms_here) > 1:
                    terms_room: list[cp_model.IntVar] = []
                    for room_id in rooms_here:
                        term_room = model.NewBoolVar(f"room__{occ}__{start}__{room_id}")
                        z_room[(occ, start, room_id)] = term_room
                        terms_room.append(term_room)
                    model.Add(sum(terms_room) == slot_var)

        model.Add(sum(x[(occ, start)] for start in allowed_starts[occ]) == 1)

    # Class-facing collisions (parallel child lessons do not consume extra class-facing rows).
    class_ids = sorted({unit.class_id for unit in units})
    for class_id in class_ids:
        class_units = [unit for unit in units if unit.class_id == class_id]
        for slot in teaching_slots:
            vars_here = [x[(unit.occurrence_id, start)] for unit in class_units for start in allowed_starts[unit.occurrence_id] if slot in occupied_slots[(unit.occurrence_id, start)]]
            if vars_here:
                model.Add(sum(vars_here) <= 1)

    # Teacher collisions across normal units and parallel children.
    teacher_ids = sorted({teacher.teacher_id for teacher in problem.teachers})
    for teacher_id in teacher_ids:
        for slot in teaching_slots:
            vars_here: list[cp_model.IntVar] = []
            for (occ, start, t), var in z_teacher.items():
                if t == teacher_id and slot in occupied_slots[(occ, start)]:
                    vars_here.append(var)
            for unit in units:
                if unit.parallel_block_id is None:
                    continue
                if any(child_teacher == teacher_id for _child_id, child_teacher, _subject, _room in unit.parallel_children):
                    for start in allowed_starts[unit.occurrence_id]:
                        if slot in occupied_slots[(unit.occurrence_id, start)]:
                            vars_here.append(x[(unit.occurrence_id, start)])
            if vars_here:
                model.Add(sum(vars_here) <= 1)

    # Room collisions.
    room_ids = sorted({room.room_id for room in problem.rooms})
    for room_id in room_ids:
        for slot in teaching_slots:
            vars_here_room: list[cp_model.IntVar] = []
            for (occ, start, r), var in z_room.items():
                if r == room_id and slot in occupied_slots[(occ, start)]:
                    vars_here_room.append(var)
            for unit in units:
                if unit.parallel_block_id is None:
                    continue
                if any(child_room == room_id for _child_id, _teacher, _subject, child_room in unit.parallel_children):
                    for start in allowed_starts[unit.occurrence_id]:
                        if slot in occupied_slots[(unit.occurrence_id, start)]:
                            vars_here_room.append(x[(unit.occurrence_id, start)])
            if vars_here_room:
                model.Add(sum(vars_here_room) <= 1)

    # Requirement daily min/max constraints for ordinary units (count occurrences, not occupied periods).
    for requirement in problem.teaching_requirements:
        occ_ids = [unit.occurrence_id for unit in units if unit.requirement_id == requirement.requirement_id]
        if not occ_ids:
            continue
        weekdays = sorted({_day_from_slot(slot) for slot in teaching_slots})
        for weekday in weekdays:
            vars_day: list[cp_model.IntVar] = []
            for occ in occ_ids:
                for start in allowed_starts.get(occ, []):
                    if _day_from_slot(start) == weekday:
                        vars_day.append(x[(occ, start)])
            if vars_day:
                if requirement.max_daily_sessions >= 0:
                    model.Add(sum(vars_day) <= int(requirement.max_daily_sessions))
                if requirement.min_daily_sessions > 0:
                    model.Add(sum(vars_day) >= int(requirement.min_daily_sessions))

    # Policy workload hard limits.
    teach_slot: dict[tuple[str, str], cp_model.IntVar] = {}
    for teacher_id in teacher_ids:
        for slot in teaching_slots:
            vars_here = [
                var
                for (occ, start, t), var in z_teacher.items()
                if t == teacher_id and slot in occupied_slots[(occ, start)]
            ]
            vars_here.extend(
                x[(unit.occurrence_id, start)]
                for unit in units
                for start in allowed_starts[unit.occurrence_id]
                if unit.parallel_block_id is not None
                and slot in occupied_slots[(unit.occurrence_id, start)]
                and any(child_teacher == teacher_id for _child_id, child_teacher, _subject, _room in unit.parallel_children)
            )
            if vars_here:
                agg = model.NewBoolVar(f"teach__{teacher_id}__{slot}")
                model.Add(agg == sum(vars_here))
                teach_slot[(teacher_id, slot)] = agg

    for teacher_id, limit in constraints.teacher_max_daily.items():
        weekdays = sorted({_day_from_slot(slot) for slot in teaching_slots})
        for weekday in weekdays:
            vars_day = [teach_slot[(teacher_id, slot)] for slot in teaching_slots if _day_from_slot(slot) == weekday and (teacher_id, slot) in teach_slot]
            if vars_day:
                model.Add(sum(vars_day) <= int(limit))

    for teacher_id, limit in constraints.teacher_max_consecutive.items():
        days = sorted({_day_from_slot(slot) for slot in teaching_slots})
        periods_by_day: dict[int, list[int]] = {}
        for slot in teaching_slots:
            periods_by_day.setdefault(_day_from_slot(slot), []).append(_period_from_slot(slot))
        for day in days:
            periods = sorted(set(periods_by_day.get(day, [])))
            if len(periods) <= limit:
                continue
            for start_idx in range(0, len(periods) - limit):
                window = periods[start_idx : start_idx + limit + 1]
                vars_window = [teach_slot[(teacher_id, f"d{day}:p{period}")] for period in window if (teacher_id, f"d{day}:p{period}") in teach_slot]
                if len(vars_window) == len(window):
                    model.Add(sum(vars_window) <= int(limit))

    objective_terms: list[tuple[cp_model.IntVar, str, str, int]] = []

    priority_map = _priority_map(problem)
    stability_factor = _stability_factor(problem.stability_mode)

    # Teacher preference penalties.
    pref_penalty_vars: list[cp_model.IntVar] = []
    pref_priority = priority_map.get("teacher_preferences", "high")
    strength_priority = {"strong": "high", "normal": "normal", "low": "low"}

    for pref in problem.teacher_preferences:
        if pref.strength == "hard":
            continue
        affected = set()
        if pref.preference_type in {"avoid_selected_periods", "prefer_selected_periods", "unavailable_selected_periods"}:
            days = pref.weekday_values or tuple(sorted({_day_from_slot(slot) for slot in teaching_slots}))
            for day in days:
                for period in pref.period_numbers:
                    affected.add(f"d{day}:p{period}")
        elif pref.preference_type == "avoid_first_period":
            min_period = min(_period_from_slot(slot) for slot in teaching_slots)
            for day in sorted({_day_from_slot(slot) for slot in teaching_slots}):
                affected.add(f"d{day}:p{min_period}")
        elif pref.preference_type == "avoid_last_period":
            max_period = max(_period_from_slot(slot) for slot in teaching_slots)
            for day in sorted({_day_from_slot(slot) for slot in teaching_slots}):
                affected.add(f"d{day}:p{max_period}")
        elif pref.preference_type in {"prefer_selected_days", "avoid_selected_days"}:
            for slot in teaching_slots:
                if _day_from_slot(slot) in pref.weekday_values:
                    affected.add(slot)

        local_penalties: list[cp_model.IntVar] = []
        teacher_id = pref.teacher_id
        for slot in teaching_slots:
            teach_var = teach_slot.get((teacher_id, slot))
            if teach_var is None:
                continue
            if pref.preference_type.startswith("avoid") or pref.preference_type == "unavailable_selected_periods":
                if slot in affected:
                    local_penalties.append(teach_var)
            elif pref.preference_type.startswith("prefer"):
                if slot not in affected:
                    local_penalties.append(teach_var)
            else:
                warnings.append(
                    SolverDiagnostic(
                        code="unsupported_soft_preference",
                        message="Soft preference type is not mapped and was excluded.",
                        severity="warning",
                        entity_type="teacher_preference",
                        entity_id=pref.preference_id,
                        details={"preference_type": pref.preference_type},
                    )
                )

        if local_penalties:
            penalty = model.NewIntVar(0, len(local_penalties), f"pref_penalty__{pref.preference_id}")
            model.Add(penalty == sum(local_penalties))
            pref_penalty_vars.append(penalty)
            objective_terms.append((penalty, "teacher_preferences", strength_priority.get(pref.strength, pref_priority), len(local_penalties)))

    # Subject daily spread penalties (count occurrences per day by start slot).
    distribution_terms: list[cp_model.IntVar] = []
    for class_id in sorted({item.class_id for item in problem.teaching_requirements}):
        for subject_id in sorted({item.subject_id for item in problem.teaching_requirements if item.class_id == class_id}):
            occ_ids = [unit.occurrence_id for unit in units if unit.class_id == class_id and unit.subject_id == subject_id]
            if len(occ_ids) <= 1:
                continue
            for day in sorted({_day_from_slot(slot) for slot in teaching_slots}):
                vars_day: list[cp_model.IntVar] = []
                for occ in occ_ids:
                    for start in allowed_starts.get(occ, []):
                        if _day_from_slot(start) == day:
                            vars_day.append(x[(occ, start)])
                if not vars_day:
                    continue
                day_count = model.NewIntVar(0, len(occ_ids), f"dist_count__{class_id}__{subject_id}__d{day}")
                model.Add(day_count == sum(vars_day))
                excess = model.NewIntVar(0, len(occ_ids), f"dist_excess__{class_id}__{subject_id}__d{day}")
                model.Add(excess >= day_count - 1)
                distribution_terms.append(excess)

    if distribution_terms:
        distribution_penalty = model.NewIntVar(0, max(1, len(distribution_terms) * len(problem.teaching_requirements)), "distribution_penalty")
        model.Add(distribution_penalty == sum(distribution_terms))
        objective_terms.append((distribution_penalty, "subject_distribution", priority_map.get("subject_distribution", "normal"), len(distribution_terms)))

    # Teacher gap penalties.
    gap_terms: list[cp_model.IntVar] = []
    for teacher_id in teacher_ids:
        for day in sorted({_day_from_slot(slot) for slot in teaching_slots}):
            day_slots = sorted([slot for slot in teaching_slots if _day_from_slot(slot) == day], key=lambda slot: _period_from_slot(slot))
            for index in range(1, len(day_slots) - 1):
                prev_slot = day_slots[index - 1]
                current_slot = day_slots[index]
                next_slot = day_slots[index + 1]
                prev_var = teach_slot.get((teacher_id, prev_slot))
                cur_var = teach_slot.get((teacher_id, current_slot))
                next_var = teach_slot.get((teacher_id, next_slot))
                if prev_var is None or cur_var is None or next_var is None:
                    continue
                gap = model.NewBoolVar(f"gap__{teacher_id}__{day}__{index}")
                model.Add(gap <= prev_var)
                model.Add(gap <= next_var)
                model.Add(gap <= 1 - cur_var)
                model.Add(gap >= prev_var + next_var - cur_var - 1)
                gap_terms.append(gap)

    if gap_terms:
        gap_penalty = model.NewIntVar(0, len(gap_terms), "teacher_gap_penalty")
        model.Add(gap_penalty == sum(gap_terms))
        objective_terms.append((gap_penalty, "minimize_teacher_gaps", priority_map.get("minimize_teacher_gaps", "normal"), len(gap_terms)))

    # Workload balance.
    teacher_totals: list[cp_model.IntVar] = []
    for teacher_id in teacher_ids:
        vars_teacher = [teach_slot[(teacher_id, slot)] for slot in teaching_slots if (teacher_id, slot) in teach_slot]
        if vars_teacher:
            total = model.NewIntVar(0, len(teaching_slots), f"teacher_total__{teacher_id}")
            model.Add(total == sum(vars_teacher))
            teacher_totals.append(total)

    if teacher_totals:
        max_load = model.NewIntVar(0, len(teaching_slots), "max_teacher_load")
        min_load = model.NewIntVar(0, len(teaching_slots), "min_teacher_load")
        model.AddMaxEquality(max_load, teacher_totals)
        model.AddMinEquality(min_load, teacher_totals)
        balance_penalty = model.NewIntVar(0, len(teaching_slots), "workload_balance_penalty")
        model.Add(balance_penalty == max_load - min_load)
        objective_terms.append((balance_penalty, "workload_balance", priority_map.get("workload_balance", "normal"), len(teaching_slots)))

    # Baseline disruption objective and lock semantics when baseline exists.
    disruption_terms: list[cp_model.IntVar] = []
    if problem.baseline.supported:
        for unit in units:
            baseline = baseline_by_occurrence.get(unit.occurrence_id)
            if not baseline:
                continue
            baseline_start = str(baseline.get("period_key"))
            lock_state = lock_by_occurrence.get(unit.occurrence_id)
            if lock_state == "locked":
                if (unit.occurrence_id, baseline_start) not in x:
                    blockers.append(
                        SolverDiagnostic(
                            code="hard_lock_conflict",
                            message="Locked baseline placement cannot be represented in current domain.",
                            severity="blocker",
                            entity_type="placement_unit",
                            entity_id=unit.occurrence_id,
                        )
                    )
                    continue
                model.Add(x[(unit.occurrence_id, baseline_start)] == 1)

            if (unit.occurrence_id, baseline_start) in x:
                moved = model.NewBoolVar(f"moved__{unit.occurrence_id}")
                model.Add(moved == 1 - x[(unit.occurrence_id, baseline_start)])
                disruption_terms.append(moved)

                if lock_state == "prefer_to_keep":
                    objective_terms.append((moved, "preserve_existing_assignments", "high", 1))

        if disruption_terms:
            disruption_sum = model.NewIntVar(0, len(disruption_terms), "disruption_penalty")
            model.Add(disruption_sum == sum(disruption_terms))
            objective_terms.append(
                (
                    disruption_sum,
                    "minimize_timetable_disruption",
                    priority_map.get("minimize_timetable_disruption", "high"),
                    len(disruption_terms) * stability_factor,
                )
            )

    if blockers:
        return _precondition_result(problem, tuple(blockers), status="invalid_problem")

    # Fairness objective from preference penalties grouped by teacher.
    if pref_penalty_vars:
        max_pref = model.NewIntVar(0, len(pref_penalty_vars) * len(teaching_slots), "pref_max")
        min_pref = model.NewIntVar(0, len(pref_penalty_vars) * len(teaching_slots), "pref_min")
        model.AddMaxEquality(max_pref, pref_penalty_vars)
        model.AddMinEquality(min_pref, pref_penalty_vars)
        fairness = model.NewIntVar(0, len(pref_penalty_vars) * len(teaching_slots), "pref_fairness")
        model.Add(fairness == max_pref - min_pref)
        objective_terms.append((fairness, "preference_fairness", priority_map.get("preference_fairness", "normal"), len(pref_penalty_vars) * len(teaching_slots)))

    max_by_priority: dict[str, int] = {"critical": 0, "high": 0, "normal": 0, "low": 0}
    for _var, _key, priority, max_score in objective_terms:
        p = normalize_priority(priority)
        max_by_priority[p] = max_by_priority.get(p, 0) + int(max_score)

    coefficients = build_priority_coefficients(max_by_priority)

    weighted_terms: list[cp_model.LinearExpr] = []
    component_caps: dict[str, int] = {}
    component_vars: dict[str, list[cp_model.IntVar]] = {}
    component_priority: dict[str, str] = {}

    for var, key, priority, max_score in objective_terms:
        p = normalize_priority(priority)
        component_caps[key] = component_caps.get(key, 0) + int(max_score)
        component_vars.setdefault(key, []).append(var)
        existing_priority = component_priority.get(key)
        if existing_priority is None:
            component_priority[key] = p
        else:
            rank = {"critical": 4, "high": 3, "normal": 2, "low": 1}
            component_priority[key] = p if rank[p] > rank[existing_priority] else existing_priority
        weighted_terms.append(var * coefficients[p])

    if weighted_terms:
        model.Minimize(sum(weighted_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(max(0.1, solve_options.max_time_seconds))
    solver.parameters.log_search_progress = bool(solve_options.log_search_progress)
    solver.parameters.random_seed = int(solve_options.random_seed)
    solver.parameters.num_search_workers = 1 if solve_options.deterministic_mode else max(1, int(solve_options.num_search_workers))

    if solve_options.stop_after_first_feasible:
        solver.parameters.stop_after_first_solution = True

    t0 = perf_counter()
    status = solver.Solve(model)
    runtime_ms = int((perf_counter() - t0) * 1000)

    has_solution = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    timed_out = runtime_ms >= int(solve_options.max_time_seconds * 1000)

    status_text, feasible, optimal = _status_to_contract(status, has_solution=has_solution, timed_out=timed_out)

    assignments: list[SolverAssignment] = []
    if feasible:
        start_for_occurrence: dict[str, str] = {}

        for unit in units:
            for start in allowed_starts[unit.occurrence_id]:
                if solver.Value(x[(unit.occurrence_id, start)]) == 1:
                    start_for_occurrence[unit.occurrence_id] = start
                    break

        for unit in units:
            start = start_for_occurrence.get(unit.occurrence_id)
            if start is None:
                continue
            teacher_id: str | None = None
            room_id: str | None = None
            span = occupied_slots[(unit.occurrence_id, start)]

            if unit.parallel_block_id is None:
                teacher_vars = [
                    (t, var)
                    for (occ, st, t), var in z_teacher.items()
                    if occ == unit.occurrence_id and st == start
                ]
                for t, var in teacher_vars:
                    if solver.Value(var) == 1:
                        teacher_id = t
                        break

                room_vars = [
                    (r, var)
                    for (occ, st, r), var in z_room.items()
                    if occ == unit.occurrence_id and st == start
                ]
                for r, var in room_vars:
                    if solver.Value(var) == 1:
                        room_id = r
                        break

                assignments.append(
                    SolverAssignment(
                        occurrence_id=unit.occurrence_id,
                        requirement_id=unit.requirement_id,
                        class_id=unit.class_id,
                        subject_id=unit.subject_id,
                        day_key=f"d{_day_from_slot(start)}",
                        period_key=start,
                        teacher_id=teacher_id,
                        room_id=room_id,
                        parallel_block_id=None,
                        parallel_child_id=None,
                        fixed=unit.fixed,
                        lock_state=lock_by_occurrence.get(unit.occurrence_id),
                        periods_per_session=unit.periods_per_session,
                        occupied_period_keys=span,
                    )
                )
            else:
                for child_id, child_teacher, child_subject, child_room in unit.parallel_children:
                    assignments.append(
                        SolverAssignment(
                            occurrence_id=unit.occurrence_id,
                            requirement_id=unit.requirement_id,
                            class_id=unit.class_id,
                            subject_id=child_subject,
                            day_key=f"d{_day_from_slot(start)}",
                            period_key=start,
                            teacher_id=child_teacher,
                            room_id=child_room,
                            parallel_block_id=unit.parallel_block_id,
                            parallel_child_id=child_id,
                            fixed=unit.fixed,
                            lock_state=lock_by_occurrence.get(unit.occurrence_id),
                            periods_per_session=unit.periods_per_session,
                            occupied_period_keys=span,
                        )
                    )

    component_results: list[SolverObjectiveComponent] = []
    objective_score: int | None = None
    if feasible and weighted_terms:
        objective_score = int(round(solver.ObjectiveValue()))

    for key, vars_for_component in sorted(component_vars.items()):
        score = int(sum(solver.Value(var) for var in vars_for_component)) if feasible else 0
        component_results.append(
            SolverObjectiveComponent(
                key=key,
                priority=component_priority.get(key, "normal"),
                score=score,
                max_score=int(component_caps.get(key, 0)),
                details={"term_count": len(vars_for_component)},
            )
        )

    teacher_gap_count = 0
    if feasible:
        for term in gap_terms:
            teacher_gap_count += int(solver.Value(term))

    hard_constraint_summary = {
        "exactly_one_placement": True,
        "class_collision": True,
        "teacher_collision": True,
        "room_collision": True,
        "requirement_fulfillment": True,
        "fixed_session_enforced": True,
        "unsupported_hard_rule_count": 0,
    }

    solver_statistics = {
        "cp_sat_status": int(status),
        "wall_time_seconds": float(solver.WallTime()) if hasattr(solver, "WallTime") else runtime_ms / 1000.0,
        "branches": int(solver.NumBranches()) if feasible else 0,
        "conflicts": int(solver.NumConflicts()) if feasible else 0,
    }

    metrics = SolverMetrics(
        runtime_ms=runtime_ms,
        objective_score=objective_score,
        boolean_variables=len(x) + len([item for item in z_teacher.values() if item not in x.values()]) + len([item for item in z_room.values() if item not in x.values()]),
        integer_variables=0,
        constraint_count=0,
        placement_unit_count=len(units),
        logical_slot_count=len(teaching_slots),
        eligible_teacher_links=sum(len(options) for options_by_start in teacher_candidates.values() for options in options_by_start.values()),
        room_links=sum(len(options) for options_by_start in room_candidates.values() for options in options_by_start.values()),
        parallel_block_count=len(problem.parallel_lesson_blocks),
        teacher_gap_count=teacher_gap_count,
    )

    result_diagnostics = list(blockers)
    if status == cp_model.INFEASIBLE:
        result_diagnostics.append(
            SolverDiagnostic(
                code="infeasible_model",
                message="Model is infeasible under current hard constraints.",
                severity="blocker",
            )
        )

    return SolverResult(
        problem_id=problem.problem_id,
        problem_fingerprint=problem.source_fingerprint,
        solver_name="or-tools-cp-sat",
        solver_version=str(ortools.__version__),
        status=status_text,
        feasible=feasible,
        optimal=optimal,
        assignments=tuple(sorted(assignments, key=lambda row: (row.occurrence_id, row.parallel_child_id or "", row.period_key))),
        objective_score=objective_score,
        objective_components=tuple(component_results),
        hard_constraint_summary=hard_constraint_summary,
        diagnostics=tuple(result_diagnostics),
        warnings=tuple(warnings),
        metrics=metrics,
        solver_statistics=solver_statistics,
        input_counts={
            "teachers": len(problem.teachers),
            "classes": len(problem.classes),
            "subjects": len(problem.subjects),
            "rooms": len(problem.rooms),
            "requirements": len(problem.teaching_requirements),
            "parallel_blocks": len(problem.parallel_lesson_blocks),
            "placement_units": len(units),
        },
    )
