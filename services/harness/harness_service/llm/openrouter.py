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


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL_ID)

    async def iter_chunks(self, messages: list[ChatMessage]):
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
        }
        async with httpx.AsyncClient(timeout=120) as client:
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
                    delta = (
                        parsed.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        yield delta


def create_provider():
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return OpenRouterProvider()
    from harness_service.llm.scripted import ScriptedLLMProvider

    return ScriptedLLMProvider()
