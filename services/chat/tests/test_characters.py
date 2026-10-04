import asyncio

from fastapi.responses import JSONResponse

from chat_service.main import delete_character_tree, post_character
from chat_service.rpc import RpcError
from engram_contracts.models import CharacterCard, CharacterInput


class _Character:
    id = "new-id"
    greeting = "Hey"

    def model_dump(self, by_alias=True):
        return {"id": self.id, "name": "Nova", "greeting": self.greeting}


def test_delete_character_stops_when_memory_cleanup_fails():
    class Memory:
        async def delete_character(self, character_id):
            raise RpcError(503, "memory down")

    class Context:
        async def delete_character(self, character_id):
            raise AssertionError("context should not be called")

    result = asyncio.run(delete_character_tree("char-1", Memory(), Context()))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503


def test_delete_character_stops_when_context_cleanup_fails(monkeypatch):
    calls: list[str] = []

    class Memory:
        async def delete_character(self, character_id):
            calls.append("memory")

    class Context:
        async def delete_character(self, character_id):
            calls.append("context")
            raise RpcError(500, "context down")

    monkeypatch.setattr("chat_service.main.remove_character", lambda character_id: True)
    result = asyncio.run(delete_character_tree("char-1", Memory(), Context()))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert calls == ["memory", "context"]


def test_delete_character_removes_the_card_after_cleanup_succeeds(monkeypatch):
    removed: list[str] = []

    class Memory:
        async def delete_character(self, character_id):
            return None

    class Context:
        async def delete_character(self, character_id):
            return None

    monkeypatch.setattr(
        "chat_service.main.remove_character",
        lambda character_id: removed.append(character_id) or True,
    )
    result = asyncio.run(delete_character_tree("char-1", Memory(), Context()))
    assert result == {"ok": True}
    assert removed == ["char-1"]


def test_create_character_rolls_back_when_greeting_fails(monkeypatch):
    removed: list[str] = []
    monkeypatch.setattr("chat_service.main.insert_character", lambda payload: _Character())
    monkeypatch.setattr(
        "chat_service.main.remove_character",
        lambda character_id: removed.append(character_id) or True,
    )

    class Context:
        async def ensure_greeting(self, character_id, user_id, greeting):
            raise RpcError(500, "greeting failed")

    import chat_service.main as main

    main.app.state.context = Context()
    result = asyncio.run(post_character(CharacterInput(name="Nova", greeting="Hey")))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert removed == ["new-id"]


def test_create_character_returns_the_card_when_greeting_is_stored(monkeypatch):
    monkeypatch.setattr(
        "chat_service.main.insert_character",
        lambda payload: CharacterCard.model_validate(
            {
                "id": "new-id",
                "name": "Nova",
                "greeting": "Hey",
                "createdAt": "2026-01-01T00:00:00.000Z",
                "updatedAt": "2026-01-01T00:00:00.000Z",
            }
        ),
    )
    monkeypatch.setattr(
        "chat_service.main.remove_character",
        lambda character_id: (_ for _ in ()).throw(AssertionError("should not delete")),
    )

    class Context:
        async def ensure_greeting(self, character_id, user_id, greeting):
            assert character_id == "new-id"
            assert greeting == "Hey"

    import chat_service.main as main

    main.app.state.context = Context()
    result = asyncio.run(post_character(CharacterInput(name="Nova", greeting="Hey")))
    assert result["character"]["id"] == "new-id"
