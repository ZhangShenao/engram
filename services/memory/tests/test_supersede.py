from datetime import datetime, timezone

from engram_contracts.models import MemoryCandidate, MemoryRecord
from memory_service.domain.supersede import find_superseded_memory


def mem(**partial) -> MemoryRecord:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "id": partial.pop("id"),
        "text": partial.pop("text"),
        "characterId": "c",
        "userId": "local",
        "type": "fact",
        "salience": 0.8,
        "slot": None,
        "sourceTurnId": None,
        "supersededById": None,
        "deletedAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    data.update(partial)
    return MemoryRecord.model_validate(data)


def test_supersedes_name_fact_when_a_new_name_is_learned():
    old_name = mem(id="old", text="The user's name is Bob.", slot="user_name")
    target = find_superseded_memory(
        MemoryCandidate(
            type="fact",
            text="The user's name is Alex.",
            salience=0.9,
            slot="user_name",
        ),
        [old_name],
    )
    assert target is not None
    assert target.id == "old"


def test_infers_user_name_slot_when_the_candidate_omits_it():
    old_name = mem(id="old", text="The user's name is Bob.")
    target = find_superseded_memory(
        MemoryCandidate(
            type="fact",
            text="The user's name is Alex.",
            salience=0.9,
        ),
        [old_name],
    )
    assert target is not None
    assert target.id == "old"


def test_keeps_two_unrelated_facts_active():
    coffee = mem(id="coffee", type="fact", text="The user likes coffee.")
    target = find_superseded_memory(
        MemoryCandidate(
            type="fact",
            text="The user has a dog named Pepper.",
            salience=0.7,
        ),
        [coffee],
    )
    assert target is None
