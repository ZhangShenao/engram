import asyncio
import json
import logging
import os
from pathlib import Path

import grpc
from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from engram_contracts.models import MEMORY_TYPES
from engram_contracts.rpc import engram_pb2, engram_pb2_grpc
from engram_queue.queue import ensure_topics
from memory_service.consumer import consume_forever
from memory_service.llm_client import aclose
from memory_service.store import (
    active_memories,
    delete_for_character,
    init_db,
    rank_for_character,
    soft_delete,
    soft_delete_by_source_turn,
    update_memory,
)

logger = logging.getLogger("engram.memory")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _dump(memory) -> dict:
    return memory.model_dump(by_alias=True)


class MemoryService(engram_pb2_grpc.MemoryServicer):
    async def Check(self, request, context):
        return engram_pb2.HealthResponse(status="ok")

    async def List(self, request, context):
        memories = active_memories(request.character_id, request.user_id or "local")
        return engram_pb2.JsonReply(json=json.dumps([_dump(item) for item in memories]), found=True)

    async def Rank(self, request, context):
        ranked = rank_for_character(request.character_id, request.user_id or "local", request.query)
        return engram_pb2.JsonReply(json=json.dumps([_dump(item) for item in ranked]), found=True)

    async def DiscardTurn(self, request, context):
        discarded = await asyncio.to_thread(soft_delete_by_source_turn, request.source_turn_id)
        return engram_pb2.DiscardTurnResponse(ok=True, discarded=discarded)

    async def Update(self, request, context):
        patch = json.loads(request.patch_json or "{}")
        memory_type = patch.get("type")
        salience = patch.get("salience")
        if memory_type is not None and memory_type not in MEMORY_TYPES:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid memory type")
        if salience is not None and not 0 <= float(salience) <= 1:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "Salience must be between 0 and 1"
            )
        updated = await asyncio.to_thread(
            update_memory,
            request.memory_id,
            patch.get("text"),
            memory_type,
            None if salience is None else float(salience),
        )
        if updated is None:
            return engram_pb2.JsonReply(json="", found=False)
        return engram_pb2.JsonReply(json=json.dumps(_dump(updated)), found=True)

    async def Delete(self, request, context):
        removed = await asyncio.to_thread(soft_delete, request.memory_id)
        if not removed:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Memory not found")
        return engram_pb2.Ack(ok=True)

    async def DeleteByCharacter(self, request, context):
        await asyncio.to_thread(delete_for_character, request.character_id)
        return engram_pb2.Ack(ok=True)


async def serve() -> None:
    init_db()
    ensure_topics()
    port = os.environ.get("MEMORY_PORT", "18413")
    server = grpc.aio.server()
    engram_pb2_grpc.add_MemoryServicer_to_server(MemoryService(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    logger.info("memory-service listening on %s", port)
    consumer = asyncio.create_task(consume_forever())
    try:
        await server.wait_for_termination()
    finally:
        consumer.cancel()
        await aclose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
