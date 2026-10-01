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


def rank_memories(
    memories: list[MemoryRecord],
    query: str,
    now_ms: float | None = None,
    weights: dict[str, float] | None = None,
) -> list[MemoryRecord]:
    if now_ms is None:
        now_ms = time.time() * 1000
    weights = weights or DEFAULT_WEIGHTS
    active = [m for m in memories if not m.deleted_at and not m.superseded_by_id]
    ranked: list[MemoryRecord] = []
    for memory in active:
        score = (
            weights["salience"] * memory.salience
            + weights["recency"] * recency_score(memory.created_at, now_ms)
            + weights["relevance"] * relevance_score(query, memory.text)
        )
        ranked.append(memory.model_copy(update={"score": score}))
    ranked.sort(key=lambda memory: memory.score or 0.0, reverse=True)
    return ranked


def pack_memories_by_token_budget(
    ranked: list[MemoryRecord],
    budget_tokens: int,
    estimate_tokens,
) -> tuple[list[MemoryRecord], list[MemoryRecord]]:
    packed: list[MemoryRecord] = []
    dropped: list[MemoryRecord] = []
    used = 0
    header_tokens = estimate_tokens("[memories]\n")
    for memory in ranked:
        line = f"- [{memory.type}] {memory.text}"
        cost = estimate_tokens(line + "\n")
        if used + cost + header_tokens <= budget_tokens or len(packed) == 0:
            if len(packed) > 0 or used + cost + header_tokens <= budget_tokens:
                packed.append(memory)
                used += cost
            else:
                dropped.append(memory)
        else:
            dropped.append(memory)
    return packed, dropped
