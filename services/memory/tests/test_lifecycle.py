import asyncio
import uuid

from engram_contracts.models import MemoryCandidate
from memory_service.consumer import handle
from memory_service.domain.extractor import DeterministicMemoryExtractor, _parse_candidates
from memory_service.store import (
    connect,
    extract_and_store,
    forget_stale,
    get_memory,
    insert_memory,
    list_memories,
    reinforce_memories,
)


def test_deterministic_extractor_recognizes_each_memory_kind():
    extractor = DeterministicMemoryExtractor()

    async def collect(user: str, assistant: str = ""):
        return await extractor.extract(user, assistant)

    name = asyncio.run(collect("My name is Mina"))
    assert name[0].slot == "user.name"
    promise = asyncio.run(collect("I promise I will write"))
    assert promise[0].type == "promise"
    boundary = asyncio.run(collect("Don't ever mention that"))
    assert boundary[0].type == "boundary"
    relationship = asyncio.run(collect("We're partners in this"))
    assert relationship[0].type == "relationship"
    plot = asyncio.run(collect("Remember that the gate is shut"))
    assert plot[0].type == "plot"
    hinted = asyncio.run(
        collect("this user line is certainly long enough", "Nice to meet you, Ada")
    )
    assert "Ada" in hinted[0].text
    assert _parse_candidates("not-json") == []
    assert _parse_candidates('{"memories":[{"type":"nope","text":"x"}]}') == []


def test_reinforce_and_forget_round_trip():
    character_id = f"life-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    memory_id = str(uuid.uuid4())
    try:
        with connect() as conn:
            insert_memory(
                memory_id,
                character_id,
                user_id,
                "fact",
                "The user likes quiet mornings.",
                0.3,
                None,
                "turn",
                conn,
            )
            conn.execute(
                "UPDATE memories SET created_at = %s WHERE id = %s",
                ("2026-01-01T00:00:00.000Z", memory_id),
            )
        assert reinforce_memories([memory_id]) == 1
        reinforced = get_memory(memory_id)
        assert reinforced is not None
        assert reinforced.salience > 0.3
        assert reinforced.last_reinforced_at
        forgotten = forget_stale(now_ms=1_735_689_600_000)
        assert forgotten == 0
        assert forget_stale(now_ms=1_800_000_000_000) >= 0
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))


def test_duplicate_text_reinforces_instead_of_inserting(monkeypatch):
    character_id = f"dup-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"

    class _Same:
        async def extract(self, user_message: str, assistant_message: str):
            return [
                MemoryCandidate(type="fact", text="The user likes coffee.", salience=0.8),
                MemoryCandidate(type="fact", text="The user likes coffee.", salience=0.9),
            ]

    monkeypatch.setattr("memory_service.store.create_extractor", lambda: _Same())
    try:
        created = asyncio.run(extract_and_store(character_id, user_id, "coffee", "ok", "t1"))
        stored = list_memories(character_id, user_id)
        assert len(created) == 1
        assert len(stored) == 1
        assert stored[0].salience == 0.9
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))


def test_queue_handler_extracts_and_reinforces(monkeypatch):
    seen: dict = {}

    async def fake_extract(*args, **kwargs):
        seen["extract"] = args
        return []

    def fake_reinforce(ids, step=0.05):
        seen["ids"] = ids
        return len(ids)

    async def fake_stamp(inspection_id, extract_ms):
        seen["stamp"] = (inspection_id, extract_ms)

    monkeypatch.setattr("memory_service.consumer.extract_and_store", fake_extract)
    monkeypatch.setattr("memory_service.consumer.reinforce_memories", fake_reinforce)
    monkeypatch.setattr("memory_service.consumer._stamp", fake_stamp)
    asyncio.run(
        handle(
            {
                "topic": "memory.extract",
                "payload": {
                    "characterId": "c",
                    "userId": "u",
                    "userMessage": "hi",
                    "assistantMessage": "hey",
                    "turnId": "t",
                    "inspectionId": "i",
                },
            }
        )
    )
    asyncio.run(handle({"topic": "memory.reinforce", "payload": {"memoryIds": ["m1"]}}))
    assert seen["extract"][0] == "c"
    assert seen["stamp"][0] == "i"
    assert seen["ids"] == ["m1"]
