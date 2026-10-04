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

from context_service.adapters import DbQueue, DbTranscript, GrpcLlm, GrpcMemory
from context_service.inspections import init_db as init_inspections
from context_service.inspections import latest_inspection
from context_service.orchestrator import TurnError, stamp_extract, stream_turn
from context_service.transcript import (
    delete_by_character,
    ensure_greeting,
    ensure_session,
    get_summary,
    list_messages,
    recent_sessions,
)
from context_service.transcript import (
    init_db as init_transcript,
)
from engram_contracts.models import CharacterCard
from engram_contracts.rpc import engram_pb2, engram_pb2_grpc
from engram_queue.queue import init_db as init_queue

logger = logging.getLogger("engram.context")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class ContextService(engram_pb2_grpc.ContextServicer):
    def __init__(self, memory_stub, llm_stub) -> None:
        self._memory = GrpcMemory(memory_stub)
        self._llm_stub = llm_stub
        self._transcript = DbTranscript()
        self._queue = DbQueue()

    async def Check(self, request, context):
        return engram_pb2.HealthResponse(status="ok")

    async def StreamTurn(self, request, context):
        try:
            character = CharacterCard.model_validate_json(request.character_json)
        except Exception as exc:  # noqa: BLE001
            yield engram_pb2.StreamTurnEvent(kind="error", status=400, message=str(exc))
            return
        generator = stream_turn(
            character,
            request.user_id or "local",
            request.mode or "chat",
            request.message or "",
            transcript=self._transcript,
            memory=self._memory,
            llm=GrpcLlm(self._llm_stub),
            queue=self._queue,
        )
        try:
            first = await generator.__anext__()
        except StopAsyncIteration:
            await generator.aclose()
            yield engram_pb2.StreamTurnEvent(kind="error", status=500, message="Empty turn")
            return
        except TurnError as exc:
            await generator.aclose()
            yield engram_pb2.StreamTurnEvent(kind="error", status=exc.status, message=exc.message)
            return
        yield engram_pb2.StreamTurnEvent(kind="sse", sse=first)
        async for chunk in generator:
            yield engram_pb2.StreamTurnEvent(kind="sse", sse=chunk)

    async def GetChat(self, request, context):
        session_id, _created = await asyncio.to_thread(
            ensure_session, request.character_id, request.user_id or "local"
        )
        messages = await asyncio.to_thread(list_messages, session_id)
        summary = await asyncio.to_thread(get_summary, session_id)
        return engram_pb2.GetChatResponse(
            session_id=session_id,
            messages_json=json.dumps(messages),
            summary=summary,
        )

    async def ListRecent(self, request, context):
        chats = await asyncio.to_thread(recent_sessions, request.user_id or "local")
        return engram_pb2.ListRecentResponse(chats_json=json.dumps(chats))

    async def EnsureGreeting(self, request, context):
        session_id, inserted = await asyncio.to_thread(
            ensure_greeting,
            request.character_id,
            request.user_id or "local",
            request.greeting or "",
        )
        return engram_pb2.EnsureGreetingResponse(session_id=session_id, inserted=inserted)

    async def DeleteByCharacter(self, request, context):
        await asyncio.to_thread(delete_by_character, request.character_id)
        return engram_pb2.Ack(ok=True)

    async def GetInspection(self, request, context):
        payload = await asyncio.to_thread(
            latest_inspection, request.character_id, request.user_id or "local"
        )
        return engram_pb2.GetInspectionResponse(
            inspector_json=json.dumps(payload) if payload is not None else ""
        )

    async def StampExtract(self, request, context):
        await asyncio.to_thread(stamp_extract, request.inspection_id, request.extract_ms)
        return engram_pb2.Ack(ok=True)


async def serve() -> None:
    init_transcript()
    init_inspections()
    init_queue()
    memory_target = os.environ.get("MEMORY_TARGET", "127.0.0.1:18413")
    llm_target = os.environ.get("LLM_TARGET", "127.0.0.1:18414")
    memory_channel = grpc.aio.insecure_channel(memory_target)
    llm_channel = grpc.aio.insecure_channel(llm_target)
    port = os.environ.get("CONTEXT_PORT", "18411")
    server = grpc.aio.server()
    engram_pb2_grpc.add_ContextServicer_to_server(
        ContextService(
            engram_pb2_grpc.MemoryStub(memory_channel), engram_pb2_grpc.LlmStub(llm_channel)
        ),
        server,
    )
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    logger.info("context-service listening on %s", port)
    try:
        await server.wait_for_termination()
    finally:
        await memory_channel.close()
        await llm_channel.close()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
