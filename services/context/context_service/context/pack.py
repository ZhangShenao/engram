from engram_contracts.models import MemoryRecord


def pack_memories_by_token_budget(
    ranked: list[MemoryRecord],
    budget_tokens: int,
    estimate_tokens,
) -> tuple[list[MemoryRecord], list[MemoryRecord]]:
    """Keep memories in the order Memory already returned, until the budget is full."""
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
