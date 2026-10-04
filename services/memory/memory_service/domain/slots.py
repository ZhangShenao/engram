import re

from engram_contracts.models import MemoryType

# Dotted paths. A slot supersedes only the same path, not its parent or siblings.
MEMORY_SLOTS = {
    "USER_NAME": "user.name",
    "USER_LANGUAGE": "user.language",
    "RELATIONSHIP_STATUS": "relationship.status",
    "BOUNDARY_LIMIT": "boundary.limit",
    "PROMISE_COMMITMENT": "promise.commitment",
}

# Phase 1 called the name slot user_name. Keep that string as an alias.
SLOT_ALIASES = {
    "user_name": MEMORY_SLOTS["USER_NAME"],
    **{slot: slot for slot in MEMORY_SLOTS.values()},
}


def slot_group(slot: str | None) -> str | None:
    if not slot or "." not in slot:
        return None
    return slot.split(".", 1)[0]


def infer_memory_slot(memory_type: MemoryType | str, text: str) -> str | None:
    lower = text.lower()
    if memory_type == "fact" and (
        re.search(r"\buser'?s name\b", lower, flags=re.ASCII)
        or re.search(r"\bname is\b", lower, flags=re.ASCII)
        or re.search(r"\bcalled\b", lower, flags=re.ASCII)
    ):
        return MEMORY_SLOTS["USER_NAME"]
    if memory_type == "fact" and re.search(
        r"\bi speak\b|\blanguage is\b|\bspeaks\b", lower, flags=re.ASCII
    ):
        return MEMORY_SLOTS["USER_LANGUAGE"]
    if memory_type == "relationship" and re.search(
        r"\bwe are\b|\bwe're\b|\bmy (friend|partner)\b", lower, flags=re.ASCII
    ):
        return MEMORY_SLOTS["RELATIONSHIP_STATUS"]
    if memory_type == "boundary" and re.search(
        r"\bnever\b|\bdon't ever\b|\bdo not\b", lower, flags=re.ASCII
    ):
        return MEMORY_SLOTS["BOUNDARY_LIMIT"]
    if memory_type == "promise" and re.search(
        r"\bi promise\b|\bi swear\b|\bi will always\b|\bi'll never\b", lower, flags=re.ASCII
    ):
        return MEMORY_SLOTS["PROMISE_COMMITMENT"]
    return None


def normalize_slot(slot: object, memory_type: MemoryType | str, text: str) -> str | None:
    """Keep a known slot path. Anything else is dropped, then inferred from type and text."""
    if isinstance(slot, str) and slot in SLOT_ALIASES:
        return SLOT_ALIASES[slot]
    return infer_memory_slot(memory_type, text)
