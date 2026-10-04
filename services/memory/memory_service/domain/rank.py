import re
import time
from datetime import datetime

from engram_contracts.models import MemoryRecord

DEFAULT_WEIGHTS = {
    "salience": 0.45,
    "recency": 0.35,
    "relevance": 0.2,
}


def tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.ASCII)
    return {word for word in cleaned.split() if len(word) > 2}


def relevance_score(query: str, memory_text: str) -> float:
    query_tokens = tokenize(query)
    memory_tokens = tokenize(memory_text)
    if not query_tokens or not memory_tokens:
        return 0.0
    overlap = sum(1 for word in query_tokens if word in memory_tokens)
    return overlap / len(query_tokens)


def _parse_ms(created_at: str) -> float:
    normalized = created_at.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp() * 1000


def recency_score(created_at: str, now_ms: float) -> float:
    age_ms = now_ms - _parse_ms(created_at)
    days = age_ms / 86_400_000
    return max(0.0, 1 - days / 30)


HALF_LIFE_DAYS = 30
FORGET_AFTER_DAYS = 14
FORGET_SALIENCE = 0.2


def age_days(stamp: str, now_ms: float) -> float:
    return max(0.0, now_ms - _parse_ms(stamp)) / 86_400_000


def decay_factor(stamp: str, now_ms: float) -> float:
    return 0.5 ** (age_days(stamp, now_ms) / HALF_LIFE_DAYS)


def effective_salience(memory: MemoryRecord, now_ms: float) -> float:
    anchor = memory.last_reinforced_at or memory.created_at
    return memory.salience * decay_factor(anchor, now_ms)


def should_forget(memory: MemoryRecord, now_ms: float) -> bool:
    if memory.deleted_at or memory.superseded_by_id or memory.forgotten_at:
        return False
    if age_days(memory.created_at, now_ms) < FORGET_AFTER_DAYS:
        return False
    return effective_salience(memory, now_ms) < FORGET_SALIENCE


def rank_memories(
    memories: list[MemoryRecord],
    query: str,
    now_ms: float | None = None,
    weights: dict[str, float] | None = None,
) -> list[MemoryRecord]:
    if now_ms is None:
        now_ms = time.time() * 1000
    weights = weights or DEFAULT_WEIGHTS
    active = [
        memory
        for memory in memories
        if not memory.deleted_at and not memory.superseded_by_id and not memory.forgotten_at
    ]
    ranked: list[MemoryRecord] = []
    for memory in active:
        score = (
            weights["salience"] * effective_salience(memory, now_ms)
            + weights["recency"] * recency_score(memory.created_at, now_ms)
            + weights["relevance"] * relevance_score(query, memory.text)
        )
        ranked.append(memory.model_copy(update={"score": score}))
    ranked.sort(key=lambda memory: memory.score or 0.0, reverse=True)
    return ranked
