from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from services.gateway.timetable_setup.policy_registry import CONSTRAINT_TYPE_REGISTRY
from services.timetable.operational_policy import (
    FALLBACK_STRATEGIES,
    OPERATIONAL_POLICY_DEFINITIONS,
    OPERATIONAL_RULE_KEYS,
    OperationalPolicyError,
    resolve_operational_staffing_policy,
    validate_fallback_tiers,
    validate_operational_rule,
)


class Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, policy=None, constraints=()):
        self.policy = policy
        self.constraints = [
            constraint
            for constraint in constraints
            if constraint.lifecycle_status == "active" and constraint.is_active
        ]
        self.scalar = AsyncMock(return_value=policy)
        self.execute = AsyncMock(return_value=Result(self.constraints))
        self.add = AsyncMock()
        self.commit = AsyncMock()


def _policy(tenant_id, **overrides):
    values = {
        "id": uuid.uuid4(), "tenant_id": tenant_id, "version_number": 3,
        "campus_id": None, "lifecycle_status": "active", "is_active": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _constraint(tenant_id, rule_key, **overrides):
    values = {
        "id": uuid.uuid4(), "tenant_id": tenant_id, "policy_set_id": uuid.uuid4(),
        "constraint_type": rule_key, "category": CONSTRAINT_TYPE_REGISTRY[rule_key]["category"],
        "enforcement_level": "hard", "priority": 10, "weight": 1.0,
        "parameters_json": {}, "lifecycle_status": "active", "is_active": True,
        "scope_type": "whole_school", "scope_reference_id": None, "scope_reference_code": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_operational_keys_use_existing_constraint_registry_and_distinct_categories():
    assert OPERATIONAL_RULE_KEYS <= set(CONSTRAINT_TYPE_REGISTRY)
    assert CONSTRAINT_TYPE_REGISTRY["require_subject_match"]["category"] == "teacher"
    assert CONSTRAINT_TYPE_REGISTRY["prefer_subject_match"]["category"] == "preference"
    assert CONSTRAINT_TYPE_REGISTRY["ordered_substitution_fallback_tiers"]["category"] == "policy"
    assert OPERATIONAL_POLICY_DEFINITIONS["require_subject_match"].operational_category == "eligibility"
    assert OPERATIONAL_POLICY_DEFINITIONS["ordered_substitution_fallback_tiers"].operational_category == "fallback"
    assert "require_department_match" not in OPERATIONAL_RULE_KEYS
    assert "prefer_department_match" not in OPERATIONAL_RULE_KEYS


def test_operational_rule_preserves_10b_scope_metadata():
    whole_school = OPERATIONAL_POLICY_DEFINITIONS["require_subject_match"]
    subject = OPERATIONAL_POLICY_DEFINITIONS["require_subject_match"]
    assert whole_school.persistence_category == "teacher"
    assert subject.persistence_category == "teacher"


def test_fallback_tiers_are_validated_and_sorted_deterministically():
    tiers = validate_fallback_tiers([
        {"priority": 2, "strategy": "leadership_escalation"},
        {"priority": 1, "strategy": "same_subject"},
    ])
    assert [(tier.priority, tier.strategy) for tier in tiers] == [(1, "same_subject"), (2, "leadership_escalation")]
    assert FALLBACK_STRATEGIES == {"same_subject", "any_eligible", "leadership_escalation"}

    with pytest.raises(OperationalPolicyError) as duplicate:
        validate_fallback_tiers([
            {"priority": 1, "strategy": "same_subject"},
            {"priority": 1, "strategy": "leadership_escalation"},
        ])
    assert duplicate.value.code == "fallback_tier_duplicate"

    with pytest.raises(OperationalPolicyError) as unsupported:
        validate_fallback_tiers([{"priority": 1, "strategy": "same_department"}])
    assert unsupported.value.code == "fallback_strategy_unsupported"


def test_operational_rule_validation_rejects_unknown_and_bad_parameters():
    with pytest.raises(OperationalPolicyError) as unknown:
        validate_operational_rule(rule_key="unknown_rule", parameters={})
    assert unknown.value.code == "operational_rule_unsupported"

    with pytest.raises(OperationalPolicyError) as invalid:
        validate_operational_rule(
            rule_key="maximum_daily_teaching_periods", parameters={"max_periods": 0}
        )
    assert invalid.value.code == "operational_rule_parameters_invalid"


@pytest.mark.asyncio
async def test_resolver_returns_explicit_missing_policy_without_mutation():
    tenant_id = uuid.uuid4()
    db = FakeDB()

    result = await resolve_operational_staffing_policy(
        db, tenant_id=tenant_id, school_date=date(2026, 9, 1)
    )

    assert result.configured is False
    assert result.issues == ("operational_policy_not_configured",)
    db.execute.assert_not_awaited()
    db.add.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_returns_only_active_effective_tenant_policy_constraints():
    tenant_id = uuid.uuid4()
    policy = _policy(tenant_id)
    valid = _constraint(
        tenant_id, "require_subject_match", policy_set_id=policy.id
    )
    inactive = _constraint(
        tenant_id, "prefer_subject_match", policy_set_id=policy.id, is_active=False
    )
    db = FakeDB(policy, [valid, inactive])

    result = await resolve_operational_staffing_policy(
        db, tenant_id=tenant_id, school_date=date(2026, 9, 1)
    )

    assert result.configured is True
    assert [rule.rule_key for rule in result.rules] == ["require_subject_match"]
    assert result.policy_set_id == policy.id
    db.add.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_preserves_same_key_whole_school_and_subject_scopes():
    tenant_id = uuid.uuid4()
    policy = _policy(tenant_id)
    subject_id = uuid.uuid4()
    whole_school = _constraint(
        tenant_id, "require_subject_match", policy_set_id=policy.id,
        scope_type="whole_school",
    )
    subject = _constraint(
        tenant_id, "require_subject_match", policy_set_id=policy.id,
        scope_type="subject", scope_reference_id=subject_id,
    )
    db = FakeDB(policy, [whole_school, subject])

    result = await resolve_operational_staffing_policy(
        db, tenant_id=tenant_id, school_date=date(2026, 9, 1)
    )

    assert len(result.rules) == 2
    assert {(rule.scope_type, rule.scope_reference_id) for rule in result.rules} == {
        ("whole_school", None), ("subject", subject_id),
    }
    assert {rule.category for rule in result.rules} == {"teacher"}
    assert {rule.operational_category for rule in result.rules} == {"eligibility"}


@pytest.mark.asyncio
async def test_multiple_fallback_constraints_report_ambiguity_without_last_row_wins():
    tenant_id = uuid.uuid4()
    policy = _policy(tenant_id)
    first = _constraint(
        tenant_id, "ordered_substitution_fallback_tiers", policy_set_id=policy.id,
        parameters_json={"tiers": [{"priority": 1, "strategy": "same_subject"}]},
    )
    second = _constraint(
        tenant_id, "ordered_substitution_fallback_tiers", policy_set_id=policy.id,
        parameters_json={"tiers": [{"priority": 1, "strategy": "any_eligible"}]},
    )
    db = FakeDB(policy, [first, second])

    result = await resolve_operational_staffing_policy(
        db, tenant_id=tenant_id, school_date=date(2026, 9, 1)
    )

    assert result.fallback_tiers == ()
    assert "ordered_substitution_fallback_tiers:fallback_policy_ambiguous" in result.issues
    assert len(result.rules) == 2

