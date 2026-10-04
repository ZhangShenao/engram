import asyncio
import json
import uuid

from context_service.inspections import init_db as init_inspections
from context_service.server import ContextService
from context_service.transcript import delete_by_character, init_db
from engram_contracts.rpc import engram_pb2


class _Memory:
    async def Rank(self, request, timeout=None):
        return engram_pb2.JsonReply(json="[]", found=True)

    async def DiscardTurn(self, request, timeout=None):
        return engram_pb2.DiscardTurnResponse(ok=True, discarded=0)


class _Llm:
    async def Complete(self, request):
        yield engram_pb2.CompleteEvent(
            text="Hello.",
            served=engram_pb2.ModelPin(provider="scripted", model="scripted"),
        )
        yield engram_pb2.CompleteEvent(
            done=True,
            served=engram_pb2.ModelPin(provider="scripted", model="scripted"),
        )


def test_context_rpc_reads_and_writes_a_session():
    init_db()
    init_inspections()
    character_id = f"ctx-{uuid.uuid4()}"
    service = ContextService(_Memory(), _Llm())
    try:

        async def exercise():
            health = await service.Check(engram_pb2.HealthRequest(), None)
            greeting = await service.EnsureGreeting(
                engram_pb2.EnsureGreetingRequest(
                    character_id=character_id,
                    user_id="local",
                    greeting="Welcome.",
                ),
                None,
            )
            chat = await service.GetChat(
                engram_pb2.GetChatRequest(character_id=character_id, user_id="local"),
                None,
            )
            recent = await service.ListRecent(engram_pb2.ListRecentRequest(user_id="local"), None)
            return health, greeting, chat, recent

        health, greeting, chat, recent = asyncio.run(exercise())
        assert health.status == "ok"
        assert greeting.inserted is True
        messages = json.loads(chat.messages_json)
        assert messages[0]["content"] == "Welcome."
        assert any(item["characterId"] == character_id for item in json.loads(recent.chats_json))
    finally:
        delete_by_character(character_id)
