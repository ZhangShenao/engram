import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from engram_contracts.constants import (
    DEFAULT_MODEL_ID,
    OPENROUTER_BASE_URL,
    OPENROUTER_REFERER,
    OPENROUTER_TITLE,
)
from engram_contracts.models import ChatMessage

LLM_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=30.0,
)


def open_llm_client() -> httpx.AsyncClient:
    # Identity encoding: gzip holds the whole SSE body until the model finishes.
    return httpx.AsyncClient(
        timeout=120,
        limits=LLM_LIMITS,
        headers={"Accept-Encoding": "identity"},
    )


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL_ID)
        self._client = client

    async def _iter_with(self, client: httpx.AsyncClient, payload: dict, headers: dict):
        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")[:400]
                raise RuntimeError(f"OpenRouter error {response.status_code}: {body}")
            async for line in response.aiter_lines():
                trimmed = line.strip()
                if not trimmed.startswith("data:"):
                    continue
                data = trimmed[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta

    async def iter_chunks(self, messages: list[ChatMessage]):
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            # Prefer the lowest-latency endpoint for this model. The model id stays the same.
            "provider": {"sort": "latency"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
        }
        if self._client is not None:
            async for chunk in self._iter_with(self._client, payload, headers):
                yield chunk
            return
        async with open_llm_client() as client:
            async for chunk in self._iter_with(client, payload, headers):
                yield chunk


def create_provider(client: httpx.AsyncClient | None = None):
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return OpenRouterProvider(client)
    from harness_service.llm.scripted import ScriptedLLMProvider

    return ScriptedLLMProvider()
