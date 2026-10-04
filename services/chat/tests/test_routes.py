import asyncio

from chat_service.characters import (
    create_character,
    delete_character,
    get_character,
    list_characters,
    log_request,
    update_character,
)
from chat_service.main import (
    get_character_card,
    get_chat,
    inspector,
    list_character_cards,
    list_memories,
    recent_chats,
)
from chat_service.rpc import RpcError
from engram_contracts.models import CharacterInput


def test_character_store_round_trip():
    created = create_character(CharacterInput(name=f"Nova-{id(object())}", greeting="Hey"))
    try:
        assert get_character(created.id) is not None
        assert any(item.id == created.id for item in list_characters())
        updated = update_character(created.id, CharacterInput(name="Nova Renamed", greeting="Hey"))
        assert updated is not None
        assert updated.name == "Nova Renamed"
        log_request("GET", "/api/characters", 200)
        listed = asyncio.run(list_character_cards())
        assert any(item["id"] == created.id for item in listed["characters"])
        fetched = asyncio.run(get_character_card(created.id))
        assert fetched["character"]["name"] == "Nova Renamed"
    finally:
        delete_character(created.id)
    assert asyncio.run(get_character_card(created.id)).status_code == 404


def test_read_routes_use_the_context_and_memory_clients(monkeypatch):
    character = create_character(CharacterInput(name=f"Route-{id(object())}", tagline="t"))
    calls: list[str] = []

    class Context:
        async def list_recent(self, user_id):
            calls.append("recent")
            return [
                {
                    "sessionId": "s1",
                    "characterId": character.id,
                    "lastMessage": "Hi",
                    "updatedAt": "t",
                }
            ]

        async def get_chat(self, character_id, user_id):
            calls.append("chat")
            return {"sessionId": "s1", "messages": [], "summary": ""}

        async def inspection(self, character_id, user_id):
            calls.append("inspector")
            return {"layers": []}

    class Memory:
        async def list_memories(self, character_id, user_id):
            calls.append("memories")
            return []

        async def update(self, memory_id, patch):
            calls.append("patch")
            if patch.get("text") == "bad":
                raise RpcError(400, "nope")
            return {"id": memory_id, "text": patch.get("text")}

    import chat_service.main as main

    main.app.state.context = Context()
    main.app.state.memory = Memory()
    try:
        chats = asyncio.run(recent_chats())
        assert chats["chats"][0]["name"] == character.name
        loaded = asyncio.run(get_chat(character.id))
        assert loaded["sessionId"] == "s1"
        memories = asyncio.run(list_memories(character.id))
        assert memories == {"memories": []}
        snapshot = asyncio.run(inspector(character.id))
        assert snapshot["inspector"]["layers"] == []
        from chat_service.main import patch_memory as patch

        class Request:
            async def json(self):
                return {"text": "kept"}

        updated = asyncio.run(patch("m1", Request()))
        assert updated["memory"]["text"] == "kept"
        assert calls == ["recent", "chat", "memories", "inspector", "patch"]
    finally:
        delete_character(character.id)
