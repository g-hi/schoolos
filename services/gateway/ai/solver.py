"""
solver.py
─────────
OR-Tools CP-SAT constraint solver for automatic timetable generation.

HOW IT WORKS
────────────
1. Load data from DB: teachers, classes, subjects, periods, teacher_subjects.
2. Load active constraints from timetable_constraints table.
3. Build variables:
     x[class, subject, teacher, day, period] = BoolVar
     "Does class C have subject S taught by teacher T on day D in period P?"
4. Add hard constraints:
     a) Each class must have each of its subjects exactly once per week.
     b) A teacher can only be in one place per period per day.
     c) A class can only have one lesson per period per day.
5. Apply soft/hard constraints from timetable_constraints table (parsed JSON).
6. Solve. If no solution → raise SolverError.
7. Return list of TimetableEntry-compatible dicts.

SUBJECT DISTRIBUTION
────────────────────
For this version: every class gets every subject once per week.
Teacher assigned to a subject is chosen from teachers qualified for that subject.
If a class has no class_teacher, any qualified teacher is used.

PERFORMANCE NOTE
────────────────
With 5 classes × 6 subjects × 4 teachers × 5 days × 7 periods = 4,200 variables.
CP-SAT handles this in < 1 second. Fine for a school.
"""

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db.connection import AsyncSessionLocal, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    Subject,
    Teacher,
    TeacherSubject,
    TimetableConstraint,
)

# ── OR-Tools import ────────────────────────────────────────────────────────────
try:
    from ortools.sat.python import cp_model
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "ortools is not installed. Run: pip install ortools>=9.10.0"
    ) from exc


class SolverError(Exception):
    """Raised when OR-Tools cannot find a feasible timetable."""


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def generate_timetable(
    tenant_id: UUID,
    academic_year: str,
) -> list[dict[str, Any]]:
    """
    Generates a complete weekly timetable for a school.

    Returns a list of dicts, each matching TimetableEntry fields:
      {
        "tenant_id":     UUID,
        "academic_year": str,
        "day_of_week":   int,      # 0=Monday … 4=Friday
        "period_id":     UUID,
        "class_id":      UUID,
        "subject_id":    UUID,
        "teacher_id":    UUID,
      }

    Raises SolverError if no valid timetable exists under the given constraints.
    """
    # 1. Load all data from DB
    db_data = await _load_data(tenant_id)

    # 2. Load active constraints
    constraints = await _load_constraints(tenant_id, academic_year)

    # 3. Run solver (synchronous CPU work — off the event loop)
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(
        None,
        _solve,
        db_data,
        constraints,
        str(tenant_id),
        academic_year,
    )
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _load_data(tenant_id: UUID) -> dict:
    """Fetch teachers, classes, subjects, periods, teacher↔subject links."""
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id)

        teachers_q  = await session.execute(
            select(Teacher)
            .where(Teacher.tenant_id == tenant_id)
            .options(selectinload(Teacher.user), selectinload(Teacher.subjects))
        )
        teachers = teachers_q.scalars().all()

        classes_q = await session.execute(
            select(Class).where(Class.tenant_id == tenant_id)
        )
        classes = classes_q.scalars().all()

        subjects_q = await session.execute(
            select(Subject).where(Subject.tenant_id == tenant_id)
        )
        subjects = subjects_q.scalars().all()

        periods_q = await session.execute(
            select(Period)
            .where(Period.tenant_id == tenant_id)
            .order_by(Period.sort_order)
        )
        periods = periods_q.scalars().all()

        ts_q = await session.execute(
            select(TeacherSubject).join(
                Teacher, TeacherSubject.teacher_id == Teacher.id
            ).where(Teacher.tenant_id == tenant_id)
        )
        teacher_subjects = ts_q.scalars().all()

    return {
        "teachers":       teachers,
        "classes":        classes,
        "subjects":       subjects,
        "periods":        periods,
        "teacher_subjects": teacher_subjects,
    }


async def _load_constraints(tenant_id: UUID, academic_year: str) -> list[dict]:
    """Return all active constraints as plain dicts (detached from session)."""
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id)
        q = await session.execute(
            select(TimetableConstraint).where(
                TimetableConstraint.tenant_id == tenant_id,
                TimetableConstraint.academic_year == academic_year,
                TimetableConstraint.is_active.is_(True),
            )
        )
        rows = q.scalars().all()
        return [
            {"constraint_type": r.constraint_type, "data": r.data}
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# The solver  (runs synchronously inside run_in_executor)
# ─────────────────────────────────────────────────────────────────────────────

def _solve(
    db_data: dict,
    constraints: list[dict],
    tenant_id_str: str,
    academic_year: str,
) -> list[dict]:
    teachers        = db_data["teachers"]
    classes         = db_data["classes"]
    subjects        = db_data["subjects"]
    periods         = db_data["periods"]
    teacher_subjects = db_data["teacher_subjects"]

    if not (teachers and classes and subjects and periods):
        raise SolverError(
            "Cannot generate timetable: missing teachers, classes, subjects, or periods."
        )

    # Index lookups
    teacher_ids  = [str(t.id) for t in teachers]
    class_ids    = [str(c.id) for c in classes]
    subject_ids  = [str(s.id) for s in subjects]
    period_ids   = [str(p.id) for p in periods]
    period_order = {str(p.id): p.sort_order for p in periods}  # id → 1-based order

    # Which teachers can teach which subjects? → set of (teacher_id, subject_id)
    qualified: set[tuple[str, str]] = {
        (str(ts.teacher_id), str(ts.subject_id))
        for ts in teacher_subjects
    }

    DAYS = list(range(5))  # 0=Mon … 4=Fri

    # ── Build model ───────────────────────────────────────────────────────────
    model = cp_model.CpModel()

    # x[(c,s,t,d,p)] = 1 means: class c has subject s taught by teacher t on day d period p
    x: dict[tuple, Any] = {}
    for c in class_ids:
        for s in subject_ids:
            for t in teacher_ids:
                if (t, s) not in qualified:
                    continue  # skip unqualified teacher
                for d in DAYS:
                    for p in period_ids:
                        x[(c, s, t, d, p)] = model.new_bool_var(
                            f"x_c{c[:4]}_s{s[:4]}_t{t[:4]}_d{d}_p{p[:4]}"
                        )

    # ── Core constraints ─────────────────────────────────────────────────────

    # 1. Each class has each subject exactly once per week
    for c in class_ids:
        for s in subject_ids:
            qualified_vars = [
                x[(c, s, t, d, p)]
                for t in teacher_ids
                for d in DAYS
                for p in period_ids
                if (c, s, t, d, p) in x
            ]
            if qualified_vars:
                model.add(sum(qualified_vars) == 1)

    # 2. A class can only have one lesson per (day, period)
    for c in class_ids:
        for d in DAYS:
            for p in period_ids:
                model.add_at_most_one(
                    x[(c, s, t, d, p)]
                    for s in subject_ids
                    for t in teacher_ids
                    if (c, s, t, d, p) in x
                )

    # 3. A teacher can only be in one place per (day, period)
    for t in teacher_ids:
        for d in DAYS:
            for p in period_ids:
                model.add_at_most_one(
                    x[(c, s, t, d, p)]
                    for c in class_ids
                    for s in subject_ids
                    if (c, s, t, d, p) in x
                )

    # ── Apply admin constraints ───────────────────────────────────────────────
    teacher_name_to_id = {t.user.name.lower(): str(t.id) for t in teachers}
    subject_name_to_id = {s.name.lower(): str(s.id) for s in subjects}
    class_name_to_id   = {
        f"{c.grade} {c.section}".lower(): str(c.id) for c in classes
    }

    for con in constraints:
        ctype = con["constraint_type"]
        data  = con.get("data", {})

        if ctype == "teacher_unavailable":
            _apply_teacher_unavailable(
                model, x, data,
                teacher_name_to_id, teacher_ids, class_ids, subject_ids,
                DAYS, period_ids, period_order
            )

        elif ctype == "teacher_max_daily":
            _apply_teacher_max_daily(
                model, x, data,
                teacher_name_to_id, teacher_ids, class_ids, subject_ids,
                DAYS, period_ids
            )

        elif ctype == "class_unavailable":
            _apply_class_unavailable(
                model, x, data,
                class_name_to_id, teacher_ids, subject_ids,
                DAYS, period_ids, period_order
            )

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0

    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SolverError(
            "No valid timetable found under the current constraints. "
            "Try relaxing some constraints and run /timetable/generate again."
        )

    # ── Extract solution ──────────────────────────────────────────────────────
    entries = []
    for (c, s, t, d, p), var in x.items():
        if solver.value(var) == 1:
            entries.append({
                "tenant_id":     tenant_id_str,
                "academic_year": academic_year,
                "day_of_week":   d,
                "period_id":     p,
                "class_id":      c,
                "subject_id":    s,
                "teacher_id":    t,
            })

    return entries


# ── Constraint application helpers ───────────────────────────────────────────

def _apply_teacher_unavailable(
    model, x, data, teacher_name_to_id, teacher_ids, class_ids, subject_ids,
    DAYS, period_ids, period_order
):
    """Block a teacher from a specific day/period combination."""
    tname = data.get("teacher_name", "").lower()
    tid = teacher_name_to_id.get(tname)
    if not tid:
        return  # teacher not found by name — skip silently

    target_day     = data.get("day_of_week")   # None means all days
    target_period  = data.get("period_order")  # None means all periods (1-based)

    days_to_block    = [target_day] if target_day is not None else DAYS
    periods_to_block = [
        pid for pid in period_ids
        if target_period is None or period_order[pid] == target_period
    ]

    for d in days_to_block:
        for p in periods_to_block:
            for c in class_ids:
                for s in subject_ids:
                    if (c, s, tid, d, p) in x:
                        model.add(x[(c, s, tid, d, p)] == 0)


def _apply_teacher_max_daily(
    model, x, data, teacher_name_to_id, teacher_ids, class_ids, subject_ids,
    DAYS, period_ids
):
    """Limit how many periods a teacher teaches per day."""
    tname = data.get("teacher_name", "").lower()
    tid = teacher_name_to_id.get(tname)
    max_p = data.get("max_periods", 3)
    if not tid:
        return

    for d in DAYS:
        day_vars = [
            x[(c, s, tid, d, p)]
            for c in class_ids
            for s in subject_ids
            for p in period_ids
            if (c, s, tid, d, p) in x
        ]
        if day_vars:
            model.add(sum(day_vars) <= max_p)


def _apply_class_unavailable(
    model, x, data, class_name_to_id, teacher_ids, subject_ids,
    DAYS, period_ids, period_order
):
    """Block an entire class from a period (e.g., sports day)."""
    cname = data.get("class_name", "").lower()
    cid = class_name_to_id.get(cname)
    if not cid:
        return

    target_day    = data.get("day_of_week")
    target_period = data.get("period_order")

    days_to_block    = [target_day] if target_day is not None else DAYS
    periods_to_block = [
        pid for pid in period_ids
        if target_period is None or period_order[pid] == target_period
    ]

    for d in days_to_block:
        for p in periods_to_block:
            for s in subject_ids:
                for t in teacher_ids:
                    if (cid, s, t, d, p) in x:
                        model.add(x[(cid, s, t, d, p)] == 0)
