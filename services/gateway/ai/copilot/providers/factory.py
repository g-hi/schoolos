from __future__ import annotations

from shared.config import settings

from .deterministic import DeterministicLLMProvider


def get_provider(preferred: str | None = None):
    provider_name = (preferred or settings.copilot_provider).lower().strip()

    if provider_name == "groq" and settings.groq_api_key.strip():
        from .groq_provider import GroqLLMProvider

        return GroqLLMProvider(api_key=settings.groq_api_key, model=settings.llm_model)

    # Deterministic stays the safe default for local and tests.
    return DeterministicLLMProvider()
