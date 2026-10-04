import asyncio
import json
import uuid

from engram_contracts.rpc import engram_pb2
from memory_service.server import MemoryService
from memory_service.store import connect, insert_memory


def test_memory_rpc_lists_ranks_and_discards():
    character_id = f"rpc-{uuid.uuid4()}"
    user_id = "local"
    memory_id = str(uuid.uuid4())
    service = MemoryService()
    try:
        with connect() as conn:
            insert_memory(
                memory_id,
                character_id,
                user_id,
                "fact",
                "The user likes tea.",
                0.8,
                None,
                "turn-a",
                conn,
            )

        async def exercise():
            health = await service.Check(engram_pb2.HealthRequest(), None)
            listed = await service.List(
                engram_pb2.ListMemoriesRequest(character_id=character_id, user_id=user_id),
                None,
            )
            ranked = await service.Rank(
                engram_pb2.RankRequest(character_id=character_id, user_id=user_id, query="tea"),
                None,
            )
            discarded = await service.DiscardTurn(
                engram_pb2.DiscardTurnRequest(source_turn_id="turn-a"),
                None,
            )
            return health, listed, ranked, discarded

        health, listed, ranked, discarded = asyncio.run(exercise())
        assert health.status == "ok"
        assert json.loads(listed.json)[0]["id"] == memory_id
        assert json.loads(ranked.json)[0]["id"] == memory_id
        assert discarded.discarded == 1
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))
            conn.execute("DELETE FROM discarded_turns WHERE source_turn_id = %s", ("turn-a",))
