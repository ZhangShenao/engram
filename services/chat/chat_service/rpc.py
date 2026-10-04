"""Long-lived clients from the public chat service to context and memory."""

import json
import os

import grpc

from engram_contracts.rpc import engram_pb2, engram_pb2_grpc


class RpcError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _status(exc: grpc.aio.AioRpcError) -> int:
    code = exc.code()
    if code == grpc.StatusCode.NOT_FOUND:
        return 404
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return 400
    return 502


class ContextClient:
    def __init__(self, target: str | None = None) -> None:
        self._channel = grpc.aio.insecure_channel(
            target or os.environ.get("CONTEXT_TARGET", "127.0.0.1:18411")
        )
        self._stub = engram_pb2_grpc.ContextStub(self._channel)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
        await self._channel.close()

    async def stream_turn(self, character_json: str, user_id: str, mode: str, message: str):
        request = engram_pb2.StreamTurnRequest(
            character_json=character_json,
            user_id=user_id,
            mode=mode,
            message=message,
        )
        call = self._stub.StreamTurn(request)
        first = await call.read()
        if first is grpc.aio.EOF:
            raise RpcError(502, "Empty turn")
        if first.kind == "error":
            raise RpcError(first.status or 502, first.message or "Turn failed")

        async def frames():
            yield first.sse
            async for event in call:
                if event.kind == "error":
                    raise RpcError(event.status or 502, event.message or "Turn failed")
                if event.sse:
                    yield event.sse

        return frames()

    async def get_chat(self, character_id: str, user_id: str) -> dict:
        try:
            reply = await self._stub.GetChat(
                engram_pb2.GetChatRequest(character_id=character_id, user_id=user_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Context request failed") from exc
        return {
            "sessionId": reply.session_id,
            "messages": json.loads(reply.messages_json or "[]"),
            "summary": reply.summary,
        }

    async def list_recent(self, user_id: str) -> list[dict]:
        try:
            reply = await self._stub.ListRecent(
                engram_pb2.ListRecentRequest(user_id=user_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Context request failed") from exc
        return json.loads(reply.chats_json or "[]")

    async def ensure_greeting(self, character_id: str, user_id: str, greeting: str) -> None:
        try:
            await self._stub.EnsureGreeting(
                engram_pb2.EnsureGreetingRequest(
                    character_id=character_id,
                    user_id=user_id,
                    greeting=greeting,
                ),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Greeting failed") from exc

    async def delete_character(self, character_id: str) -> None:
        try:
            await self._stub.DeleteByCharacter(
                engram_pb2.CharacterRef(character_id=character_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(
                _status(exc), exc.details() or "Could not delete the conversation"
            ) from exc

    async def inspection(self, character_id: str, user_id: str):
        try:
            reply = await self._stub.GetInspection(
                engram_pb2.GetInspectionRequest(character_id=character_id, user_id=user_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Inspection failed") from exc
        if not reply.inspector_json:
            return None
        return json.loads(reply.inspector_json)


class MemoryClient:
    def __init__(self, target: str | None = None) -> None:
        self._channel = grpc.aio.insecure_channel(
            target or os.environ.get("MEMORY_TARGET", "127.0.0.1:18413")
        )
        self._stub = engram_pb2_grpc.MemoryStub(self._channel)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
        await self._channel.close()

    async def list_memories(self, character_id: str, user_id: str) -> list[dict]:
        try:
            reply = await self._stub.List(
                engram_pb2.ListMemoriesRequest(character_id=character_id, user_id=user_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Memory request failed") from exc
        return json.loads(reply.json or "[]")

    async def update(self, memory_id: str, patch: dict) -> dict:
        try:
            reply = await self._stub.Update(
                engram_pb2.UpdateMemoryRequest(memory_id=memory_id, patch_json=json.dumps(patch)),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Memory update failed") from exc
        if not reply.found:
            raise RpcError(404, "Memory not found")
        return json.loads(reply.json)

    async def delete(self, memory_id: str) -> None:
        try:
            await self._stub.Delete(engram_pb2.DeleteMemoryRequest(memory_id=memory_id), timeout=30)
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Memory delete failed") from exc

    async def delete_character(self, character_id: str) -> None:
        try:
            await self._stub.DeleteByCharacter(
                engram_pb2.CharacterRef(character_id=character_id),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            raise RpcError(_status(exc), exc.details() or "Could not delete memories") from exc
