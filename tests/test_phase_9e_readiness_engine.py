from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.onboarding import readiness


def _check_map(payload: dict) -> dict[str, dict]:
    return {item["check_key"]: item for item in payload["checks"]}


def _count_stub(values: list[int]):
    iterator = iter(values)

    async def _inner(db, stmt):
        return next(iterator)

    return _inner


@pytest.mark.asyncio
async def test_empty_tenant_is_blocked() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    # No current year => terms count call is skipped; provide remaining _count values as zeros.
    values = [0] * 27
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_readiness(db, tenant_id)

    checks = _check_map(result)
    assert checks["foundation_active_campus"]["status"] == "blocking"
    assert checks["foundation_current_academic_year"]["status"] == "blocking"
    assert checks["foundation_active_terms"]["status"] == "blocking"
    assert checks["foundation_active_grade_levels"]["status"] == "blocking"
    assert checks["foundation_subjects"]["status"] == "blocking"
    assert checks["academic_active_canonical_classes"]["status"] == "blocking"
    assert checks["academic_subject_offerings"]["status"] == "blocking"
    assert checks["people_active_leadership"]["status"] == "blocking"
    assert checks["people_active_teacher_profile"]["status"] == "blocking"
    assert checks["people_parent_profile_consistency"]["status"] == "complete"
    assert checks["people_active_students"]["status"] == "blocking"
    assert checks["ops_homeroom_coverage"]["status"] == "complete"
    assert checks["ops_subject_teacher_coverage_report"]["status"] == "warning"
    assert checks["ops_active_student_enrollment_coverage"]["status"] == "complete"
    assert checks["ops_timetable_required"]["status"] == "blocking"
    assert checks["data_preview_ready_uncommitted_imports"]["status"] == "complete"
    assert checks["people_pending_invitations"]["status"] == "complete"
    assert result["blocker_count"] > 0
    assert result["readiness_percentage"] < 100


@pytest.mark.asyncio
async def test_readiness_checks_cover_warnings_info_and_next_actions() -> None:
    tenant_id = uuid.uuid4()
    current_year = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=current_year)

    # Ordered to match _count calls in compute_readiness when current year exists.
    values = [
        1,  # campuses
        1,  # terms
        3,  # grade_levels
        8,  # subjects
        2,  # active canonical classes
        0,  # invalid scope classes
        0,  # classes without academic year
        4,  # offerings
        1,  # active leadership
        2,  # active teacher profiles
        0,  # active teacher users without profile
        0,  # active parent users without relationship
        15,  # active students
        2,  # classes with homeroom
        4,  # subject teacher assignments
        15,  # active canonical students
        15,  # active enrolled students
        0,  # multiple active enrollment
        0,  # stale class pointer conflicts
        2,  # students without parent/guardian
        1,  # inactive family history
        20,  # active timetable entries
        2,  # classes with timetable
        1,  # failed imports
        1,  # preview-ready imports
        3,  # pending invitations
        1,  # expired invitations
        1,  # inactive users with active profiles
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_readiness(db, tenant_id)

    checks = _check_map(result)
    assert checks["foundation_active_campus"]["status"] == "complete"
    assert checks["foundation_current_academic_year"]["status"] == "complete"
    assert checks["foundation_active_terms"]["status"] == "complete"
    assert checks["foundation_active_grade_levels"]["status"] == "complete"
    assert checks["foundation_subjects"]["status"] == "complete"
    assert checks["academic_active_canonical_classes"]["status"] == "complete"
    assert checks["academic_subject_offerings"]["status"] == "complete"
    assert checks["people_active_leadership"]["status"] == "complete"
    assert checks["people_teacher_user_profile_consistency"]["status"] == "complete"
    assert checks["people_parent_profile_consistency"]["status"] == "complete"
    assert checks["people_active_students"]["status"] == "complete"
    assert checks["ops_homeroom_coverage"]["status"] == "complete"
    assert checks["ops_subject_teacher_coverage_report"]["status"] == "complete"
    assert checks["ops_active_student_enrollment_coverage"]["status"] == "complete"
    assert checks["ops_multiple_active_enrollment_diagnostic"]["status"] == "complete"
    assert checks["ops_stale_class_pointer_conflict"]["status"] == "complete"
    assert checks["family_students_without_parent_guardian"]["status"] == "warning"
    assert checks["family_inactive_history"]["status"] == "informational"
    assert checks["ops_timetable_required"]["status"] == "complete"
    assert checks["data_recent_failed_or_error_imports"]["status"] == "warning"
    assert checks["data_preview_ready_uncommitted_imports"]["status"] == "informational"
    assert checks["people_pending_invitations"]["status"] == "informational"
    assert checks["people_expired_invitations"]["status"] == "warning"
    assert checks["people_inactive_users_with_active_profiles"]["status"] == "warning"
    assert result["blocker_count"] == 0
    assert result["warning_count"] >= 1
    assert result["recommended_next_actions"]
    assert result["step_statuses"]["campus"] == "completed"
    assert result["readiness_percentage"] > 0


@pytest.mark.asyncio
async def test_specific_blockers_are_flagged() -> None:
    tenant_id = uuid.uuid4()
    current_year = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=current_year)

    values = [
        1, 1, 2, 4, 2, 0, 0, 2, 1, 1,
        1,  # active teacher user without profile -> blocker
        1,  # active parent user without relationship -> blocker
        10,
        0,   # no homeroom coverage -> blocker
        0,
        10,
        8,   # enrollment gap -> blocker
        1,   # multiple active -> blocker
        1,   # stale class conflict -> blocker
        0,
        0,
        0,   # no timetable -> blocker
        0,   # class timetable gap -> blocker
        0, 0, 0, 0,
        0,
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_stub(values))
        result = await readiness.compute_readiness(db, tenant_id)

    checks = _check_map(result)
    assert checks["people_teacher_user_profile_consistency"]["status"] == "blocking"
    assert checks["people_parent_profile_consistency"]["status"] == "blocking"
    assert checks["ops_homeroom_coverage"]["status"] == "blocking"
    assert checks["ops_subject_teacher_coverage_report"]["status"] == "warning"
    assert checks["ops_active_student_enrollment_coverage"]["status"] == "blocking"
    assert checks["ops_multiple_active_enrollment_diagnostic"]["status"] == "blocking"
    assert checks["ops_stale_class_pointer_conflict"]["status"] == "blocking"
    assert checks["ops_timetable_required"]["status"] == "blocking"
    assert checks["ops_timetable_gap_for_active_classes"]["status"] == "blocking"
    assert result["blocker_count"] >= 5


@pytest.mark.asyncio
async def test_tenant_scope_applied_in_queries() -> None:
    tenant_id = uuid.uuid4()
    current_year = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    db.add = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    captured_tenants: list[uuid.UUID] = []

    async def _scalar(stmt):
        params = stmt.compile().params
        for key, value in params.items():
            if key.startswith("tenant_id") and isinstance(value, uuid.UUID):
                captured_tenants.append(value)
        return current_year

    db.scalar = AsyncMock(side_effect=_scalar)

    async def _count_with_assertions(_db, stmt):
        params = stmt.compile().params
        tenant_values = [value for key, value in params.items() if key.startswith("tenant_id") and isinstance(value, uuid.UUID)]
        if tenant_values:
            captured_tenants.extend(tenant_values)
        return 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(readiness, "_count", _count_with_assertions)
        await readiness.compute_readiness(db, tenant_id)

    assert captured_tenants
    assert all(value == tenant_id for value in captured_tenants)
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()
