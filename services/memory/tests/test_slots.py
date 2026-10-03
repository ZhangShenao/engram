import asyncio
import json
import uuid

from engram_contracts.models import MemoryCandidate, MemoryRecord
from memory_service.domain.extractor import _parse_candidates
from memory_service.domain.supersede import find_superseded_memory
from memory_service.store import connect, extract_and_store, list_memories


def _raw(memories: list[dict]) -> str:
    return json.dumps({"memories": memories})


def test_parser_drops_an_invented_slot_so_unrelated_facts_do_not_supersede():
    candidates = _parse_candidates(
        _raw(
            [
                {
                    "type": "fact",
                    "text": "The user likes coffee.",
                    "salience": 0.8,
                    "slot": "user_preference",
                },
                {
                    "type": "fact",
                    "text": "The user has a dog named Pepper.",
                    "salience": 0.7,
                    "slot": "user_preference",
                },
            ]
        )
    )
    assert [candidate.slot for candidate in candidates] == [None, None]
    stored = MemoryRecord.model_validate(
        {
            "id": "coffee",
            "characterId": "c",
            "userId": "local",
            "type": "fact",
            "text": candidates[0].text,
            "salience": 0.8,
            "slot": candidates[0].slot,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    )
    assert find_superseded_memory(candidates[1], [stored]) is None


def test_parser_keeps_the_user_name_slot():
    candidates = _parse_candidates(
        _raw(
            [
                {
                    "type": "fact",
                    "text": "The user's name is Mina.",
                    "salience": 0.9,
                    "slot": "user_name",
                }
            ]
        )
    )
    assert candidates[0].slot == "user_name"


def test_parser_infers_user_name_when_the_model_invents_a_slot():
    candidates = _parse_candidates(
        _raw(
            [
                {
                    "type": "fact",
                    "text": "The user's name is Mina.",
                    "salience": 0.9,
                    "slot": "nickname",
                }
            ]
        )
    )
    assert candidates[0].slot == "user_name"


class _ScriptedExtractor:
    def __init__(self, candidates: list[MemoryCandidate]) -> None:
        self.candidates = candidates

    async def extract(self, user_message: str, assistant_message: str) -> list[MemoryCandidate]:
        return self.candidates


def test_persisted_invented_slots_do_not_supersede_each_other(monkeypatch):
    character_id = f"slot-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    monkeypatch.setattr(
        "memory_service.store.create_extractor",
        lambda: _ScriptedExtractor(
            [
                MemoryCandidate(
                    type="fact",
                    text="The user likes coffee.",
                    salience=0.8,
                    slot="user_preference",
                ),
                MemoryCandidate(
                    type="fact",
                    text="The user has a dog named Pepper.",
                    salience=0.7,
                    slot="user_preference",
                ),
            ]
        ),
    )
    try:
        created = asyncio.run(extract_and_store(character_id, user_id, "hi", "hello", "turn-1"))
        assert [memory.slot for memory in created] == [None, None]
        stored = list_memories(character_id, user_id)
        assert len(stored) == 2
        assert all(memory.superseded_by_id is None for memory in stored)
        assert all(memory.deleted_at is None for memory in stored)
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))


def test_persisted_user_name_slot_still_supersedes(monkeypatch):
    character_id = f"slot-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    names = [
        [
            MemoryCandidate(
                type="fact",
                text="The user's name is Bob.",
                salience=0.9,
                slot="user_name",
            )
        ],
        [
            MemoryCandidate(
                type="fact",
                text="The user's name is Alex.",
                salience=0.9,
                slot="user_name",
            )
        ],
    ]

    def extractor_factory():
        return _ScriptedExtractor(names.pop(0))

    monkeypatch.setattr("memory_service.store.create_extractor", extractor_factory)
    try:
        asyncio.run(extract_and_store(character_id, user_id, "Bob", "hi", "turn-1"))
        asyncio.run(extract_and_store(character_id, user_id, "Alex", "hi", "turn-2"))
        stored = list_memories(character_id, user_id)
        bob = next(memory for memory in stored if "Bob" in memory.text)
        alex = next(memory for memory in stored if "Alex" in memory.text)
        assert bob.superseded_by_id == alex.id
        assert alex.superseded_by_id is None
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))
