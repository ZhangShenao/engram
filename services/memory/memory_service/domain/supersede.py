from engram_contracts.models import MemoryCandidate, MemoryRecord
from memory_service.domain.slots import infer_memory_slot


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

    active = [m for m in existing if not m.deleted_at and not m.superseded_by_id]
    for memory in active:
        existing_slot = memory.slot or infer_memory_slot(memory.type, memory.text)
        if existing_slot == slot:
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
