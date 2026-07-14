from __future__ import annotations

from typing import Protocol

from services.gateway.ai.copilot.state import SchoolOSAIState


class CheckpointStore(Protocol):
    async def save(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        ...

    async def get(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
    ) -> SchoolOSAIState | None:
        ...

    async def update(
        self,
        *,
        request_id: str,
        tenant_id: str,
        tenant_slug: str,
        state: SchoolOSAIState,
    ) -> None:
        ...

    async def cleanup_expired(self) -> int:
        ...
