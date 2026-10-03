import json
import os
import re
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
from engram_contracts.models import MEMORY_TYPES, MemoryCandidate
from memory_service.domain.slots import MEMORY_SLOTS, normalize_slot


class DeterministicMemoryExtractor:
    async def extract(self, user_message: str, assistant_message: str) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        user = user_message.strip()
        assistant = assistant_message.strip()
        lower = user.lower()

        name_match = re.search(
            r"my name is ([\w\s'-]+)", lower, flags=re.IGNORECASE | re.ASCII
        ) or re.search(r"call me ([\w\s'-]+)", lower, flags=re.IGNORECASE | re.ASCII)
        if name_match:
            candidates.append(
                MemoryCandidate(
                    type="fact",
                    text=f"The user's name is {name_match.group(1).strip()}.",
                    salience=0.9,
                    slot=MEMORY_SLOTS["USER_NAME"],
                )
            )

        if re.search(r"i promise|i swear|i'll never|i will always", user, flags=re.IGNORECASE):
            candidates.append(
                MemoryCandidate(
                    type="promise",
                    text=f'User said: "{user[:200]}"',
                    salience=0.75,
                )
            )

        if re.search(r"don't ever|never mention|i hate when|boundary", user, flags=re.IGNORECASE):
            candidates.append(
                MemoryCandidate(
                    type="boundary",
                    text=f"User boundary: {user[:200]}",
                    salience=0.85,
                )
            )

        if re.search(r"we're|we are|you're my|you are my", user, flags=re.IGNORECASE):
            candidates.append(
                MemoryCandidate(
                    type="relationship",
                    text=f"Relationship note from user: {user[:200]}",
                    salience=0.7,
                )
            )

        if re.search(r"remember that|important:|plot twist|secret is", user, flags=re.IGNORECASE):
            candidates.append(
                MemoryCandidate(
                    type="plot",
                    text=user[:240],
                    salience=0.65,
                )
            )

        if not candidates and len(user) > 20:
            fact_hint = re.search(r"nice to meet you,?\s+([\w'-]+)", assistant, flags=re.IGNORECASE)
            if fact_hint:
                candidates.append(
                    MemoryCandidate(
                        type="fact",
                        text=f"The user may be called {fact_hint.group(1)}.",
                        salience=0.5,
                    )
                )

        return candidates


def _parse_candidates(raw: str) -> list[MemoryCandidate]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = parsed.get("memories") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    candidates: list[MemoryCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        memory_type = item.get("type")
        text = item.get("text")
        if not text or memory_type not in MEMORY_TYPES:
            continue
        salience = item.get("salience", 0.6)
        try:
            salience_value = float(salience)
        except (TypeError, ValueError):
            salience_value = 0.6
        text_value = str(text).strip()
        candidates.append(
            MemoryCandidate(
                type=memory_type,  # type: ignore[arg-type]
                text=text_value,
                salience=min(1.0, max(0.0, salience_value)),
                slot=normalize_slot(item.get("slot"), memory_type, text_value),
                supersedesMemoryId=item.get("supersedesMemoryId"),
            )
        )
    return candidates


_llm_client: httpx.AsyncClient | None = None


def llm_http_client() -> httpx.AsyncClient:
    global _llm_client
    if _llm_client is None or _llm_client.is_closed:
        _llm_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
        )
    return _llm_client


async def aclose_llm_client() -> None:
    global _llm_client
    if _llm_client is not None and not _llm_client.is_closed:
        await _llm_client.aclose()
    _llm_client = None


class LLMMemoryExtractor:
    async def extract(self, user_message: str, assistant_message: str) -> list[MemoryCandidate]:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        base = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL_ID)
        system = (
            "You extract structured roleplay memories from the latest exchange.\n"
            'Return JSON only: {"memories":[{"type":"fact|relationship|promise|boundary|plot",'
            '"text":"...","salience":0.0-1.0,"slot":null or "user_name"}]}\n'
            "Rules:\n"
            "- Only salient, durable facts worth recalling later.\n"
            '- Use slot "user_name" only for the user\'s name (one slot; new name supersedes).\n'
            "- Multiple facts/promises/plot beats can coexist; do not duplicate the same slot.\n"
            '- If nothing to store, return {"memories":[]}.'
        )
        try:
            response = await llm_http_client().post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": OPENROUTER_REFERER,
                    "X-Title": OPENROUTER_TITLE,
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": f"User: {user_message}\nAssistant: {assistant_message}",
                        },
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
        except httpx.HTTPError:
            return []
        if response.status_code >= 400:
            return []
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content") or "{}"
        return _parse_candidates(content)


def create_extractor():
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return LLMMemoryExtractor()
    return DeterministicMemoryExtractor()
