from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.ai.copilot.state import SchoolOSAIState, sanitize_state_for_checkpoint
from shared.db.models import CopilotCheckpoint


class PostgresCheckpointStore:
    def __init__(self, db: AsyncSession, retention_days: int) -> None:
        self._db = db
        self._retention_days = retention_days

    async def save(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        tenant_uuid = UUID(str(tenant_id))
        await self.cleanup_expired()
        await self._upsert(request_id=request_id, tenant_id=tenant_uuid, tenant_slug=tenant_slug, state=state)

    async def get(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
    ) -> SchoolOSAIState | None:
        tenant_uuid = UUID(str(tenant_id))
        await self.cleanup_expired()

        result = await self._db.execute(
            select(CopilotCheckpoint).where(
                CopilotCheckpoint.request_id == request_id,
                CopilotCheckpoint.tenant_id == tenant_uuid,
                CopilotCheckpoint.tenant_slug == tenant_slug,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        if row.expires_at and row.expires_at <= datetime.now(timezone.utc):
            await self._db.delete(row)
            await self._db.commit()
            return None

        return dict(row.graph_state or {})

    async def update(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        tenant_uuid = UUID(str(tenant_id))
        await self.cleanup_expired()
        await self._upsert(request_id=request_id, tenant_id=tenant_uuid, tenant_slug=tenant_slug, state=state)

    async def cleanup_expired(self) -> int:
        if self._retention_days < 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        result = await self._db.execute(
            delete(CopilotCheckpoint).where(
                CopilotCheckpoint.updated_at <= cutoff,
            )
        )
        await self._db.commit()
        return int(result.rowcount or 0)

    async def _upsert(
        self,
        *,
        request_id: str,
        tenant_id: UUID,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires_at = None if self._retention_days < 0 else now + timedelta(days=self._retention_days)
        current_status = (state.get("final_response") or {}).get("status", "pending")

        result = await self._db.execute(
            select(CopilotCheckpoint).where(
                CopilotCheckpoint.request_id == request_id,
                CopilotCheckpoint.tenant_id == tenant_id,
                CopilotCheckpoint.tenant_slug == tenant_slug,
            )
        )
        row = result.scalar_one_or_none()

        if not row:
            row = CopilotCheckpoint(
                request_id=request_id,
                conversation_id=state.get("conversation_id"),
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                user_id=state.get("user_id", "unknown"),
                intent=state.get("intent", "unknown"),
                graph_state=_sanitize_state(state),
                current_status=current_status,
                approval_status=state.get("approval_status", "pending"),
                retry_count=state.get("retry_count", 0),
                expires_at=expires_at,
            )
            self._db.add(row)
        else:
            row.conversation_id = state.get("conversation_id")
            row.user_id = state.get("user_id", row.user_id)
            row.intent = state.get("intent", row.intent)
            row.graph_state = _sanitize_state(state)
            row.current_status = current_status
            row.approval_status = state.get("approval_status", row.approval_status)
            row.retry_count = state.get("retry_count", row.retry_count)
            row.expires_at = expires_at
            row.updated_at = now

        await self._db.commit()


def _sanitize_state(state: SchoolOSAIState) -> dict:
    return sanitize_state_for_checkpoint(state)
