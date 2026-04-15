"""
Audit Trail Router
==================
Query endpoint for the immutable AuditLog table.

Endpoints
---------
GET  /audit/  – search audit logs with filters (action, entity, actor, date range)
"""

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.db.connection import get_db, set_tenant_context
from shared.db.models import AuditLog, Tenant, User

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/", summary="Search audit trail")
async def search_audit(
    action: str | None = None,
    action_prefix: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: str | None = None,
    actor_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Query the immutable audit log with optional filters.

    Examples:
      ?action=substitution.assigned
      ?action_prefix=substitution  (matches substitution.*)
      ?entity_type=Substitution&start_date=2025-04-10&end_date=2025-04-10
      ?actor_id=<user-uuid>
      ?actor_name=Sara  (case-insensitive partial match on user name)
      ?action=timetable.generated
    """
    await set_tenant_context(db, tenant.id)

    query = (
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant.id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
    )

    if action:
        query = query.where(AuditLog.action == action)
    elif action_prefix:
        query = query.where(AuditLog.action.startswith(action_prefix))

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    if entity_id:
        try:
            eid = uuid.UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="entity_id must be a valid UUID.")
        query = query.where(AuditLog.entity_id == eid)

    if actor_id:
        try:
            aid = uuid.UUID(actor_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="actor_id must be a valid UUID.")
        query = query.where(AuditLog.actor_id == aid)
    elif actor_name:
        # Resolve user IDs matching the name (case-insensitive partial)
        name_q = await db.execute(
            select(User.id).where(
                User.tenant_id == tenant.id,
                func.lower(User.name).contains(actor_name.strip().lower()),
            )
        )
        matching_ids = name_q.scalars().all()
        if not matching_ids:
            return []
        query = query.where(AuditLog.actor_id.in_(matching_ids))

    if start_date:
        try:
            sd = date_type.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")
        query = query.where(func.date(AuditLog.created_at) >= sd)

    if end_date:
        try:
            ed = date_type.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date must be YYYY-MM-DD")
        query = query.where(func.date(AuditLog.created_at) <= ed)

    result = await db.execute(query)
    rows = result.scalars().all()

    # Batch-fetch actor names for display
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actor_names: dict[uuid.UUID, str] = {}
    if actor_ids:
        actors_q = await db.execute(
            select(User.id, User.name).where(User.id.in_(actor_ids))
        )
        for uid, name in actors_q.all():
            actor_names[uid] = name

    return [
        {
            "id": str(r.id),
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "actor_name": actor_names.get(r.actor_id) if r.actor_id else None,
            "details": r.details,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]
