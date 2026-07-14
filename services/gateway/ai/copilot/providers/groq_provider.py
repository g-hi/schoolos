from __future__ import annotations

import asyncio
from typing import Any

from langchain_groq import ChatGroq


class GroqLLMProvider:
    provider_name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(self, prompt: str) -> dict[str, Any]:
        llm = ChatGroq(model=self._model, api_key=self._api_key, temperature=0.1)
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: llm.invoke(prompt))
        return {
            "content": response.content.strip(),
            "token_usage": {},
        }
