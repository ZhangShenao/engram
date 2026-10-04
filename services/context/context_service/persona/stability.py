from engram_contracts.models import CharacterCard, ExampleDialogue

MIN_EXAMPLE_ANCHORS = 1

OUTPUT_SHAPE_INSTRUCTION = """Respond in character using this format:
*brief action or emotion in asterisks*
Spoken dialogue in plain text on the next line(s).
Stay in first-person as the character. No meta commentary."""

REANCHOR_INSTRUCTION = (
    "Remember: stay fully in character as defined above. "
    "Use *actions* plus spoken lines. Do not slip into assistant mode."
)


def select_example_anchors(
    examples: list[ExampleDialogue],
    max_count: int,
) -> list[ExampleDialogue]:
    if not examples:
        return []
    count = max(MIN_EXAMPLE_ANCHORS, min(max_count, len(examples)))
    return list(examples[:count])


def build_stable_persona_body(
    character: CharacterCard,
    example_anchors: list[ExampleDialogue],
) -> str:
    example_block = "\n\n".join(
        f"Example {index + 1}:\nUser: {example.user}\n{character.name}: {example.assistant}"
        for index, example in enumerate(example_anchors)
    )
    parts = [
        f"You are {character.name}. You are a fictional character in an immersive text roleplay.",
        "You are NOT a generic AI assistant. "
        "Never say you are an AI or refuse in an assistant-like way.",
        "",
        f"Tagline: {character.tagline}",
        f"Description: {character.description}",
        f"Personality: {character.personality}",
        f"Scenario: {character.scenario}",
        f"Speech style: {character.speech_style}",
        "",
        "Boundaries (never break these):",
        character.boundaries,
        "",
        f"Style anchors (match this voice):\n{example_block}" if example_block else "",
    ]
    return "\n".join(part for part in parts if part)
