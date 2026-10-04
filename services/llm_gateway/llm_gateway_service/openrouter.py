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


def _headers(api_key: str, *, stream: bool) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "HTTP-Referer": OPENROUTER_REFERER,
        "X-Title": OPENROUTER_TITLE,
    }
    if stream:
        headers["Accept"] = "text/event-stream"
    return headers


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL_ID)
        self._client = client

    def _payload(
        self, messages: list[ChatMessage], model: str, *, stream: bool, temperature: float
    ):
        payload = {
            "model": model or self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": stream,
            "temperature": temperature,
            # Prefer the lowest-latency endpoint for this model. The model id stays the same.
            "provider": {"sort": "latency"},
        }
        return payload

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

    async def iter_chunks(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.8,
    ):
        payload = self._payload(messages, model or self.model, stream=True, temperature=temperature)
        headers = _headers(self.api_key, stream=True)
        if self._client is not None:
            async for chunk in self._iter_with(self._client, payload, headers):
                yield chunk
            return
        async with open_llm_client() as client:
            async for chunk in self._iter_with(client, payload, headers):
                yield chunk

    async def complete_text(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        payload = self._payload(
            messages, model or self.model, stream=False, temperature=temperature
        )
        payload["response_format"] = {"type": "json_object"}
        headers = _headers(self.api_key, stream=False)

        async def _post(client: httpx.AsyncClient) -> str:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            if response.status_code >= 400:
                body = response.text[:400]
                raise RuntimeError(f"OpenRouter error {response.status_code}: {body}")
            return response.json().get("choices", [{}])[0].get("message", {}).get("content") or ""

        if self._client is not None:
            return await _post(self._client)
        async with open_llm_client() as client:
            return await _post(client)
