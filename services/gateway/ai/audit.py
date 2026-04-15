"""
Audit Trail Helper
==================
Provides a simple `log_action()` function that any router can call
to write an immutable AuditLog row. Keeps the audit-writing logic
in one place so routers stay clean.

Usage:
    from services.gateway.ai.audit import log_action

    await log_action(
        db=db,
        tenant_id=tenant.id,
        action="substitution.assigned",
        entity_type="Substitution",
        entity_id=substitution.id,
        actor_id=user.id,       # optional: who did this
        details={"absent": "John Smith", "substitute": "Sara Jones"},
    )
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from shared.db.models import AuditLog


async def log_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Write one immutable audit row. Call *before* db.commit() so it
    participates in the same transaction as the business logic."""
    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        details=details or {},
    )
    db.add(entry)
    return entry
