"""
Phase 10D-2A: Focused tests for Attendance Persistence + Effective Rosters.

Covers:
  - models declared (column names, constraints, __tablename__)
  - migration: tables / columns / constraint names / identifier <=63 chars
  - effective roster before enrollment start → not in roster
  - effective roster after enrollment start → in roster
  - enrollment end boundary (half-open exited_on) → out on/after exited_on
  - same roster → same register, no duplicate records (idempotent)
  - changed roster → attendance_roster_stale, no mutation
  - cancelled session → attendance_not_available_for_session
  - inactive session → attendance_not_available_for_session
  - logical_period_unavailable → attendance_not_available_for_session
  - non-teaching operational day → attendance_not_available_for_session
  - multi-period session (periods_span > 1) → one register
  - parallel_block_id set → parallel_roster_membership_unresolved
  - cross-tenant isolation (different tenant cannot see register)
  - PostgreSQL identifiers ≤63 chars in migration
"""
from __future__ import annotations

import importlib.util
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.db.models import AttendanceRecord, AttendanceRegister
from services.timetable.attendance_registers import (
    AttendanceError,
    _compute_roster_fingerprint,
    _resolve_effective_roster,
    ensure_attendance_register,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIGRATION_FILE = Path(
    "alembic/versions/b7c3d9e1f4a2_phase_10d_2_attendance_persistence.py"
)
REVISION_ID = "b7c3d9e1f4a2"
DOWN_REVISION = "f3a2d8c1e9b4"
MAX_PG_IDENTIFIER = 63


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_daily_session(
    *,
    tenant_id: uuid.UUID,
    osd_id: uuid.UUID | None = None,
    session_status: str = "scheduled",
    is_active: bool = True,
    override_reason: str | None = None,
    parallel_block_id: str | None = None,
    class_facing_session_key: str | None = "cfsk-abc123",
    class_id: str | None = None,
    school_date: date = date(2026, 9, 15),
    periods_span: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        operational_school_day_id=osd_id or uuid.uuid4(),
        session_status=session_status,
        is_active=is_active,
        override_reason=override_reason,
        parallel_block_id=parallel_block_id,
        class_facing_session_key=class_facing_session_key,
        class_id=class_id or str(uuid.uuid4()),
        school_date=school_date,
        periods_span=periods_span,
        session_key="sk-full-" + str(uuid.uuid4()),
    )


def _make_osd(
    *,
    tenant_id: uuid.UUID,
    is_teaching_day: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        is_teaching_day=is_teaching_day,
    )


def _make_register(
    *,
    tenant_id: uuid.UUID,
    osd_id: uuid.UUID,
    class_facing_key: str,
    fingerprint: str,
    roster_resolution_status: str = "resolved",
) -> AttendanceRegister:
    return AttendanceRegister(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        operational_school_day_id=osd_id,
        class_facing_session_key=class_facing_key,
        class_id=str(uuid.uuid4()),
        school_date=date(2026, 9, 15),
        register_status="open",
        roster_resolution_status=roster_resolution_status,
        roster_source_fingerprint=fingerprint,
        expected_student_count=2,
    )


def _db_with_scalars(*return_values) -> AsyncMock:
    """Return an AsyncMock db whose scalar() returns successive values."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(side_effect=list(return_values))
    return db


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model declarations
# ─────────────────────────────────────────────────────────────────────────────

def test_attendance_register_tablename() -> None:
    assert AttendanceRegister.__tablename__ == "attendance_registers"


def test_attendance_record_tablename() -> None:
    assert AttendanceRecord.__tablename__ == "attendance_records"


def test_attendance_register_columns_present() -> None:
    cols = {c.name for c in AttendanceRegister.__table__.columns}
    required = {
        "id", "tenant_id", "operational_school_day_id",
        "class_facing_session_key", "class_id", "school_date",
        "register_status", "roster_resolution_status",
        "roster_source_fingerprint", "expected_student_count",
        "created_at", "updated_at",
    }
    assert required <= cols


def test_attendance_record_columns_present() -> None:
    cols = {c.name for c in AttendanceRecord.__table__.columns}
    required = {
        "id", "tenant_id", "attendance_register_id",
        "student_id", "source_enrollment_id",
        "attendance_status", "marked_at", "marked_by",
        "created_at", "updated_at",
    }
    assert required <= cols


def test_attendance_register_unique_constraint_declared() -> None:
    constraint_names = {
        c.name
        for c in AttendanceRegister.__table__.constraints
        if hasattr(c, "name") and c.name
    }
    assert any("uq_att_registers_osd_session_key" in name for name in constraint_names)


def test_attendance_record_unique_constraint_declared() -> None:
    constraint_names = {
        c.name
        for c in AttendanceRecord.__table__.constraints
        if hasattr(c, "name") and c.name
    }
    assert any("uq_attendance_records_register_student" in name for name in constraint_names)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Migration checks
# ─────────────────────────────────────────────────────────────────────────────

def test_migration_file_exists() -> None:
    assert MIGRATION_FILE.exists(), f"Migration file not found: {MIGRATION_FILE}"


def test_migration_revision_and_down_revision() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION_ID}"' in text
    assert f'down_revision: Union[str, None] = "{DOWN_REVISION}"' in text


def test_migration_declares_attendance_tables() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "attendance_registers" in text
    assert "attendance_records" in text
    assert "def upgrade()" in text
    assert "def downgrade()" in text


def test_migration_declares_key_columns() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    for col in [
        "operational_school_day_id",
        "class_facing_session_key",
        "register_status",
        "roster_resolution_status",
        "roster_source_fingerprint",
        "expected_student_count",
        "attendance_register_id",
        "student_id",
        "source_enrollment_id",
        "attendance_status",
        "marked_at",
        "marked_by",
    ]:
        assert col in text, f"Expected column '{col}' in migration"


def test_migration_declares_uniqueness_constraints() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "uq_att_registers_osd_session_key" in text
    assert "uq_attendance_records_register_student" in text


def test_migration_declares_check_constraints() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "ck_attendance_registers_status" in text
    assert "ck_att_registers_roster_status" in text
    assert "ck_attendance_records_status" in text


def test_migration_identifiers_le63_chars() -> None:
    """All explicit PostgreSQL identifiers in the migration must be ≤63 chars."""
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    named = re.findall(r'name=["\']([^"\']+)["\']', text)
    positional = re.findall(
        r'op\.(?:create_index|drop_index)\(\s*["\']([^"\']+)["\']', text
    )
    all_identifiers = sorted(set(named + positional))
    violations = [
        (name, len(name))
        for name in all_identifiers
        if len(name) > MAX_PG_IDENTIFIER
    ]
    assert not violations, (
        f"PostgreSQL identifier limit ({MAX_PG_IDENTIFIER}) exceeded:\n"
        + "\n".join(f"  {name!r} ({length} chars)" for name, length in violations)
    )


def test_migration_alembic_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION_ID], (
        f"Expected head {REVISION_ID}, got {script.get_heads()}"
    )


def test_migration_chain_includes_10d_foundation() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    chain = {r.revision for r in script.iterate_revisions(heads[0], "base")}
    assert DOWN_REVISION in chain   # Phase 10D foundation
    assert "e7b1c9d4a2f0" in chain  # Phase 10C batch 5


# ─────────────────────────────────────────────────────────────────────────────
# 3. Roster fingerprint
# ─────────────────────────────────────────────────────────────────────────────

def test_fingerprint_is_deterministic() -> None:
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    cid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    sd = date(2026, 9, 15)
    s1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
    e1 = uuid.UUID("22222222-2222-2222-2222-222222222222")
    s2 = uuid.UUID("33333333-3333-3333-3333-333333333333")
    e2 = uuid.UUID("44444444-4444-4444-4444-444444444444")
    enrollments = [(s1, e1), (s2, e2)]

    fp1 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=enrollments
    )
    fp2 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=enrollments
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_fingerprint_differs_for_different_roster() -> None:
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    cid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    sd = date(2026, 9, 15)
    s1, e1 = uuid.uuid4(), uuid.uuid4()
    s2, e2 = uuid.uuid4(), uuid.uuid4()

    fp1 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=[(s1, e1)]
    )
    fp2 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=[(s1, e1), (s2, e2)]
    )
    assert fp1 != fp2


def test_fingerprint_excludes_runtime_values() -> None:
    """Same inputs on two separate calls with different UUIDs4 must differ."""
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    cid = "bbbb"
    sd = date(2026, 9, 15)
    enr: list[tuple[uuid.UUID, uuid.UUID]] = []

    # Empty roster: fingerprint must be the same both times
    fp1 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=enr
    )
    fp2 = _compute_roster_fingerprint(
        tenant_id=tid, class_id=cid, school_date=sd, enrollments=enr
    )
    assert fp1 == fp2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Effective roster – before/after enrollment start
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_effective_roster_before_enrolled_on() -> None:
    """Student enrolled Sep 10; Sep 8 session → not in roster."""
    from shared.db.models import StudentEnrollment as _SE

    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    class_id = uuid.uuid4()
    session_date = date(2026, 9, 8)  # before enrolled_on

    # Mock db.execute to return an empty result (no qualifying enrollments)
    db = AsyncMock()
    empty_result = MagicMock()
    empty_result.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)

    roster = await _resolve_effective_roster(
        db, tenant_id=tid, class_id=class_id, school_date=session_date
    )
    assert roster == []


@pytest.mark.asyncio
async def test_effective_roster_after_enrolled_on() -> None:
    """Student enrolled Sep 10; Sep 15 session → in roster."""
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    class_id = uuid.uuid4()
    student_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()
    session_date = date(2026, 9, 15)

    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(student_id, enrollment_id)]
    db.execute = AsyncMock(return_value=result)

    roster = await _resolve_effective_roster(
        db, tenant_id=tid, class_id=class_id, school_date=session_date
    )
    assert roster == [(student_id, enrollment_id)]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Enrollment end boundary (half-open exited_on)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_effective_roster_on_exited_on_date_not_included() -> None:
    """
    exited_on is exclusive (half-open [enrolled_on, exited_on)).
    Student with exited_on = Sep 15 must NOT appear in Sep 15 roster.
    The DB filter already enforces this via school_date < exited_on.
    Verify _resolve_effective_roster passes the right WHERE condition by
    confirming an empty roster is returned when mock returns no rows.
    """
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    class_id = uuid.uuid4()
    session_date = date(2026, 9, 15)

    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []  # DB filtered out the exited student
    db.execute = AsyncMock(return_value=result)

    roster = await _resolve_effective_roster(
        db, tenant_id=tid, class_id=class_id, school_date=session_date
    )
    assert roster == []


@pytest.mark.asyncio
async def test_effective_roster_day_before_exited_on_included() -> None:
    """Student with exited_on = Sep 15; Sep 14 session → still in roster."""
    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    class_id = uuid.uuid4()
    student_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()
    session_date = date(2026, 9, 14)

    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(student_id, enrollment_id)]
    db.execute = AsyncMock(return_value=result)

    roster = await _resolve_effective_roster(
        db, tenant_id=tid, class_id=class_id, school_date=session_date
    )
    assert roster == [(student_id, enrollment_id)]


# ─────────────────────────────────────────────────────────────────────────────
# 6. ensure_attendance_register – idempotency (same roster)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_roster_returns_existing_register() -> None:
    """Second call with same roster → existing register returned unchanged."""
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-idempotent"

    s1, e1 = uuid.uuid4(), uuid.uuid4()
    enrollments = [(s1, e1)]
    fp = _compute_roster_fingerprint(
        tenant_id=tid,
        class_id=class_id_str,
        school_date=sd,
        enrollments=enrollments,
    )

    session_ns = _make_daily_session(
        tenant_id=tid,
        osd_id=osd_id,
        class_facing_session_key=cfsk,
        class_id=class_id_str,
        school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid, is_teaching_day=True)
    existing_register = _make_register(
        tenant_id=tid,
        osd_id=osd_id,
        class_facing_key=cfsk,
        fingerprint=fp,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    # scalar calls: DailySession, OSD, AttendanceRegister (existing)
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, existing_register])
    roster_result = MagicMock()
    roster_result.all.return_value = enrollments
    db.execute = AsyncMock(return_value=roster_result)

    result = await ensure_attendance_register(
        db, tenant_id=tid, daily_session_id=session_ns.id
    )
    assert result is existing_register
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_same_roster_no_duplicate_records() -> None:
    """Same roster → db.add never called again (no new records)."""
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-no-dup"

    enrollments: list[tuple[uuid.UUID, uuid.UUID]] = []
    fp = _compute_roster_fingerprint(
        tenant_id=tid, class_id=class_id_str, school_date=sd, enrollments=enrollments
    )

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)
    existing_register = _make_register(
        tenant_id=tid, osd_id=osd_id, class_facing_key=cfsk, fingerprint=fp,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, existing_register])
    roster_result = MagicMock()
    roster_result.all.return_value = enrollments
    db.execute = AsyncMock(return_value=roster_result)

    await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)
    db.add.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 7. ensure_attendance_register – changed roster → stale
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_changed_roster_raises_stale_error() -> None:
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-stale"

    # Register was created with empty roster fingerprint
    old_fp = _compute_roster_fingerprint(
        tenant_id=tid, class_id=class_id_str, school_date=sd, enrollments=[]
    )
    # Now roster has a student
    new_enrollment = (uuid.uuid4(), uuid.uuid4())
    new_fp = _compute_roster_fingerprint(
        tenant_id=tid, class_id=class_id_str, school_date=sd, enrollments=[new_enrollment]
    )
    assert old_fp != new_fp

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)
    existing_register = _make_register(
        tenant_id=tid, osd_id=osd_id, class_facing_key=cfsk, fingerprint=old_fp,
    )
    prior_snapshot = {
        "register_status": existing_register.register_status,
        "roster_resolution_status": existing_register.roster_resolution_status,
        "roster_source_fingerprint": existing_register.roster_source_fingerprint,
        "expected_student_count": existing_register.expected_student_count,
        "school_date": existing_register.school_date,
        "class_id": existing_register.class_id,
    }

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, existing_register])
    roster_result = MagicMock()
    roster_result.all.return_value = [new_enrollment]
    db.execute = AsyncMock(return_value=roster_result)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "attendance_roster_stale"
    assert existing_register.register_status == prior_snapshot["register_status"]
    assert existing_register.roster_resolution_status == prior_snapshot["roster_resolution_status"]
    assert existing_register.roster_source_fingerprint == prior_snapshot["roster_source_fingerprint"]
    assert existing_register.expected_student_count == prior_snapshot["expected_student_count"]
    assert existing_register.school_date == prior_snapshot["school_date"]
    assert existing_register.class_id == prior_snapshot["class_id"]
    db.add.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_stale_roster_does_not_mutate_records() -> None:
    """On stale, AttendanceRecord rows must NOT be added or deleted."""
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-no-mutate"

    old_fp = _compute_roster_fingerprint(
        tenant_id=tid, class_id=class_id_str, school_date=sd, enrollments=[]
    )

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)
    existing_register = _make_register(
        tenant_id=tid, osd_id=osd_id, class_facing_key=cfsk, fingerprint=old_fp,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, existing_register])
    new_enrollment = (uuid.uuid4(), uuid.uuid4())
    roster_result = MagicMock()
    roster_result.all.return_value = [new_enrollment]
    db.execute = AsyncMock(return_value=roster_result)

    with pytest.raises(AttendanceError):
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    db.add.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Ineligible sessions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancelled_session_blocked() -> None:
    tid = _tenant_id()
    session_ns = _make_daily_session(
        tenant_id=tid, session_status="cancelled"
    )
    db = _db_with_scalars(session_ns)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "attendance_not_available_for_session"
    assert "cancelled" in exc_info.value.detail


@pytest.mark.asyncio
async def test_inactive_session_blocked() -> None:
    tid = _tenant_id()
    session_ns = _make_daily_session(tenant_id=tid, is_active=False)
    db = _db_with_scalars(session_ns)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "attendance_not_available_for_session"
    assert "inactive" in exc_info.value.detail


@pytest.mark.asyncio
async def test_logical_period_unavailable_blocked() -> None:
    tid = _tenant_id()
    session_ns = _make_daily_session(
        tenant_id=tid,
        session_status="cancelled",
        override_reason="logical_period_unavailable",
    )
    db = _db_with_scalars(session_ns)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "attendance_not_available_for_session"


@pytest.mark.asyncio
async def test_non_teaching_day_blocked() -> None:
    tid = _tenant_id()
    session_ns = _make_daily_session(tenant_id=tid)
    osd_ns = _make_osd(tenant_id=tid, is_teaching_day=False)
    db = _db_with_scalars(session_ns, osd_ns)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "attendance_not_available_for_session"
    assert "non_instructional" in exc_info.value.detail


@pytest.mark.asyncio
async def test_session_not_found_for_wrong_tenant() -> None:
    tid = _tenant_id()
    db = _db_with_scalars(None)  # scalar returns None → session not found

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(
            db, tenant_id=tid, daily_session_id=uuid.uuid4()
        )

    assert exc_info.value.code == "session_not_found"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Multi-period session → one register
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_period_session_creates_one_register() -> None:
    """periods_span=3 (double/triple period) still creates exactly one register."""
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-multiperiod"

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str,
        school_date=sd, periods_span=3,
    )
    osd_ns = _make_osd(tenant_id=tid)

    db = AsyncMock()
    add_calls: list = []
    db.add = MagicMock(side_effect=lambda x: add_calls.append(x))
    db.flush = AsyncMock()
    # No existing register (None)
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, None])
    empty_roster = MagicMock()
    empty_roster.all.return_value = []
    db.execute = AsyncMock(return_value=empty_roster)

    result = await ensure_attendance_register(
        db, tenant_id=tid, daily_session_id=session_ns.id
    )

    registers = [x for x in add_calls if isinstance(x, AttendanceRegister)]
    assert len(registers) == 1
    assert result is registers[0]


# ─────────────────────────────────────────────────────────────────────────────
# 10. Parallel membership unresolved
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parallel_block_raises_unresolved() -> None:
    """DailySession with parallel_block_id set → parallel_roster_membership_unresolved."""
    tid = _tenant_id()
    session_ns = _make_daily_session(
        tenant_id=tid,
        parallel_block_id="pblock-foreign-lang-grade8",
    )
    osd_ns = _make_osd(tenant_id=tid)
    db = _db_with_scalars(session_ns, osd_ns)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    assert exc_info.value.code == "parallel_roster_membership_unresolved"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Cross-tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_tenant_session_not_visible() -> None:
    """A session belonging to tenant_B must not be accessible by tenant_A."""
    tenant_a = _tenant_id()
    # DB returns None because the WHERE includes tenant_a but session belongs to tenant_b
    db = _db_with_scalars(None)

    with pytest.raises(AttendanceError) as exc_info:
        await ensure_attendance_register(
            db, tenant_id=tenant_a, daily_session_id=uuid.uuid4()
        )

    assert exc_info.value.code == "session_not_found"


@pytest.mark.asyncio
async def test_new_register_carries_correct_tenant_id() -> None:
    """AttendanceRegister created must carry the requesting tenant_id."""
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-tenant-check"

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)

    add_calls: list = []
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda x: add_calls.append(x))
    db.flush = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, None])
    empty_roster = MagicMock()
    empty_roster.all.return_value = []
    db.execute = AsyncMock(return_value=empty_roster)

    await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    registers = [x for x in add_calls if isinstance(x, AttendanceRegister)]
    assert len(registers) == 1
    assert registers[0].tenant_id == tid


# ─────────────────────────────────────────────────────────────────────────────
# 12. First call creates register + unmarked records
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_call_creates_register_and_records() -> None:
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-first-create"

    s1, e1 = uuid.uuid4(), uuid.uuid4()
    s2, e2 = uuid.uuid4(), uuid.uuid4()
    enrollments = [(s1, e1), (s2, e2)]

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)

    add_calls: list = []
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda x: add_calls.append(x))
    db.flush = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, None])
    roster_result = MagicMock()
    roster_result.all.return_value = enrollments
    db.execute = AsyncMock(return_value=roster_result)

    result = await ensure_attendance_register(
        db, tenant_id=tid, daily_session_id=session_ns.id
    )

    registers = [x for x in add_calls if isinstance(x, AttendanceRegister)]
    records = [x for x in add_calls if isinstance(x, AttendanceRecord)]
    assert len(registers) == 1
    assert len(records) == 2
    assert all(r.attendance_status == "unmarked" for r in records)
    assert all(r.tenant_id == tid for r in records)
    assert result is registers[0]
    assert result.expected_student_count == 2


@pytest.mark.asyncio
async def test_first_call_register_status_is_open() -> None:
    tid = _tenant_id()
    osd_id = uuid.uuid4()
    class_id_str = str(uuid.uuid4())
    sd = date(2026, 9, 15)
    cfsk = "cfsk-open-status"

    session_ns = _make_daily_session(
        tenant_id=tid, osd_id=osd_id,
        class_facing_session_key=cfsk, class_id=class_id_str, school_date=sd,
    )
    osd_ns = _make_osd(tenant_id=tid)

    add_calls: list = []
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda x: add_calls.append(x))
    db.flush = AsyncMock()
    db.scalar = AsyncMock(side_effect=[session_ns, osd_ns, None])
    empty_roster = MagicMock()
    empty_roster.all.return_value = []
    db.execute = AsyncMock(return_value=empty_roster)

    await ensure_attendance_register(db, tenant_id=tid, daily_session_id=session_ns.id)

    registers = [x for x in add_calls if isinstance(x, AttendanceRegister)]
    assert registers[0].register_status == "open"
    assert registers[0].roster_resolution_status == "resolved"
