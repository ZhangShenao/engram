from dataclasses import dataclass

from engram_contracts.models import CharacterCard, MemoryRecord
from harness_service.persona.stability import (
    OUTPUT_SHAPE_INSTRUCTION,
    REANCHOR_INSTRUCTION,
    build_stable_persona_body,
    select_example_anchors,
)
from harness_service.prompt.templates import PROMPT_SECTION_ORDER, PROMPT_VERSION


def build_generation_hint(character_name: str) -> str:
    return (
        f"Continue the roleplay as {character_name}. "
        "Reply with *action* then dialogue. Stay in character."
    )


def format_memories_block(memories: list[MemoryRecord]) -> str:
    if not memories:
        return ""
    lines = [f"- [{memory.type}] {memory.text}" for memory in memories]
    return "[What you remember about the user and story]\n" + "\n".join(lines)


def format_summary_block(summary: str) -> str:
    if not summary.strip():
        return ""
    return f"[Earlier conversation summary]\n{summary.strip()}"


@dataclass
class BuiltPromptSections:
    version: str
    section_order: tuple[str, ...]
    system_persona: str
    memories_block: str
    summary_block: str
    reanchor_block: str
    generation_hint: str
    system_message: str


def build_prompt_sections(
    character: CharacterCard,
    example_anchor_count: int,
    memories: list[MemoryRecord],
    summary: str,
) -> BuiltPromptSections:
    anchors = select_example_anchors(character.example_dialogues, example_anchor_count)
    persona_body = build_stable_persona_body(character, anchors)
    memories_block = format_memories_block(memories)
    summary_block = format_summary_block(summary)
    generation_hint = build_generation_hint(character.name)
    system_parts = [
        persona_body,
        OUTPUT_SHAPE_INSTRUCTION,
        memories_block,
        summary_block,
        REANCHOR_INSTRUCTION,
    ]
    system_parts = [part for part in system_parts if part.strip()]
    return BuiltPromptSections(
        version=PROMPT_VERSION,
        section_order=PROMPT_SECTION_ORDER,
        system_persona=persona_body + "\n\n" + OUTPUT_SHAPE_INSTRUCTION,
        memories_block=memories_block,
        summary_block=summary_block,
        reanchor_block=REANCHOR_INSTRUCTION,
        generation_hint=generation_hint,
        system_message="\n\n".join(system_parts),
    )


def assert_persona_contains_boundaries(system_persona: str, boundaries: str) -> bool:
    return (
        "Boundaries" in system_persona
        and boundaries in system_persona
        and "NOT a generic AI assistant" in system_persona
    )
