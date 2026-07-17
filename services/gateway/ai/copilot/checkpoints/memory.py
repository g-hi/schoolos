from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

from services.gateway.ai.copilot.state import SchoolOSAIState, sanitize_state_for_checkpoint


class InMemoryCheckpointStore:
    def __init__(self, retention_days: int = 30) -> None:
        self._data: dict[tuple[str, str], tuple[SchoolOSAIState, datetime]] = {}
        self._lock = Lock()
        self._retention_days = retention_days

    async def save(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        await self.cleanup_expired()
        with self._lock:
            self._data[(tenant_id, request_id)] = (sanitize_state_for_checkpoint(state), datetime.now(timezone.utc))

    async def get(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
    ) -> SchoolOSAIState | None:
        await self.cleanup_expired()
        with self._lock:
            value = self._data.get((tenant_id, request_id))
            return dict(value[0]) if value else None

    async def update(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        await self.cleanup_expired()
        with self._lock:
            self._data[(tenant_id, request_id)] = (sanitize_state_for_checkpoint(state), datetime.now(timezone.utc))

    async def cleanup_expired(self) -> int:
        if self._retention_days < 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        removed = 0
        with self._lock:
            for key in list(self._data.keys()):
                _, updated_at = self._data[key]
                if updated_at <= cutoff:
                    del self._data[key]
                    removed += 1
        return removed
