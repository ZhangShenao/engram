import math

from engram_contracts.models import (
    AssembledContext,
    CharacterCard,
    ChatMessage,
    ContextLayer,
    MemoryRecord,
    VerbatimTurn,
)
from harness_service.context.pack import pack_memories_by_token_budget
from harness_service.context.tokens import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    LAYER_BUDGET_HINTS,
    estimate_tokens,
)
from harness_service.persona.stability import (
    MIN_EXAMPLE_ANCHORS,
    OUTPUT_SHAPE_INSTRUCTION,
    REANCHOR_INSTRUCTION,
    build_stable_persona_body,
    select_example_anchors,
)
from harness_service.prompt.builder import (
    build_generation_hint,
    format_memories_block,
    format_summary_block,
)
from harness_service.prompt.templates import PROMPT_SECTION_ORDER


def turns_to_pairs(turns: list[VerbatimTurn]) -> list[list[VerbatimTurn]]:
    pairs: list[list[VerbatimTurn]] = []
    index = 0
    while index < len(turns):
        pair: list[VerbatimTurn] = []
        if turns[index].role == "user":
            pair.append(turns[index])
            index += 1
            if index < len(turns) and turns[index].role == "assistant":
                pair.append(turns[index])
                index += 1
        else:
            pair.append(turns[index])
            index += 1
        pairs.append(pair)
    return pairs


def shrink_summary(summary: str, max_tokens: int) -> tuple[str, bool]:
    if estimate_tokens(summary) <= max_tokens:
        return summary, False
    max_chars = max_tokens * 4
    return summary[: max_chars - 3] + "...", True


def assemble_context(
    character: CharacterCard,
    memories: list[MemoryRecord],
    summary: str,
    verbatim_turns: list[VerbatimTurn],
    latest_user_message: str,
    budget: int | None = None,
    rank_query: str | None = None,
) -> AssembledContext:
    token_budget = budget if budget is not None else DEFAULT_CONTEXT_TOKEN_BUDGET
    trim_log: list[str] = []
    example_count = len(character.example_dialogues)
    summary_text = summary
    summary_trimmed = False
    # Memory already ranked these via POST /memories/rank. rank_query is accepted
    # so callers can keep passing that query; Harness does not rank again.
    _ = rank_query

    packed_memories, dropped_memories = pack_memories_by_token_budget(
        list(memories),
        LAYER_BUDGET_HINTS["memoriesMax"],
        estimate_tokens,
    )
    if dropped_memories:
        trim_log.append(f"Dropped {len(dropped_memories)} lower-ranked memories from context.")

    pairs = turns_to_pairs(list(verbatim_turns))
    trimmed_turn_ids: list[str] = []
    evicted_turns: list[VerbatimTurn] = []

    def build_layers() -> dict:
        anchors = select_example_anchors(character.example_dialogues, example_count)
        persona_body = build_stable_persona_body(character, anchors)
        persona_content = persona_body + "\n\n" + OUTPUT_SHAPE_INSTRUCTION
        mem_block = format_memories_block(packed_memories)
        sum_block = format_summary_block(summary_text)
        hint = build_generation_hint(character.name)
        flat = [turn for pair in pairs for turn in pair]
        recent_content = "\n\n".join(f"{turn.role}: {turn.content}" for turn in flat) or "(none)"
        examples_trimmed = example_count < len(character.example_dialogues)
        layers = [
            ContextLayer(
                id="persona",
                label="Stable persona prefix",
                content=persona_content,
                tokenEstimate=estimate_tokens(persona_content),
                trimmed=examples_trimmed,
                trimReason=(
                    f"Reduced example dialogues to {example_count} (min {MIN_EXAMPLE_ANCHORS})."
                    if examples_trimmed
                    else None
                ),
            ),
            ContextLayer(
                id="memories",
                label="Retrieved memories",
                content=mem_block or "(none)",
                tokenEstimate=estimate_tokens(mem_block),
                trimmed=len(dropped_memories) > 0,
                trimReason="Low-score memories omitted." if dropped_memories else None,
            ),
            ContextLayer(
                id="summary",
                label="Rolling summary",
                content=sum_block or "(none)",
                tokenEstimate=estimate_tokens(sum_block),
                trimmed=summary_trimmed,
                trimReason="Summary truncated." if summary_trimmed else None,
            ),
            ContextLayer(
                id="recent",
                label="Recent turns (verbatim)",
                content=recent_content,
                tokenEstimate=estimate_tokens("\n".join(turn.content for turn in flat)),
                trimmed=len(trimmed_turn_ids) > 0,
                trimReason=(
                    f"Removed {len(trimmed_turn_ids)} oldest turn(s)." if trimmed_turn_ids else None
                ),
            ),
            ContextLayer(
                id="reanchor",
                label="Re-anchor",
                content=REANCHOR_INSTRUCTION,
                tokenEstimate=estimate_tokens(REANCHOR_INSTRUCTION),
                trimmed=False,
            ),
            ContextLayer(
                id="hint",
                label="Generation hint",
                content=hint,
                tokenEstimate=estimate_tokens(hint),
                trimmed=False,
            ),
        ]
        total = sum(layer.token_estimate for layer in layers)
        return {
            "layers": layers,
            "total": total,
            "persona_content": persona_content,
            "mem_block": mem_block,
            "sum_block": sum_block,
            "hint": hint,
        }

    built = build_layers()

    while built["total"] > token_budget and pairs:
        removed = pairs.pop(0)
        trimmed_turn_ids.extend(turn.id for turn in removed)
        evicted_turns.extend(removed)
        trim_log.append("Trimmed oldest verbatim turn pair.")
        built = build_layers()

    while built["total"] > token_budget and estimate_tokens(summary_text) > 50:
        shrunk, _did_trim = shrink_summary(
            summary_text, math.floor(LAYER_BUDGET_HINTS["summaryMax"] * 0.6)
        )
        if shrunk == summary_text:
            break
        summary_text = shrunk
        summary_trimmed = True
        trim_log.append("Shrunk rolling summary.")
        built = build_layers()

    while built["total"] > token_budget and len(packed_memories) > 1:
        removed_memory = packed_memories.pop()
        dropped_memories.append(removed_memory)
        trim_log.append("Removed lowest packed memory.")
        built = build_layers()

    while built["total"] > token_budget and example_count > MIN_EXAMPLE_ANCHORS:
        example_count -= 1
        trim_log.append("Reduced example dialogue anchors.")
        built = build_layers()

    system_content = "\n\n".join(
        part
        for part in [
            built["persona_content"],
            built["mem_block"],
            built["sum_block"],
            REANCHOR_INSTRUCTION,
            built["hint"],
        ]
        if part and part.strip()
    )
    messages = [ChatMessage(role="system", content=system_content)]
    for pair in pairs:
        for turn in pair:
            messages.append(ChatMessage(role=turn.role, content=turn.content))
    if len(messages) == 1 or messages[-1].role != "user":
        messages.append(ChatMessage(role="user", content=latest_user_message))

    return AssembledContext(
        messages=messages,
        layers=built["layers"],
        trimLog=trim_log,
        evictedTurns=evicted_turns,
        totalTokens=built["total"],
        budget=token_budget,
    )


def persona_layer_present(layers: list[ContextLayer]) -> bool:
    persona = next((layer for layer in layers if layer.id == "persona"), None)
    return bool(persona and "Boundaries" in persona.content and persona.token_estimate > 0)


def get_section_order() -> tuple[str, ...]:
    return PROMPT_SECTION_ORDER
