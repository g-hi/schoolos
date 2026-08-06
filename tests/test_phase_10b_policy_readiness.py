from __future__ import annotations

import copy
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from services.gateway.main import app
from services.gateway.routers import timetable_policies, timetable_setup_centre
from services.gateway.timetable_setup import policy_readiness as pr
from shared.auth.jwt import get_current_user
from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db


NOW = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)


def _ids() -> dict[str, str]:
    return {
        "tenant": str(uuid.uuid4()),
        "academic_year": str(uuid.uuid4()),
        "term": str(uuid.uuid4()),
        "campus": str(uuid.uuid4()),
        "other_campus": str(uuid.uuid4()),
        "grade": str(uuid.uuid4()),
        "class": str(uuid.uuid4()),
        "subject": str(uuid.uuid4()),
        "teacher": str(uuid.uuid4()),
        "room": str(uuid.uuid4()),
    }


def _context(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "tenant_id": ids["tenant"],
        "academic_year_id": ids["academic_year"],
        "term_id": ids["term"],
        "campus_id": ids["campus"],
        "grade_id": ids["grade"],
        "class_id": ids["class"],
        "subject_id": ids["subject"],
        "teacher_id": ids["teacher"],
        "room_id": ids["room"],
        "effective_at": NOW,
    }
    context.update(overrides)
    return context


def _policy_set(ids: dict[str, str], *, policy_id: str, name: str, campus_id: str | None, version_number: int, lifecycle_status: str = "active", is_active: bool = True, effective_start_date: datetime | None = None, effective_end_date: datetime | None = None, tenant_id: str | None = None) -> dict[str, object]:
    return {
        "id": policy_id,
        "tenant_id": tenant_id or ids["tenant"],
        "academic_year_id": ids["academic_year"],
        "term_id": ids["term"],
        "campus_id": campus_id,
        "name": name,
        "description": None,
        "lifecycle_status": lifecycle_status,
        "version_number": version_number,
        "is_active": is_active,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "source_type": "manual",
        "created_by_user_id": None,
        "approved_by_user_id": None,
        "approved_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _constraint(ids: dict[str, str], *, constraint_id: str, policy_set_id: str, constraint_type: str, scope_type: str, enforcement_level: str, priority: int, weight: float = 1.0, lifecycle_status: str = "active", is_active: bool = True, scope_reference_id: str | None = None, scope_reference_code: str | None = None, parameters: dict[str, object] | None = None, effective_end_date: datetime | None = None, tenant_id: str | None = None) -> dict[str, object]:
    return {
        "id": constraint_id,
        "tenant_id": tenant_id or ids["tenant"],
        "policy_set_id": policy_set_id,
        "policy_set_name": "Policy",
        "academic_year_id": ids["academic_year"],
        "term_id": ids["term"],
        "campus_id": ids["campus"],
        "constraint_type": constraint_type,
        "category": "curriculum",
        "enforcement_level": enforcement_level,
        "lifecycle_status": lifecycle_status,
        "scope_type": scope_type,
        "scope_reference_id": scope_reference_id,
        "scope_reference_code": scope_reference_code,
        "parameters": parameters or {},
        "weight": weight,
        "priority": priority,
        "is_active": is_active,
        "effective_start_date": None,
        "effective_end_date": effective_end_date,
        "explanation": None,
        "source_type": "manual",
        "confidence_score": 100,
        "requires_approval": False,
        "version_number": 1,
        "created_at": NOW,
    }


def _exception(ids: dict[str, str], *, exception_id: str, scope_type: str = "subject", policy_set_id: str | None = None, constraint_id: str | None = None, scope_reference_id: str | None = None, scope_reference_code: str | None = None, approval_state: str = "approved", reason: str = "Approved exception", is_active: bool = True, start_date: datetime | None = None, end_date: datetime | None = None, expires_at: datetime | None = None, tenant_id: str | None = None) -> dict[str, object]:
    return {
        "id": exception_id,
        "tenant_id": tenant_id or ids["tenant"],
        "policy_set_id": policy_set_id,
        "constraint_id": constraint_id,
        "scope_type": scope_type,
        "scope_reference_id": scope_reference_id,
        "scope_reference_code": scope_reference_code,
        "reason": reason,
        "start_date": start_date,
        "end_date": end_date,
        "approval_state": approval_state,
        "requested_by_user_id": None,
        "approved_by_user_id": None,
        "approved_at": NOW,
        "expires_at": expires_at,
        "is_active": is_active,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _school_week(ids: dict[str, str]) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": ids["tenant"],
        "campus_id": ids["campus"],
        "academic_year_id": ids["academic_year"],
        "term_id": ids["term"],
        "name": "Week",
        "operational_weekdays": [1, 2, 3, 4, 5],
        "is_default": True,
        "source_type": "manual",
        "review_status": "approved",
        "is_active": True,
    }


def _bell_period(ids: dict[str, str]) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": ids["tenant"],
        "bell_schedule_id": str(uuid.uuid4()),
        "period_number": 1,
        "label": "P1",
        "start_time": "08:00:00",
        "end_time": "08:40:00",
        "is_teaching_period": True,
        "is_active": True,
    }


def _requirements(ids: dict[str, str], *, teacher_id: str | None = None, specialist_room_type: str | None = None, has_fixed_sessions: bool = False) -> list[dict[str, object]]:
    return [
        {
            "id": str(uuid.uuid4()),
            "tenant_id": ids["tenant"],
            "campus_id": ids["campus"],
            "academic_year_id": ids["academic_year"],
            "term_id": ids["term"],
            "class_id": ids["class"],
            "subject_id": ids["subject"],
            "teacher_id": teacher_id,
            "sessions_per_week": 3,
            "periods_per_session": 1,
            "min_daily_sessions": 0,
            "max_daily_sessions": 5,
            "double_period_mode": "none",
            "specialist_room_type": specialist_room_type,
            "preferred_period_numbers": [],
            "forbidden_period_numbers": [],
            "has_fixed_sessions": has_fixed_sessions,
            "fixed_session_rules": [],
            "priority": 100,
            "source_type": "manual",
            "review_status": "approved",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
    ]


def _diagnostics(*, blocker_count: int = 0, warning_count: int = 0, information_count: int = 0) -> dict[str, object]:
    return {
        "generated_at": NOW,
        "summary": {"blocker_count": blocker_count, "warning_count": warning_count, "information_count": information_count},
        "generation": {
            "generation_allowed": blocker_count == 0,
            "policy_generation_allowed": blocker_count == 0,
            "readiness_status": "blocked" if blocker_count else "ready",
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "information_count": information_count,
            "pending_approval_count": 0,
        },
        "conflicts": [],
        "feasibility": [],
        "impact": [],
        "resolution_guidance": [],
        "policy_counts": {"policy_sets": 0},
    }


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True, settings={})


def _actor(tenant_id: uuid.UUID, *, role: str = "principal", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active, name="Leader", email="leader@example.test")


def _client(db: SimpleNamespace, tenant: SimpleNamespace, actor: SimpleNamespace) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[resolve_tenant] = lambda: tenant
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def _canonical(*, blocker_count: int = 0, warning_count: int = 0, information_count: int = 0) -> dict[str, int]:
    return {"blocker_count": blocker_count, "warning_count": warning_count, "information_count": information_count}


def _ready_state(ids: dict[str, str], *, policy_sets: list[dict[str, object]], constraints: list[dict[str, object]], exceptions: list[dict[str, object]] | None = None, requirements: list[dict[str, object]] | None = None, rooms: list[dict[str, object]] | None = None, school_weeks: list[dict[str, object]] | None = None, bell_periods: list[dict[str, object]] | None = None, diagnostics: dict[str, object] | None = None, canonical: dict[str, int] | None = None, context_extra: dict[str, object] | None = None) -> dict[str, object]:
    context = _context(ids)
    if context_extra:
        context.update(context_extra)
    return pr.analyze_policy_readiness_state(
        canonical_readiness=canonical or _canonical(),
        policy_sets=policy_sets,
        constraints=constraints,
        exceptions=exceptions or [],
        diagnostics=diagnostics or _diagnostics(),
        requirements=requirements or [],
        rooms=rooms or [],
            school_weeks=[_school_week(ids)] if school_weeks is None else school_weeks,
            bell_periods=[_bell_period(ids)] if bell_periods is None else bell_periods,
        classes=[],
        subjects=[],
        teachers=[],
        grade_levels=[],
        academic_years=[],
        terms=[],
        campuses=[],
        context=context,
    )


def test_policy_set_resolution_prefers_exact_scope_and_version_precedence() -> None:
    ids = _ids()
    broad_policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Broad", campus_id=None, version_number=1)
    exact_policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Exact", campus_id=ids["campus"], version_number=2)
    exact_draft = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Draft", campus_id=ids["campus"], version_number=9, lifecycle_status="draft", is_active=False)
    exact_pending = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Pending", campus_id=ids["campus"], version_number=9, lifecycle_status="pending_review", is_active=False)
    exact_suspended = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Suspended", campus_id=ids["campus"], version_number=9, lifecycle_status="suspended", is_active=False)
    exact_retired = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Retired", campus_id=ids["campus"], version_number=9, lifecycle_status="retired", is_active=False)
    expired_active = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Expired", campus_id=ids["campus"], version_number=8, effective_end_date=NOW - timedelta(days=1))
    foreign_policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Foreign", campus_id=ids["campus"], version_number=99, tenant_id=str(uuid.uuid4()))

    result = pr._select_effective_policy_set(
        [broad_policy, exact_policy, exact_draft, exact_pending, exact_suspended, exact_retired, expired_active, foreign_policy],
        _context(ids),
    )

    assert result["selected"]["id"] == exact_policy["id"]
    assert result["selected"]["campus_id"] == ids["campus"]
    assert {item["lifecycle_status"] for item in result["operational_candidates"]} == {"active"}
    assert foreign_policy["id"] not in {item["id"] for item in result["rejected_candidates"]}


def test_equal_priority_policy_overlap_blocks_readiness() -> None:
    ids = _ids()
    first = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy A", campus_id=ids["campus"], version_number=1)
    second = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy B", campus_id=ids["campus"], version_number=1)

    result = _ready_state(ids, policy_sets=[first, second], constraints=[])

    assert result["readiness_status"] == "blocked"
    assert result["generation_allowed"] is False
    assert result["policy_blocker_count"] >= 1


def test_cross_tenant_policy_is_ignored() -> None:
    ids = _ids()
    local_policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Local", campus_id=ids["campus"], version_number=1)
    foreign_policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Foreign", campus_id=ids["campus"], version_number=9, tenant_id=str(uuid.uuid4()))

    result = pr._select_effective_policy_set([foreign_policy, local_policy], _context(ids))

    assert result["selected"]["id"] == local_policy["id"]
    assert {item["id"] for item in result["rejected_candidates"]} == {local_policy["id"]}
    assert all("tenant_id" not in item for item in result["rejected_candidates"])


def test_effective_constraints_select_active_constraint_and_exclude_non_active_rows() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    active = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=10)
    draft = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5, lifecycle_status="draft", is_active=False)
    pending = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5, lifecycle_status="pending_review", is_active=False)

    result = pr._build_effective_constraints(policy, [active, draft, pending], [], _context(ids))

    assert result["selected_count"] == 1
    selected = next(item for item in result["items"] if item["selected"])
    assert selected["constraint_id"] == active["id"]
    assert selected["final_effective_enforcement"] == "hard"
    assert {item["lifecycle_status"] for item in result["items"]} == {"active"}


def test_hard_constraint_stays_hard_when_soft_rule_competes() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    hard = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="hard", priority=5)
    soft = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="soft", priority=20)

    result = pr._build_effective_constraints(policy, [hard, soft], [], _context(ids))

    assert result["items"][0]["constraint_id"] == hard["id"]
    assert result["items"][0]["final_effective_enforcement"] == "hard"


def test_exception_affects_only_explicit_constraint_target() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    targeted = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="room_capacity", scope_type="room", scope_reference_id=ids["room"], enforcement_level="hard", priority=5)
    unrelated = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="hard", priority=5)
    exception = _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=targeted["id"], scope_type="room", scope_reference_id=ids["room"], reason="Exam hall override")

    result = pr._build_effective_constraints(policy, [targeted, unrelated], [exception], _context(ids))

    targeted_item = next(item for item in result["items"] if item["constraint_id"] == targeted["id"])
    unrelated_item = next(item for item in result["items"] if item["constraint_id"] == unrelated["id"])
    assert targeted_item["final_effective_enforcement"] == "soft"
    assert targeted_item["applicable_exception"]["id"] == exception["id"]
    assert unrelated_item["final_effective_enforcement"] == "hard"
    assert unrelated_item["applicable_exception"] is None


def test_pending_expired_and_revoked_exceptions_do_not_change_effective_constraints() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    constraint = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)
    exceptions = [
        _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=constraint["id"], scope_type="subject", scope_reference_id=ids["subject"], approval_state="pending_review"),
        _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=constraint["id"], scope_type="subject", scope_reference_id=ids["subject"], expires_at=NOW - timedelta(days=1)),
        _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=constraint["id"], scope_type="subject", scope_reference_id=ids["subject"], approval_state="revoked"),
    ]

    effective_constraints = pr._build_effective_constraints(policy, [constraint], exceptions, _context(ids))
    exception_readiness = pr._evaluate_exceptions(
        exceptions=exceptions,
        selected_policy=policy,
        effective_constraints=effective_constraints["items"],
        context=_context(ids),
    )

    assert effective_constraints["items"][0]["final_effective_enforcement"] == "hard"
    assert exception_readiness["pending_exception_count"] == 1
    assert exception_readiness["expired_exception_count"] == 1
    assert exception_readiness["ignored_exception_count"] == 1
    assert exception_readiness["ready"] is False


def test_equivalent_duplicate_exceptions_are_deduplicated() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    constraint = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="room_capacity", scope_type="room", scope_reference_id=ids["room"], enforcement_level="hard", priority=5)
    exceptions = [
        _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=constraint["id"], scope_type="room", scope_reference_id=ids["room"], reason="Duplicate override"),
        _exception(ids, exception_id=str(uuid.uuid4()), constraint_id=constraint["id"], scope_type="room", scope_reference_id=ids["room"], reason="Duplicate override"),
    ]

    exception_readiness = pr._evaluate_exceptions(
        exceptions=exceptions,
        selected_policy=policy,
        effective_constraints=pr._build_effective_constraints(policy, [constraint], exceptions, _context(ids))["items"],
        context=_context(ids),
    )

    assert exception_readiness["valid_exception_count"] == 1
    assert exception_readiness["ready"] is True


def test_equal_priority_constraint_contradiction_blocks_readiness() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    first = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="hard", priority=10, parameters={"window": "AM"})
    second = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="soft", priority=10, parameters={"window": "PM"})

    result = _ready_state(ids, policy_sets=[policy], constraints=[first, second])

    assert result["readiness_status"] == "blocked"
    assert result["policy_blocker_count"] >= 1
    assert result["effective_constraints"]
    assert result["policy_score"]["overall_score"] >= 0


def test_coverage_and_score_report_mandatory_and_not_applicable_dimensions() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    curriculum = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)
    soft_preference = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="teacher_unavailable", scope_type="teacher", scope_reference_id=ids["teacher"], enforcement_level="soft", priority=50)

    result = _ready_state(
        ids,
        policy_sets=[policy],
        constraints=[curriculum, soft_preference],
        requirements=[],
        rooms=[],
        school_weeks=[_school_week(ids)],
        bell_periods=[_bell_period(ids)],
    )

    coverage = result["coverage"]
    score = result["policy_score"]
    assert coverage["coverage_percentage"] == 100
    assert coverage["missing_mandatory_checks"] == []
    assert coverage["not_applicable_checks"]
    assert coverage["excluded_not_applicable_weight"] > 0
    assert score["overall_score"] >= 0
    assert score["calculation_explanation"]
    assert result["readiness_status"] == "ready"
    assert result["generation_allowed"] is True


def test_missing_mandatory_decision_is_reported() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    curriculum = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)

    result = _ready_state(
        ids,
        policy_sets=[policy],
        constraints=[curriculum],
        school_weeks=[],
        bell_periods=[],
    )

    assert any(item["check_key"] == "school_week" for item in result["coverage"]["missing_mandatory_checks"])
    assert any(item["check_key"] == "bell_periods" for item in result["coverage"]["missing_mandatory_checks"])


def test_readiness_authorization_blocks_follow_logical_and() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    curriculum = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)

    blocked = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], canonical={"blocker_count": 1, "warning_count": 0, "information_count": 0})
    missing_policy = _ready_state(ids, policy_sets=[], constraints=[curriculum])
    diagnostic_blocked = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], diagnostics=_diagnostics(blocker_count=1))
    pending_review = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], exceptions=[_exception(ids, exception_id=str(uuid.uuid4()), constraint_id=curriculum["id"], approval_state="pending_review")])
    invalid_exception = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], exceptions=[_exception(ids, exception_id=str(uuid.uuid4()), constraint_id=curriculum["id"], expires_at=NOW - timedelta(days=1))])

    assert blocked["generation_allowed"] is False and blocked["readiness_status"] == "blocked"
    assert missing_policy["generation_allowed"] is False and missing_policy["readiness_status"] == "blocked"
    assert diagnostic_blocked["generation_allowed"] is False and diagnostic_blocked["readiness_status"] == "blocked"
    assert pending_review["generation_allowed"] is False and pending_review["readiness_status"] == "blocked"
    assert invalid_exception["generation_allowed"] is False and invalid_exception["readiness_status"] == "blocked"


@pytest.mark.asyncio
async def test_policy_readiness_payload_is_deterministic_for_identical_inputs() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    curriculum = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)
    payload_rows = {
        "policy_sets": [policy],
        "constraints": [curriculum],
        "exceptions": [],
        "requirements": [],
        "rooms": [],
        "school_weeks": [_school_week(ids)],
        "bell_periods": [_bell_period(ids)],
        "classes": [],
        "subjects": [],
        "teachers": [],
        "grade_levels": [],
        "academic_years": [],
        "terms": [],
        "campuses": [],
        "diagnostics": _diagnostics(),
        "canonical_readiness": _canonical(),
    }
    db = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pr, "_now", lambda: NOW)
        mp.setattr(pr, "_load_rows", AsyncMock(return_value=copy.deepcopy(payload_rows)))
        mp.setattr(pr, "_validate_context_references", AsyncMock(return_value={"academic_year": None, "term": None, "campus": None, "grade": None, "class": None, "subject": None, "teacher": None, "room": None}))
        first = await pr.build_policy_readiness_payload(db, ids["tenant"], academic_year_id=uuid.UUID(ids["academic_year"]), term_id=uuid.UUID(ids["term"]), campus_id=uuid.UUID(ids["campus"]))
        second = await pr.build_policy_readiness_payload(db, ids["tenant"], academic_year_id=uuid.UUID(ids["academic_year"]), term_id=uuid.UUID(ids["term"]), campus_id=uuid.UUID(ids["campus"]))

    assert first == second
    assert isinstance(first["generation_allowed"], bool)
    assert first["calculation_id"] == second["calculation_id"]


def test_readiness_routes_are_registered_without_tenant_query_parameters() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/leadership/timetable-policies/readiness",
        "/leadership/timetable-policies/readiness/effective-policy",
        "/leadership/timetable-policies/readiness/effective-constraints",
        "/leadership/timetable-policies/readiness/authorization",
    }

    assert expected.issubset(paths.keys())
    for path in expected:
        for method in paths[path].values():
            if isinstance(method, dict):
                assert all(param["name"] != "tenant" for param in method.get("parameters", []))


def test_readiness_route_authorization_and_tenant_isolation() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    payload = {
        "generated_at": NOW,
        "calculation_id": str(uuid.uuid4()),
        "readiness_status": "ready",
        "generation_allowed": True,
        "policy_set_id": str(uuid.uuid4()),
        "policy_set_status": "active",
        "policy_set_version": 1,
        "policy_explanation": {},
        "source_and_provenance_summary": {},
        "policy_blocker_count": 0,
        "policy_warning_count": 0,
        "policy_pending_approval_count": 0,
        "policy_readiness_status": "ready",
        "overall_policy_score": 100,
        "policy_score": {"overall_score": 100, "dimensions": [], "applicable_weight": 0, "completed_weight": 0, "excluded_not_applicable_weight": 0, "calculation_explanation": ""},
        "calculation_breakdown": {},
        "effective_constraint_count": 0,
        "coverage": {"coverage_percentage": 100},
        "effective_constraints": [],
        "exception_readiness": {"ready": True},
        "required_actions": [],
        "readiness_blockers": [],
        "readiness_warnings": [],
    }

    original = timetable_policies.build_policy_readiness_payload
    original_context = timetable_policies.set_tenant_context
    timetable_policies.build_policy_readiness_payload = AsyncMock(return_value=payload)
    timetable_policies.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, _actor(tenant.id, role="principal")) as client:
            assert client.get("/leadership/timetable-policies/readiness").status_code == 200
        with _client(db, tenant, _actor(tenant.id, role="school_admin")) as client:
            assert client.get("/leadership/timetable-policies/readiness").status_code == 200
        for role in ("teacher", "parent", "student"):
            with _client(db, tenant, _actor(tenant.id, role=role)) as client:
                assert client.get("/leadership/timetable-policies/readiness").status_code == 403
        with _client(db, tenant, _actor(tenant.id, is_active=False)) as client:
            assert client.get("/leadership/timetable-policies/readiness").status_code == 403
    finally:
        timetable_policies.build_policy_readiness_payload = original
        timetable_policies.set_tenant_context = original_context
        app.dependency_overrides.clear()


def test_readiness_route_rejects_unknown_context_with_controlled_4xx() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(tenant.id)

    original = timetable_policies.build_policy_readiness_payload
    original_context = timetable_policies.set_tenant_context
    timetable_policies.build_policy_readiness_payload = AsyncMock(side_effect=HTTPException(status_code=422, detail="Unknown or inactive academic year."))
    timetable_policies.set_tenant_context = AsyncMock()
    try:
        with _client(db, tenant, actor) as client:
            response = client.get("/leadership/timetable-policies/readiness", params={"academic_year_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4())})
        assert response.status_code == 422
    finally:
        timetable_policies.build_policy_readiness_payload = original
        timetable_policies.set_tenant_context = original_context
        app.dependency_overrides.clear()


def test_readiness_route_rejects_cross_tenant_actor() -> None:
    db = SimpleNamespace()
    tenant = _tenant()
    actor = _actor(uuid.uuid4())

    with _client(db, tenant, actor) as client:
        response = client.get("/leadership/timetable-policies/readiness")

    assert response.status_code == 401


def test_readiness_context_validation_rejects_department_and_validates_references() -> None:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            pr.build_policy_readiness_payload(
                db,
                uuid.uuid4(),
                academic_year_id=uuid.uuid4(),
                term_id=uuid.uuid4(),
                department_id=uuid.uuid4(),
            )
        )
    assert exc.value.status_code == 422


def test_readiness_generation_decision_is_logical_and() -> None:
    ids = _ids()
    policy = _policy_set(ids, policy_id=str(uuid.uuid4()), name="Policy", campus_id=ids["campus"], version_number=1)
    curriculum = _constraint(ids, constraint_id=str(uuid.uuid4()), policy_set_id=policy["id"], constraint_type="subject_required_weekly_sessions", scope_type="subject", scope_reference_id=ids["subject"], enforcement_level="hard", priority=5)

    canonical_blocked = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], canonical={"blocker_count": 1, "warning_count": 0, "information_count": 0})
    diagnostic_blocked = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], diagnostics=_diagnostics(blocker_count=1))
    approval_blocked = _ready_state(ids, policy_sets=[policy], constraints=[curriculum], exceptions=[_exception(ids, exception_id=str(uuid.uuid4()), constraint_id=curriculum["id"], approval_state="pending_review")])
    all_good = _ready_state(ids, policy_sets=[policy], constraints=[curriculum])

    assert canonical_blocked["generation_allowed"] is False
    assert diagnostic_blocked["generation_allowed"] is False
    assert approval_blocked["generation_allowed"] is False
    assert all_good["generation_allowed"] is True