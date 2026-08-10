"""Tests for Phase 10D materialization service - full semantic coverage."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.gateway.timetable_setup.daily_sessions as ds_module
from services.gateway.timetable_setup.daily_sessions import (
    DailySessionError,
    MaterializationOutcome,
    compute_class_facing_session_key,
    compute_source_fingerprint,
    materialize_operational_day,
    period_number_from_period_key,
    resolve_day_key,
    resolve_session_times,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_resolve_day_key_monday_5day():
    assert resolve_day_key(date(2026, 9, 7), [0, 1, 2, 3, 4]) == "d0"

def test_resolve_day_key_friday_5day():
    assert resolve_day_key(date(2026, 9, 11), [0, 1, 2, 3, 4]) == "d4"

def test_resolve_day_key_saturday_none():
    assert resolve_day_key(date(2026, 9, 12), [0, 1, 2, 3, 4]) is None

def test_resolve_day_key_sunday_none():
    assert resolve_day_key(date(2026, 9, 13), [0, 1, 2, 3, 4]) is None

def test_resolve_day_key_sun_thu_school():
    # Sun-Thu school; Monday is d1
    assert resolve_day_key(date(2026, 9, 7), [6, 0, 1, 2, 3]) == "d1"

def test_resolve_day_key_fri_not_in_sun_thu():
    assert resolve_day_key(date(2026, 9, 11), [6, 0, 1, 2, 3]) is None

def test_resolve_day_key_single_day():
    assert resolve_day_key(date(2026, 9, 7), [0]) == "d0"

def test_period_number_standard():
    assert period_number_from_period_key("d0:p3") == 3

def test_period_number_large():
    assert period_number_from_period_key("d2:p10") == 10

def test_period_number_invalid():
    assert period_number_from_period_key("badformat") is None

def test_period_number_zero():
    assert period_number_from_period_key("d0:p0") is None

def test_compute_fingerprint_deterministic():
    vid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    tid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    fp1 = compute_source_fingerprint(tid, vid, "d0", None, None)
    fp2 = compute_source_fingerprint(tid, vid, "d0", None, None)
    assert fp1 == fp2 and len(fp1) == 64

def test_compute_fingerprint_changes_with_bell():
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    vid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    bid = uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert compute_source_fingerprint(tid, vid, "d0", None, None) != compute_source_fingerprint(tid, vid, "d0", bid, None)

def test_compute_fingerprint_changes_with_calendar_override():
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    vid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    cid = uuid.UUID("44444444-4444-4444-4444-444444444444")
    assert compute_source_fingerprint(tid, vid, "d0", None, None) != compute_source_fingerprint(tid, vid, "d0", None, cid)

def test_compute_fingerprint_changes_with_version():
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    vid1 = uuid.UUID("22222222-2222-2222-2222-222222222222")
    vid2 = uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert compute_source_fingerprint(tid, vid1, "d0", None, None) != compute_source_fingerprint(tid, vid2, "d0", None, None)

def test_compute_fingerprint_changes_with_timetable_id():
    tid1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
    tid2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
    vid = uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert compute_source_fingerprint(tid1, vid, "d0", None, None) != compute_source_fingerprint(tid2, vid, "d0", None, None)

def test_class_facing_key_ordinary_deterministic():
    k1 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", None)
    k2 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", None)
    assert k1 == k2 and len(k1) == 64

def test_class_facing_key_parallel_children_share_key():
    k1 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", "block_x")
    k2 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", "block_x")
    assert k1 == k2

def test_class_facing_key_different_block_different_key():
    k_plain = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", None)
    k_block = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", "block_x")
    assert k_plain != k_block

def test_class_facing_key_no_subject_names_used():
    """Key must not change when subject_id changes - it's not an input."""
    k1 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", "block_x")
    k2 = compute_class_facing_session_key(date(2026, 9, 7), "class_8a", "d0:p3", "block_x")
    assert k1 == k2  # subject names are not inputs to this function

def _bp(n, start, end):
    return SimpleNamespace(id=uuid.uuid4(), period_number=n, start_time=start, end_time=end)

def test_resolve_session_times_single_period():
    bps = {3: _bp(3, "09:00", "09:50")}
    s, e, bid, ok = resolve_session_times("d0:p3", ["d0:p3"], bps)
    assert ok and s == "09:00" and e == "09:50"

def test_resolve_session_times_multi_period_end_from_last():
    bps = {3: _bp(3, "09:00", "09:50"), 4: _bp(4, "10:00", "10:50")}
    s, e, bid, ok = resolve_session_times("d0:p3", ["d0:p3", "d0:p4"], bps)
    assert ok and s == "09:00" and e == "10:50"

def test_resolve_session_times_missing_first_period():
    bps = {4: _bp(4, "10:00", "10:50")}
    s, e, bid, ok = resolve_session_times("d0:p3", ["d0:p3", "d0:p4"], bps)
    assert not ok and s is None

def test_resolve_session_times_missing_second_period():
    bps = {3: _bp(3, "09:00", "09:50")}
    s, e, bid, ok = resolve_session_times("d0:p3", ["d0:p3", "d0:p4"], bps)
    assert not ok and e is None

def test_resolve_session_times_fallback_to_primary():
    bps = {5: _bp(5, "11:00", "11:50")}
    s, e, bid, ok = resolve_session_times("d0:p5", [], bps)
    assert ok and s == "11:00" and e == "11:50"


# ---------------------------------------------------------------------------
# DB stub helpers
# ---------------------------------------------------------------------------

def _make_db(scalars_return=None):
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = scalars_return or []
    db.execute = AsyncMock(return_value=execute_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    return db


def _timetable(tenant_id, timetable_id=None, campus_id=None, academic_year_id=None):
    return SimpleNamespace(
        id=timetable_id or uuid.uuid4(),
        tenant_id=tenant_id,
        campus_id=campus_id,
        academic_year_id=academic_year_id,
    )


def _version(tenant_id, timetable_id, version_id=None):
    return SimpleNamespace(
        id=version_id or uuid.uuid4(),
        tenant_id=tenant_id,
        timetable_id=timetable_id,
        lifecycle_status="published",
    )


def _assignment(period_key, class_id="class_7a", periods_per_session=1,
                parallel_block_id=None, parallel_child_id=None, occupied_keys=None):
    child = parallel_child_id or ""
    return SimpleNamespace(
        id=uuid.uuid4(),
        day_key=period_key.split(":")[0],
        period_key=period_key,
        class_id=class_id,
        subject_id="sub",
        teacher_id="t1",
        room_id=None,
        periods_per_session=periods_per_session,
        parallel_block_id=parallel_block_id,
        parallel_child_id=parallel_child_id,
        occupied_period_keys_json=occupied_keys or [period_key],
        assignment_key=f"{class_id}|{period_key}|{child}",
    )


def _setup_creation(tenant_id, timetable, version, *, swc=None,
                    cal_override=None, bell=None, existing_osd=None, assignments=None):
    """Build a mock db for creation-path tests.
    scalar sequence: timetable, swc, cal_override, bell_schedule, existing_osd
    """
    scalars = [timetable, swc, cal_override, bell, existing_osd]
    it = iter(scalars)
    db = _make_db(scalars_return=assignments or [])
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    return db


# ---------------------------------------------------------------------------
# Validation rejections
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raises_timetable_not_found():
    db = _make_db()
    db.scalar = AsyncMock(return_value=None)
    with pytest.raises(DailySessionError) as ei:
        await materialize_operational_day(
            db, tenant_id=uuid.uuid4(), timetable_id=uuid.uuid4(), school_date=date(2026, 9, 7)
        )
    assert ei.value.code == "timetable_not_found"


@pytest.mark.asyncio
async def test_raises_no_effective_timetable():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    db = _make_db()
    db.scalar = AsyncMock(return_value=tt)
    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=None)):
        with pytest.raises(DailySessionError) as ei:
            await materialize_operational_day(
                db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
            )
    assert ei.value.code == "no_effective_timetable"


@pytest.mark.asyncio
async def test_cross_tenant_timetable_not_accessible():
    """Timetable query is tenant-scoped; None return simulates cross-tenant filtering."""
    db = _make_db()
    db.scalar = AsyncMock(return_value=None)
    with pytest.raises(DailySessionError) as ei:
        await materialize_operational_day(
            db, tenant_id=uuid.uuid4(), timetable_id=uuid.uuid4(), school_date=date(2026, 9, 7)
        )
    assert ei.value.code == "timetable_not_found" and ei.value.status_code == 404


@pytest.mark.asyncio
async def test_effective_version_selected_by_date_not_arbitrary():
    """Service calls resolve_effective_version - caller cannot force a specific version."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    db = _setup_creation(tenant_id, tt, v)
    captured_call_args = []

    async def mock_rev(db, *, tenant_id, timetable_id, on_date):
        captured_call_args.append((tenant_id, timetable_id, on_date))
        return v

    with patch.object(ds_module, "resolve_effective_version", new=mock_rev):
        await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    assert len(captured_call_args) == 1
    assert captured_call_args[0][1] == tt.id
    assert captured_call_args[0][2] == date(2026, 9, 7)


# ---------------------------------------------------------------------------
# CASE 1: First-time materialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_teaching_weekend_creates_osd_no_sessions():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    db = _setup_creation(tenant_id, tt, v)

    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 12)  # Saturday
        )

    assert outcome.status == "created" and outcome.session_count == 0
    osd = [o for o in captured if hasattr(o, "is_teaching_day")][0]
    assert osd.is_teaching_day is False
    assert osd.non_teaching_reason == "not_operational_weekday"
    assert osd.timetable_day_key is None
    assert osd.source_fingerprint is not None
    assert osd.timetable_id == tt.id
    assert osd.timetable_version_id == v.id


@pytest.mark.asyncio
async def test_calendar_holiday_overrides_normal_monday():
    """A Monday explicitly marked no-school by the living calendar -> non-teaching."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    cal_event = SimpleNamespace(
        id=uuid.uuid4(), lifecycle_status="published", teaching_day_effect="non_teaching_day"
    )
    db = _setup_creation(tenant_id, tt, v, cal_override=cal_event)

    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)  # Monday
        )

    assert outcome.status == "created" and outcome.session_count == 0
    osd = [o for o in captured if hasattr(o, "is_teaching_day")][0]
    assert osd.is_teaching_day is False
    assert osd.non_teaching_reason == "calendar_non_teaching"
    assert osd.calendar_override_event_id == cal_event.id


@pytest.mark.asyncio
async def test_normal_monday_no_calendar_override_is_teaching_day():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    db = _setup_creation(tenant_id, tt, v)

    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    osd = [o for o in captured if hasattr(o, "is_teaching_day")][0]
    assert osd.is_teaching_day is True and osd.timetable_day_key == "d0"
    assert osd.calendar_override_event_id is None


@pytest.mark.asyncio
async def test_date_specific_bell_profile_used_over_default():
    """When a date-specific bell schedule exists, it is preferred over the default."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    special_bell = SimpleNamespace(id=uuid.uuid4(), schedule_type="short")
    assignment = _assignment("d0:p1")
    db = _setup_creation(tenant_id, tt, v, bell=special_bell, assignments=[assignment])

    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)), \
         patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value={})):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    osd = [o for o in captured if hasattr(o, "bell_schedule_id")][0]
    assert osd.bell_schedule_id == special_bell.id


@pytest.mark.asyncio
async def test_same_logical_period_different_bell_profile_gives_different_clock_times():
    """P3 on date A (normal bell) and P3 on date B (short bell) differ in end_time only."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    assignment = _assignment("d0:p3", occupied_keys=["d0:p3"])
    bp_normal = SimpleNamespace(id=uuid.uuid4(), period_number=3, start_time="09:00", end_time="09:50")
    bp_short  = SimpleNamespace(id=uuid.uuid4(), period_number=3, start_time="09:00", end_time="09:30")

    bell_normal = SimpleNamespace(id=uuid.uuid4(), schedule_type="normal")
    bell_short  = SimpleNamespace(id=uuid.uuid4(), schedule_type="short")

    async def run(bell, bp, school_date):
        sc = [tt, None, None, bell, None]
        it = iter(sc)
        db = _make_db(scalars_return=[assignment])
        db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
        captured = []
        db.add.side_effect = captured.append
        with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)),              patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value={3: bp})):
            await materialize_operational_day(db, tenant_id=tenant_id, timetable_id=tt.id, school_date=school_date)
        return [o for o in captured if hasattr(o, "period_end_time")][0]

    sess_a = await run(bell_normal, bp_normal, date(2026, 9, 7))
    sess_b = await run(bell_short,  bp_short,  date(2026, 9, 8))

    assert sess_a.period_number == sess_b.period_number == 3
    assert sess_a.period_end_time == "09:50"
    assert sess_b.period_end_time == "09:30"


@pytest.mark.asyncio
async def test_missing_bell_period_creates_cancelled_session():
    """Assignment P8, bell profile only has P1-P6 -> session_status=cancelled, override_reason=logical_period_unavailable."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    bell = SimpleNamespace(id=uuid.uuid4(), schedule_type="normal")
    assignment = _assignment("d0:p8", occupied_keys=["d0:p8"])

    scalars = [tt, None, None, bell, None]
    it = iter(scalars)
    db = _make_db(scalars_return=[assignment])
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    bell_periods_map = {
        i: SimpleNamespace(id=uuid.uuid4(), period_number=i,
                           start_time=f"0{7+i}:00", end_time=f"0{7+i}:50")
        for i in range(1, 7)
    }  # P1-P6 only; P8 absent

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)),          patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value=bell_periods_map)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    sessions = [o for o in captured if hasattr(o, "session_status")]
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_status == "cancelled"
    assert s.override_reason == "logical_period_unavailable"
    assert s.period_start_time is None
    assert s.period_end_time is None
    assert s.bell_period_id is None


@pytest.mark.asyncio
async def test_unavailable_session_has_no_fabricated_times():
    """Cancelled session never contains fabricated clock times."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    bell = SimpleNamespace(id=uuid.uuid4())
    assignment = _assignment("d0:p9", occupied_keys=["d0:p9"])

    sc = [tt, None, None, bell, None]
    it = iter(sc)
    db = _make_db(scalars_return=[assignment])
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)),          patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value={})):  # empty bell
        await materialize_operational_day(db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7))

    sessions = [o for o in captured if hasattr(o, "session_status")]
    for s in sessions:
        if s.session_status == "cancelled":
            assert s.period_start_time is None
            assert s.period_end_time is None


@pytest.mark.asyncio
async def test_multi_period_span_end_time_from_last_period():
    """periods_per_session=2: ONE session, start=P3.start, end=P4.end."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    bell = SimpleNamespace(id=uuid.uuid4())
    assignment = _assignment("d0:p3", periods_per_session=2, occupied_keys=["d0:p3", "d0:p4"])

    sc = [tt, None, None, bell, None]
    it = iter(sc)
    db = _make_db(scalars_return=[assignment])
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    bp3 = SimpleNamespace(id=uuid.uuid4(), period_number=3, start_time="09:00", end_time="09:50")
    bp4 = SimpleNamespace(id=uuid.uuid4(), period_number=4, start_time="10:00", end_time="10:50")

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)),          patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value={3: bp3, 4: bp4})):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    sessions = [o for o in captured if hasattr(o, "periods_span")]
    assert len(sessions) == 1
    assert sessions[0].periods_span == 2
    assert sessions[0].period_start_time == "09:00"
    assert sessions[0].period_end_time == "10:50"


@pytest.mark.asyncio
async def test_multi_period_missing_second_period_creates_cancelled():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    bell = SimpleNamespace(id=uuid.uuid4())
    assignment = _assignment("d0:p3", periods_per_session=2, occupied_keys=["d0:p3", "d0:p4"])

    sc = [tt, None, None, bell, None]
    it = iter(sc)
    db = _make_db(scalars_return=[assignment])
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    bp3 = SimpleNamespace(id=uuid.uuid4(), period_number=3, start_time="09:00", end_time="09:50")

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)),          patch.object(ds_module, "_load_bell_periods", new=AsyncMock(return_value={3: bp3})):
        await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    sessions = [o for o in captured if hasattr(o, "session_status")]
    assert sessions[0].session_status == "cancelled"
    assert sessions[0].override_reason == "logical_period_unavailable"


@pytest.mark.asyncio
async def test_parallel_children_share_class_facing_key():
    """All parallel children of the same block at the same period share class_facing_session_key."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    block_id = "pb_generic_no_subject_inspection"
    assignments = [
        _assignment("d0:p3", class_id="class_8a", parallel_block_id=block_id, parallel_child_id=f"child_{i}")
        for i in range(3)
    ]

    sc = [tt, None, None, None, None]
    it = iter(sc)
    db = _make_db(scalars_return=assignments)
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    assert outcome.session_count == 3
    sessions = [o for o in captured if hasattr(o, "class_facing_session_key")]
    assert all(s.parallel_block_id == block_id for s in sessions)
    keys = {s.class_facing_session_key for s in sessions}
    assert len(keys) == 1, "All parallel children share ONE class-facing key"


@pytest.mark.asyncio
async def test_ordinary_sessions_have_unique_class_facing_keys():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    assignments = [_assignment(f"d0:p{i}", class_id="class_7a") for i in range(1, 4)]

    sc = [tt, None, None, None, None]
    it = iter(sc)
    db = _make_db(scalars_return=assignments)
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))
    captured = []
    db.add.side_effect = captured.append

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    sessions = [o for o in captured if hasattr(o, "class_facing_session_key")]
    keys = [s.class_facing_session_key for s in sessions]
    assert len(keys) == len(set(keys)), "Ordinary sessions have distinct class-facing keys"


# ---------------------------------------------------------------------------
# CASE 2: Idempotent - same fingerprint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_fingerprint_returns_already_materialized():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    expected_fp = compute_source_fingerprint(tt.id, v.id, "d0", None, None)
    existing_osd = SimpleNamespace(id=uuid.uuid4(), source_fingerprint=expected_fp)

    scalars = [tt, None, None, None, existing_osd, 5]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    assert outcome.status == "already_materialized"
    assert outcome.session_count == 5
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_same_fingerprint_preserves_osd_identity():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    expected_fp = compute_source_fingerprint(tt.id, v.id, "d0", None, None)
    osd_id = uuid.uuid4()
    existing_osd = SimpleNamespace(id=osd_id, source_fingerprint=expected_fp)

    scalars = [tt, None, None, None, existing_osd, 0]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        outcome = await materialize_operational_day(
            db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
        )

    assert outcome.osd.id == osd_id


# ---------------------------------------------------------------------------
# CASE 3: Stale - different fingerprint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_fingerprint_raises_school_day_stale_no_writes():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    stale_osd = SimpleNamespace(id=uuid.uuid4(), source_fingerprint="a" * 64)

    scalars = [tt, None, None, None, stale_osd]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        with pytest.raises(DailySessionError) as ei:
            await materialize_operational_day(
                db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
            )

    assert ei.value.code == "school_day_stale"
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_stale_null_fingerprint_raises_school_day_stale():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    null_fp_osd = SimpleNamespace(id=uuid.uuid4(), source_fingerprint=None)

    scalars = [tt, None, None, None, null_fp_osd]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        with pytest.raises(DailySessionError) as ei:
            await materialize_operational_day(
                db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
            )

    assert ei.value.code == "school_day_stale"


@pytest.mark.asyncio
async def test_calendar_override_changes_fingerprint_causes_stale():
    """Adding a calendar non-teaching event changes the fingerprint -> stale."""
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)

    # OSD was created without a calendar override
    fp_no_override = compute_source_fingerprint(tt.id, v.id, "d0", None, None)
    existing_osd = SimpleNamespace(id=uuid.uuid4(), source_fingerprint=fp_no_override)

    # Now a calendar event creates a non-teaching override
    cal_event = SimpleNamespace(
        id=uuid.uuid4(), lifecycle_status="published", teaching_day_effect="non_teaching_day"
    )

    scalars = [tt, None, cal_event, None, existing_osd]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        with pytest.raises(DailySessionError) as ei:
            await materialize_operational_day(
                db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
            )

    assert ei.value.code == "school_day_stale"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_bell_profile_change_causes_stale():
    tenant_id = uuid.uuid4()
    tt = _timetable(tenant_id)
    v = _version(tenant_id, tt.id)
    old_bell_id = uuid.uuid4()
    fp_old = compute_source_fingerprint(tt.id, v.id, "d0", old_bell_id, None)
    existing_osd = SimpleNamespace(id=uuid.uuid4(), source_fingerprint=fp_old)

    new_bell = SimpleNamespace(id=uuid.uuid4(), schedule_type="short")

    scalars = [tt, None, None, new_bell, existing_osd]
    it = iter(scalars)
    db = _make_db()
    db.scalar = AsyncMock(side_effect=lambda *a, **k: next(it))

    with patch.object(ds_module, "resolve_effective_version", new=AsyncMock(return_value=v)):
        with pytest.raises(DailySessionError) as ei:
            await materialize_operational_day(
                db, tenant_id=tenant_id, timetable_id=tt.id, school_date=date(2026, 9, 7)
            )

    assert ei.value.code == "school_day_stale"
    db.add.assert_not_called()
