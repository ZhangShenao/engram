import re

from engram_contracts.models import MemoryType

MEMORY_SLOTS = {
    "USER_NAME": "user_name",
}


def infer_memory_slot(memory_type: MemoryType | str, text: str) -> str | None:
    lower = text.lower()
    if memory_type == "fact" and (
        re.search(r"\buser'?s name\b", lower, flags=re.ASCII)
        or re.search(r"\bname is\b", lower, flags=re.ASCII)
        or re.search(r"\bcalled\b", lower, flags=re.ASCII)
    ):
        return MEMORY_SLOTS["USER_NAME"]
    return None


def normalize_slot(slot: object, memory_type: MemoryType | str, text: str) -> str | None:
    """Keep a known slot. Anything else is dropped, then inferred from type and text."""
    if isinstance(slot, str) and slot in MEMORY_SLOTS.values():
        return slot
    return infer_memory_slot(memory_type, text)
