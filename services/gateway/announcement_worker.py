from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.gateway.announcements import claim_due_announcement_ids, claim_due_notification_ids, deliver_notification, publish_announcement
from shared.config import get_settings
from shared.db.models import Tenant

logger = logging.getLogger(__name__)


async def publish_due_for_tenant(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 20, worker_id: str = "announcement-worker") -> int:
    ids = await claim_due_announcement_ids(db, tenant_id, limit=limit, claimant_id=worker_id)
    published = 0
    for announcement_id in ids:
        try:
            await publish_announcement(db, tenant_id, announcement_id)
            published += 1
        except Exception:
            logger.warning("scheduled announcement publication failed")
    retry_ids = await claim_due_notification_ids(db, tenant_id, limit=max(limit * 5, limit))
    for notification_id in retry_ids:
        try:
            await deliver_notification(db, notification_id, tenant_id)
        except Exception:
            logger.warning("announcement notification retry failed")
    return published


async def run_once(limit: int = 20, worker_id: str = "announcement-worker") -> int:
    settings = get_settings()
    engine = create_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    total = 0
    async with session_factory() as db:
        tenants = (await db.execute(Tenant.__table__.select().where(Tenant.is_active.is_(True)))).scalars().all()
        for tenant in tenants:
            total += await publish_due_for_tenant(db, tenant.id, limit=limit, worker_id=worker_id)
    await engine.dispose()
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish due SchoolOS announcements")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--worker-id", type=str, default=os.getenv("HOSTNAME", "announcement-worker"))
    args = parser.parse_args()
    asyncio.run(run_once(limit=args.limit, worker_id=args.worker_id))
