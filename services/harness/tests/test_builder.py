from engram_contracts.models import CharacterCard, ExampleDialogue
from harness_service.prompt.builder import (
    assert_persona_contains_boundaries,
    build_generation_hint,
    build_prompt_sections,
)
from harness_service.prompt.templates import PROMPT_SECTION_ORDER

sample_character = CharacterCard(
    id="c1",
    name="Test Hero",
    tagline="A test",
    description="Desc",
    personality="Brave",
    scenario="Arena",
    example_dialogues=[ExampleDialogue(user="Hi", assistant="*nods*\nHello.")],
    greeting="Hey",
    speech_style="Short",
    boundaries="No breaking the fourth wall.",
    created_at="",
    updated_at="",
)


def test_keeps_defined_section_order():
    built = build_prompt_sections(
        character=sample_character,
        example_anchor_count=1,
        memories=[],
        summary="",
    )
    assert built.section_order == PROMPT_SECTION_ORDER
    assert built.section_order.index("boundaries") < built.section_order.index("recent_turns")


def test_includes_persona_boundaries_and_output_shape():
    built = build_prompt_sections(
        character=sample_character,
        example_anchor_count=1,
        memories=[],
        summary="They met before.",
    )
    assert assert_persona_contains_boundaries(
        built.system_persona, sample_character.boundaries
    )
    assert "*nods*" in built.system_persona or "*" in built.system_persona
    assert "NOT a generic AI assistant" in built.system_persona
    assert "Test Hero" in build_generation_hint(sample_character.name)
