from __future__ import annotations

from typing import Any, Protocol


class ProviderResult(Protocol):
    content: str
    token_usage: dict[str, Any]


class LLMProvider(Protocol):
    provider_name: str

    async def generate(self, prompt: str) -> dict[str, Any]:
        ...
