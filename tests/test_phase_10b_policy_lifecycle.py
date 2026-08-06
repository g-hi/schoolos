from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.gateway.routers import timetable_policies as policies
from shared.db.models import TimetablePolicyConstraint, TimetablePolicyException, TimetablePolicySet


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.scalar = AsyncMock()
        self.execute = AsyncMock()
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()


def _tenant() -> SimpleNamespace:
    tid = uuid.uuid4()
    return SimpleNamespace(id=tid)


def _actor(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, is_active=True)


@pytest.mark.asyncio
async def test_policy_set_lifecycle_happy_path_submit_approve_activate_suspend_retire() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    policy = TimetablePolicySet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        name="Policy Draft",
        lifecycle_status="draft",
        version_number=1,
        is_active=False,
        source_type="manual",
    )

    with patch.object(policies, "_append_policy_version", new=AsyncMock()), patch.object(policies, "log_action", new=AsyncMock()):
        db.scalar = AsyncMock(side_effect=[policy])
        submitted = await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="submit", reason="review")
        assert submitted["lifecycle_status"] == "pending_review"

        db.scalar = AsyncMock(side_effect=[policy])
        approved = await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="approve", reason="approved")
        assert approved["lifecycle_status"] == "approved"

        db.scalar = AsyncMock(side_effect=[policy, None])
        active = await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="activate", reason="go-live")
        assert active["lifecycle_status"] == "active"
        assert active["is_active"] is True

        db.scalar = AsyncMock(side_effect=[policy])
        suspended = await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="suspend", reason="pause")
        assert suspended["lifecycle_status"] == "suspended"

        db.scalar = AsyncMock(side_effect=[policy])
        retired = await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="retire", reason="close")
        assert retired["lifecycle_status"] == "retired"


@pytest.mark.asyncio
async def test_policy_set_invalid_transition_rejected() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    policy = TimetablePolicySet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        name="Active Policy",
        lifecycle_status="active",
        version_number=3,
        is_active=True,
        source_type="manual",
    )

    with patch.object(policies, "_append_policy_version", new=AsyncMock()), patch.object(policies, "log_action", new=AsyncMock()):
        db.scalar = AsyncMock(side_effect=[policy])
        with pytest.raises(HTTPException) as exc:
            await policies._policy_set_lifecycle(db=db, tenant=tenant, actor=actor, policy_set_id=policy.id, action="submit", reason="invalid")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_constraint_activation_requires_active_policy_set() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    policy_set = TimetablePolicySet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        academic_year_id=uuid.uuid4(),
        term_id=uuid.uuid4(),
        name="Approved but Inactive",
        lifecycle_status="approved",
        version_number=1,
        is_active=False,
        source_type="manual",
    )
    constraint = TimetablePolicyConstraint(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        policy_set_id=policy_set.id,
        constraint_type="teacher_unavailable",
        category="teacher",
        enforcement_level="hard",
        lifecycle_status="approved",
        scope_type="teacher",
        parameters_json={"weekdays": [1], "period_numbers": [2]},
        weight=1.0,
        priority=10,
        is_active=True,
        source_type="manual",
        requires_approval=False,
        version_number=1,
    )

    with patch.object(policies, "_append_constraint_version", new=AsyncMock()), patch.object(policies, "log_action", new=AsyncMock()):
        db.scalar = AsyncMock(side_effect=[constraint, policy_set])
        with pytest.raises(HTTPException) as exc:
            await policies._constraint_lifecycle(db=db, tenant=tenant, actor=actor, constraint_id=constraint.id, action="activate", reason="invalid")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_exception_submit_approve_revoke_and_reject_paths() -> None:
    tenant = _tenant()
    actor = _actor(tenant_id=tenant.id)
    db = _Db()

    pending = TimetablePolicyException(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        policy_set_id=uuid.uuid4(),
        scope_type="whole_school",
        reason="Exam week",
        approval_state="draft",
        is_active=True,
    )

    with patch.object(policies, "set_tenant_context", new=AsyncMock()), patch.object(policies, "log_action", new=AsyncMock()):
        db.scalar = AsyncMock(return_value=pending)
        submitted = await policies.submit_exception(
            pending.id,
            body=policies.LifecycleReasonRequest(reason="submit"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert submitted["approval_state"] == "pending_review"

        db.scalar = AsyncMock(return_value=pending)
        approved = await policies.approve_exception(
            pending.id,
            body=policies.LifecycleReasonRequest(reason="approve"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert approved["approval_state"] == "approved"

        db.scalar = AsyncMock(return_value=pending)
        revoked = await policies.revoke_exception(
            pending.id,
            body=policies.LifecycleReasonRequest(reason="revoke"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert revoked["approval_state"] == "revoked"

    rejected = TimetablePolicyException(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        constraint_id=uuid.uuid4(),
        scope_type="teacher",
        scope_reference_id=uuid.uuid4(),
        reason="Unavailable",
        approval_state="pending_review",
        is_active=True,
    )

    with patch.object(policies, "set_tenant_context", new=AsyncMock()), patch.object(policies, "log_action", new=AsyncMock()):
        db.scalar = AsyncMock(return_value=rejected)
        rejected_payload = await policies.reject_exception(
            rejected.id,
            body=policies.LifecycleReasonRequest(reason="reject"),
            tenant=tenant,
            actor=actor,
            db=db,
        )
        assert rejected_payload["approval_state"] == "rejected"
