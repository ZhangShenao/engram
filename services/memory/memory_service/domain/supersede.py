from engram_contracts.models import MemoryCandidate, MemoryRecord
from memory_service.domain.rank import tokenize
from memory_service.domain.slots import infer_memory_slot

DUPLICATE_JACCARD = 0.85


def find_superseded_memory(
    candidate: MemoryCandidate,
    existing: list[MemoryRecord],
) -> MemoryRecord | None:
    if candidate.supersedes_memory_id:
        for memory in existing:
            if memory.id == candidate.supersedes_memory_id and not memory.deleted_at:
                return memory

    slot = candidate.slot or infer_memory_slot(candidate.type, candidate.text)
    if not slot:
        return None

    active = [
        memory
        for memory in existing
        if not memory.deleted_at and not memory.superseded_by_id and not memory.forgotten_at
    ]
    for memory in active:
        existing_slot = memory.slot or infer_memory_slot(memory.type, memory.text)
        if existing_slot == slot:
            return memory
    return None


def _jaccard(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def find_duplicate_memory(
    candidate: MemoryCandidate,
    existing: list[MemoryRecord],
) -> MemoryRecord | None:
    """Same fact written again reinforces the existing row instead of inserting a copy."""
    active = [
        memory
        for memory in existing
        if not memory.deleted_at and not memory.superseded_by_id and not memory.forgotten_at
    ]
    for memory in active:
        if memory.type != candidate.type:
            continue
        if _jaccard(memory.text, candidate.text) >= DUPLICATE_JACCARD:
            return memory
    return None


def apply_supersede(
    records: list[MemoryRecord],
    new_id: str,
    superseded_id: str,
    updated_at: str,
) -> list[MemoryRecord]:
    updated: list[MemoryRecord] = []
    for memory in records:
        if memory.id == superseded_id:
            updated.append(
                memory.model_copy(update={"superseded_by_id": new_id, "updated_at": updated_at})
            )
        else:
            updated.append(memory)
    return updated
