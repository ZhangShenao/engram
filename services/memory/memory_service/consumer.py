"""Apply extract, reinforce, and forgetting off the chat turn."""

import asyncio
import logging

import grpc

from engram_contracts.rpc import engram_pb2, engram_pb2_grpc
from engram_queue.queue import TOPICS, ack, claim, ensure_topics, nack
from memory_service.store import extract_and_store, forget_stale, reinforce_memories

logger = logging.getLogger("engram.memory.queue")


async def _stamp(inspection_id: str, extract_ms: int) -> None:
    import os

    target = os.environ.get("CONTEXT_TARGET", "127.0.0.1:18411")
    channel = grpc.aio.insecure_channel(target)
    try:
        stub = engram_pb2_grpc.ContextStub(channel)
        await stub.StampExtract(
            engram_pb2.StampExtractRequest(inspection_id=inspection_id, extract_ms=extract_ms),
            timeout=10,
        )
    finally:
        await channel.close()


async def handle(job: dict) -> None:
    payload = job["payload"]
    if job["topic"] == "memory.extract":
        started = asyncio.get_running_loop().time()
        await extract_and_store(
            payload["characterId"],
            payload["userId"],
            payload.get("userMessage") or "",
            payload.get("assistantMessage") or "",
            payload["turnId"],
        )
        extract_ms = max(0, int((asyncio.get_running_loop().time() - started) * 1000))
        inspection_id = payload.get("inspectionId")
        if inspection_id:
            await _stamp(inspection_id, extract_ms)
        return
    if job["topic"] == "memory.reinforce":
        reinforce_memories(list(payload.get("memoryIds") or []))
        return
    logger.warning("unknown topic %s", job["topic"])


async def consume_once() -> bool:
    for topic in TOPICS:
        job = await asyncio.to_thread(claim, topic)
        if job is None:
            continue
        try:
            await handle(job)
        except Exception:
            logger.exception("queue job %s failed", job["id"])
            await asyncio.to_thread(nack, job["id"], job["attempts"])
        else:
            await asyncio.to_thread(ack, job["id"])
        return True
    return False


async def consume_forever(stop: asyncio.Event | None = None) -> None:
    await asyncio.to_thread(ensure_topics)
    idle_rounds = 0
    while stop is None or not stop.is_set():
        try:
            worked = await consume_once()
        except Exception:
            logger.exception("queue poll failed")
            await asyncio.sleep(1)
            continue
        if worked:
            idle_rounds = 0
            continue
        idle_rounds += 1
        if idle_rounds % 300 == 0:
            await asyncio.to_thread(forget_stale)
        await asyncio.sleep(0.2)
