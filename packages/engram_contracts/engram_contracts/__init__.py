"""Shared API contracts. Algorithms live in the owning service."""

from engram_contracts.constants import (
    DEFAULT_MODEL_ID,
    LOCAL_USER_ID,
    OPENROUTER_BASE_URL,
    OPENROUTER_REFERER,
    OPENROUTER_TITLE,
)
from engram_contracts.models import (
    MEMORY_TYPES,
    AssembledContext,
    CharacterCard,
    CharacterInput,
    ChatMessage,
    ContextLayer,
    ExampleDialogue,
    MemoryCandidate,
    MemoryRecord,
    MemoryType,
    VerbatimTurn,
)

__all__ = [
    "MEMORY_TYPES",
    "AssembledContext",
    "CharacterCard",
    "CharacterInput",
    "ChatMessage",
    "ContextLayer",
    "DEFAULT_MODEL_ID",
    "ExampleDialogue",
    "LOCAL_USER_ID",
    "MemoryCandidate",
    "MemoryRecord",
    "MemoryType",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_REFERER",
    "OPENROUTER_TITLE",
    "VerbatimTurn",
]
