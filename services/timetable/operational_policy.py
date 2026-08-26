"""Read-only structured operational staffing policy for Phase 10E-4A."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.timetable_setup.policy_registry import (
    CONSTRAINT_TYPE_REGISTRY,
    validate_constraint_parameters,
)
from shared.db.models import (
    AcademicYear,
    Term,
    TimetablePolicyConstraint,
    TimetablePolicySet,
)


@dataclass(frozen=True)
class OperationalPolicyDefinition:
    rule_key: str
    operational_category: str
    persistence_category: str


OPERATIONAL_POLICY_DEFINITIONS = {
    "require_subject_match": OperationalPolicyDefinition("require_subject_match", "eligibility", "teacher"),
    "maximum_daily_teaching_periods": OperationalPolicyDefinition("maximum_daily_teaching_periods", "eligibility", "workload"),
    "maximum_daily_operational_minutes": OperationalPolicyDefinition("maximum_daily_operational_minutes", "eligibility", "workload"),
    "protected_periods": OperationalPolicyDefinition("protected_periods", "eligibility", "time"),
    "prefer_subject_match": OperationalPolicyDefinition("prefer_subject_match", "ranking", "preference"),
    "prefer_lower_baseline_workload": OperationalPolicyDefinition("prefer_lower_baseline_workload", "ranking", "preference"),
    "prefer_lower_recent_substitution_burden": OperationalPolicyDefinition("prefer_lower_recent_substitution_burden", "ranking", "preference"),
    "ordered_substitution_fallback_tiers": OperationalPolicyDefinition("ordered_substitution_fallback_tiers", "fallback", "policy"),
}

OPERATIONAL_RULE_KEYS = frozenset(OPERATIONAL_POLICY_DEFINITIONS)

FALLBACK_STRATEGIES = frozenset({"same_subject", "any_eligible", "leadership_escalation"})


class OperationalPolicyError(Exception):
    """Controlled errors for operational policy contract resolution."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class OperationalPolicyRule:
    rule_key: str
    category: str
    operational_category: str
    enforcement_level: str
    enabled: bool
    parameters: dict
    priority: int
    weight: float
    constraint_id: uuid.UUID
    scope_type: str
    scope_reference_id: uuid.UUID | None
    scope_reference_code: str | None


@dataclass(frozen=True)
class FallbackTier:
    priority: int
    strategy: str


@dataclass(frozen=True)
class OperationalPolicySnapshot:
    tenant_id: uuid.UUID
    school_date: date_type
    policy_set_id: uuid.UUID | None
    policy_version: int | None
    configured: bool
    rules: tuple[OperationalPolicyRule, ...]
    fallback_tiers: tuple[FallbackTier, ...]
    issues: tuple[str, ...] = ()


def validate_fallback_tiers(value: object) -> tuple[FallbackTier, ...]:
    if not isinstance(value, list) or not value:
        raise OperationalPolicyError("fallback_tiers_invalid")
    tiers: list[FallbackTier] = []
    priorities: set[int] = set()
    strategies: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"priority", "strategy"}:
            raise OperationalPolicyError("fallback_tier_invalid")
        priority = item["priority"]
        strategy = item["strategy"]
        if isinstance(priority, bool) or not isinstance(priority, int) or priority <= 0:
            raise OperationalPolicyError("fallback_tier_priority_invalid")
        if not isinstance(strategy, str) or strategy not in FALLBACK_STRATEGIES:
            raise OperationalPolicyError("fallback_strategy_unsupported")
        if priority in priorities or strategy in strategies:
            raise OperationalPolicyError("fallback_tier_duplicate")
        priorities.add(priority)
        strategies.add(strategy)
        tiers.append(FallbackTier(priority=priority, strategy=strategy))
    return tuple(sorted(tiers, key=lambda tier: tier.priority))


def validate_operational_rule(*, rule_key: str, parameters: dict) -> None:
    if rule_key not in OPERATIONAL_RULE_KEYS:
        raise OperationalPolicyError("operational_rule_unsupported")
    definition = CONSTRAINT_TYPE_REGISTRY[rule_key]
    operational_definition = OPERATIONAL_POLICY_DEFINITIONS[rule_key]
    if definition["category"] != operational_definition.persistence_category:
        raise OperationalPolicyError("operational_rule_category_mismatch")
    errors = validate_constraint_parameters(definition, parameters)
    if errors:
        raise OperationalPolicyError("operational_rule_parameters_invalid", "; ".join(errors))
    if rule_key == "ordered_substitution_fallback_tiers":
        validate_fallback_tiers(parameters.get("tiers"))


async def resolve_operational_staffing_policy(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    school_date: date_type,
    academic_year_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
) -> OperationalPolicySnapshot:
    """Resolve the active, effective, tenant-owned operational policy snapshot."""
    policy_query = (
        select(TimetablePolicySet)
        .join(AcademicYear, AcademicYear.id == TimetablePolicySet.academic_year_id)
        .join(Term, Term.id == TimetablePolicySet.term_id)
        .where(
            TimetablePolicySet.tenant_id == tenant_id,
            AcademicYear.tenant_id == tenant_id,
            Term.tenant_id == tenant_id,
            TimetablePolicySet.lifecycle_status == "active",
            TimetablePolicySet.is_active.is_(True),
            AcademicYear.is_active.is_(True),
            Term.is_active.is_(True),
            AcademicYear.start_date <= school_date,
            AcademicYear.end_date >= school_date,
            Term.start_date <= school_date,
            Term.end_date >= school_date,
            (TimetablePolicySet.campus_id == campus_id) | (TimetablePolicySet.campus_id.is_(None)),
        )
    )
    if academic_year_id is not None:
        policy_query = policy_query.where(TimetablePolicySet.academic_year_id == academic_year_id)
    if term_id is not None:
        policy_query = policy_query.where(TimetablePolicySet.term_id == term_id)
    policy_query = policy_query.where(
        (TimetablePolicySet.effective_start_date.is_(None))
        | (TimetablePolicySet.effective_start_date <= school_date),
        (TimetablePolicySet.effective_end_date.is_(None))
        | (TimetablePolicySet.effective_end_date >= school_date),
    ).order_by(
        (TimetablePolicySet.campus_id == campus_id).desc(),
        TimetablePolicySet.version_number.desc(),
        TimetablePolicySet.id,
    )
    policy = await db.scalar(policy_query)
    if policy is None:
        return OperationalPolicySnapshot(
            tenant_id=tenant_id,
            school_date=school_date,
            policy_set_id=None,
            policy_version=None,
            configured=False,
            rules=(),
            fallback_tiers=(),
            issues=("operational_policy_not_configured",),
        )

    constraint_rows = await db.execute(
        select(TimetablePolicyConstraint).where(
            TimetablePolicyConstraint.tenant_id == tenant_id,
            TimetablePolicyConstraint.policy_set_id == policy.id,
            TimetablePolicyConstraint.lifecycle_status == "active",
            TimetablePolicyConstraint.is_active.is_(True),
            (TimetablePolicyConstraint.effective_start_date.is_(None))
            | (TimetablePolicyConstraint.effective_start_date <= school_date),
            (TimetablePolicyConstraint.effective_end_date.is_(None))
            | (TimetablePolicyConstraint.effective_end_date >= school_date),
        ).order_by(TimetablePolicyConstraint.priority, TimetablePolicyConstraint.id)
    )
    rules: list[OperationalPolicyRule] = []
    fallback_tiers: tuple[FallbackTier, ...] = ()
    fallback_rule_count = 0
    issues: list[str] = []
    for constraint in constraint_rows.scalars().all():
        if constraint.constraint_type not in OPERATIONAL_RULE_KEYS:
            continue
        try:
            validate_operational_rule(
                rule_key=constraint.constraint_type,
                parameters=dict(constraint.parameters_json or {}),
            )
        except OperationalPolicyError as error:
            issues.append(f"{constraint.constraint_type}:{error.code}")
            continue
        rule = OperationalPolicyRule(
            rule_key=constraint.constraint_type,
            category=constraint.category,
            operational_category=OPERATIONAL_POLICY_DEFINITIONS[constraint.constraint_type].operational_category,
            enforcement_level=constraint.enforcement_level,
            enabled=True,
            parameters=dict(constraint.parameters_json or {}),
            priority=constraint.priority,
            weight=constraint.weight,
            constraint_id=constraint.id,
            scope_type=constraint.scope_type,
            scope_reference_id=constraint.scope_reference_id,
            scope_reference_code=constraint.scope_reference_code,
        )
        rules.append(rule)
        if constraint.constraint_type == "ordered_substitution_fallback_tiers":
            fallback_rule_count += 1
            if fallback_rule_count == 1:
                fallback_tiers = validate_fallback_tiers(rule.parameters["tiers"])

    if fallback_rule_count > 1:
        fallback_tiers = ()
        issues.append("ordered_substitution_fallback_tiers:fallback_policy_ambiguous")

    return OperationalPolicySnapshot(
        tenant_id=tenant_id,
        school_date=school_date,
        policy_set_id=policy.id,
        policy_version=policy.version_number,
        configured=bool(rules),
        rules=tuple(rules),
        fallback_tiers=fallback_tiers,
        issues=tuple(issues),
    )