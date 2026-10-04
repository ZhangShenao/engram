import asyncio
import json

import grpc

from context_service import transcript as transcript_store
from context_service.orchestrator import TurnError
from engram_contracts.models import ChatMessage, MemoryRecord
from engram_contracts.rpc import engram_pb2
from engram_queue.queue import publish


class DbTranscript:
    async def ensure_session(self, character_id: str, user_id: str) -> tuple[str, bool]:
        return await asyncio.to_thread(transcript_store.ensure_session, character_id, user_id)

    async def add_message(self, session_id: str, role: str, content: str) -> dict:
        return await asyncio.to_thread(transcript_store.add_message, session_id, role, content)

    async def list_messages(self, session_id: str) -> list[dict]:
        return await asyncio.to_thread(transcript_store.list_messages, session_id)

    async def get_summary(self, session_id: str) -> str:
        return await asyncio.to_thread(transcript_store.get_summary, session_id)

    async def append_summary(self, session_id: str, text: str) -> str:
        return await asyncio.to_thread(transcript_store.append_summary, session_id, text)

    async def replace_message(self, session_id: str, message_id: str, role: str, content: str):
        return await asyncio.to_thread(
            transcript_store.replace_message, session_id, message_id, role, content
        )

    async def get_pin(self, session_id: str) -> tuple[str, str]:
        return await asyncio.to_thread(transcript_store.get_pin, session_id)

    async def set_pin(self, session_id: str, provider: str, model: str) -> None:
        await asyncio.to_thread(transcript_store.set_pin, session_id, provider, model)


class DbQueue:
    def publish(self, topic: str, payload: dict) -> None:
        publish(topic, payload)


class GrpcMemory:
    def __init__(self, stub) -> None:
        self._stub = stub

    async def rank(self, character_id: str, user_id: str, query: str) -> list[MemoryRecord]:
        try:
            reply = await self._stub.Rank(
                engram_pb2.RankRequest(character_id=character_id, user_id=user_id, query=query),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise TurnError(502, exc.details() or "Memory rank failed") from exc
        return [MemoryRecord.model_validate(item) for item in json.loads(reply.json or "[]")]

    async def discard_turn(self, source_turn_id: str) -> None:
        try:
            reply = await self._stub.DiscardTurn(
                engram_pb2.DiscardTurnRequest(source_turn_id=source_turn_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise TurnError(502, "Could not clear memories from the discarded reply.") from exc
        if not reply.ok:
            raise TurnError(502, "Could not clear memories from the discarded reply.")


class GrpcLlm:
    def __init__(self, stub) -> None:
        self._stub = stub
        self.served_provider = "scripted"
        self.served_model = "scripted"

    async def iter_chunks(self, messages: list[ChatMessage], pin: tuple[str, str]):
        request = engram_pb2.CompleteRequest(
            pin=engram_pb2.ModelPin(provider=pin[0], model=pin[1]),
            messages=[
                engram_pb2.LlmMessage(role=item.role, content=item.content) for item in messages
            ],
            temperature=0.8,
        )
        try:
            async for event in self._stub.Complete(request):
                if event.served.provider:
                    self.served_provider = event.served.provider
                    self.served_model = event.served.model
                if event.error:
                    raise RuntimeError(event.error)
                if event.text:
                    yield event.text
        except grpc.aio.AioRpcError as exc:
            raise RuntimeError(exc.details() or "Model call failed") from exc
