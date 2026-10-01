from datetime import datetime, timezone

from engram_contracts.models import CharacterCard, ExampleDialogue, MemoryRecord, VerbatimTurn
from harness_service.context.assembler import assemble_context, persona_layer_present

character = CharacterCard(
    id="c1",
    name="Lyra",
    tagline="Mage",
    description="A mage",
    personality="Wise",
    scenario="Tower",
    example_dialogues=[
        ExampleDialogue(user="Hello", assistant="*bows*\nWelcome."),
        ExampleDialogue(user="Teach me", assistant="*smiles*\nListen."),
    ],
    greeting="Hi",
    speech_style="Formal",
    boundaries="Never OOC.",
    created_at="",
    updated_at="",
)


def make_turns(count: int) -> list[VerbatimTurn]:
    turns: list[VerbatimTurn] = []
    for index in range(count):
        turns.append(
            VerbatimTurn(
                id=f"u{index}",
                role="user",
                content=f"User message number {index} with some padding text to consume tokens.",
            )
        )
        turns.append(
            VerbatimTurn(
                id=f"a{index}",
                role="assistant",
                content=f"Assistant reply number {index} with roleplay *action* and dialogue.",
            )
        )
    return turns


def test_trims_oldest_turns_before_dropping_persona():
    result = assemble_context(
        character=character,
        memories=[],
        summary="A long " * 200,
        verbatim_turns=make_turns(40),
        latest_user_message="Latest?",
        budget=800,
    )
    persona = next(layer for layer in result.layers if layer.id == "persona")
    assert persona_layer_present(result.layers) is True
    assert "Never OOC." in persona.content
    assert any("oldest" in entry for entry in result.trim_log)
    assert len(result.evicted_turns) > 0
    assert result.evicted_turns[0].role


def test_lists_evicted_turns_in_order():
    turns = make_turns(8)
    result = assemble_context(
        character=character,
        memories=[],
        summary="",
        verbatim_turns=turns,
        latest_user_message="Latest?",
        budget=400,
    )
    evicted_ids = [turn.id for turn in result.evicted_turns]
    assert turns[0].id in evicted_ids
    recent = next(layer for layer in result.layers if layer.id == "recent")
    assert turns[0].content not in recent.content


def test_records_trim_on_budget_overflow():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    memories = [
        MemoryRecord(
            id=f"m{index}",
            characterId="c1",
            userId="local",
            type="fact",
            text=f"Memory fact number {index} with extra words",
            salience=0.5,
            slot=None,
            sourceTurnId=None,
            supersededById=None,
            deletedAt=None,
            createdAt=now,
            updatedAt=now,
        )
        for index in range(20)
    ]
    result = assemble_context(
        character=character,
        memories=memories,
        summary="",
        verbatim_turns=make_turns(5),
        latest_user_message="test",
        budget=1200,
    )
    assert result.total_tokens <= result.budget + 50
    assert persona_layer_present(result.layers) is True


def test_keeps_persona_when_history_is_long():
    result = assemble_context(
        character=character,
        memories=[],
        summary="x" * 1000,
        verbatim_turns=make_turns(60),
        latest_user_message="Still here?",
        budget=600,
    )
    persona = next(layer for layer in result.layers if layer.id == "persona")
    assert "Lyra" in persona.content
    assert "Never OOC." in persona.content
