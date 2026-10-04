import asyncio
import uuid

import memory_service.store as store
from engram_contracts.models import MemoryCandidate
from memory_service.domain.extractor import DeterministicMemoryExtractor
from memory_service.store import (
    connect,
    extract_and_store,
    get_memory,
    insert_memory,
    soft_delete_by_source_turn,
)


def _insert(character_id: str, user_id: str, source_turn_id: str, text: str) -> str:
    memory_id = str(uuid.uuid4())
    with connect() as conn:
        insert_memory(
            memory_id,
            character_id,
            user_id,
            "fact",
            text,
            0.6,
            None,
            source_turn_id,
            conn,
        )
    return memory_id


def test_discard_turn_soft_deletes_only_that_source_turn():
    character_id = f"discard-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    old_turn = f"turn-{uuid.uuid4()}"
    other_turn = f"turn-{uuid.uuid4()}"
    discarded_id = _insert(character_id, user_id, old_turn, "from the discarded reply")
    kept_id = _insert(character_id, user_id, other_turn, "from another turn")
    try:
        discarded_count = soft_delete_by_source_turn(old_turn)
        assert discarded_count == 1
        discarded = get_memory(discarded_id)
        kept = get_memory(kept_id)
        assert discarded is not None and discarded.deleted_at
        assert kept is not None and kept.deleted_at is None

        class _Late(DeterministicMemoryExtractor):
            async def extract(self, user_message: str, assistant_message: str):
                return [
                    MemoryCandidate(
                        type="fact",
                        text="The user's name is Late.",
                        salience=0.9,
                        slot="user.name",
                    )
                ]

        # A late extract for a discarded turn must not resurrect that reply.
        original = store.create_extractor
        store.create_extractor = lambda: _Late()
        try:
            created = asyncio.run(
                extract_and_store(character_id, user_id, "name", "Late", old_turn)
            )
        finally:
            store.create_extractor = original
        assert created == []
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))
