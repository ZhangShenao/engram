import asyncio

import httpx
from fastapi.responses import JSONResponse

from engram_contracts.models import CharacterInput
from gateway_service.main import create_character, delete_character


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or ""

    def json(self):
        return self._payload


def _install_client(monkeypatch, post, delete):
    calls: list[tuple] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            calls.append(("POST", url, json))
            return post(url, json)

        async def delete(self, url, params=None):
            calls.append(("DELETE", url, params))
            return delete(url, params)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("gateway_service.main.httpx.AsyncClient", FakeClient)
    return calls


def test_delete_character_stops_when_memory_cleanup_fails(monkeypatch):
    calls = _install_client(
        monkeypatch,
        post=lambda url, body: FakeResponse(500),
        delete=lambda url, params: (
            FakeResponse(503, {"detail": "memory down"}, text="memory down")
            if url.endswith("/memories")
            else FakeResponse(200, {"ok": True})
        ),
    )
    result = asyncio.run(delete_character("char-1"))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert [call[0] for call in calls] == ["DELETE"]
    assert not any("/characters/char-1" in call[1] for call in calls)


def test_delete_character_stops_when_conversation_cleanup_fails(monkeypatch):
    calls = _install_client(
        monkeypatch,
        post=lambda url, body: FakeResponse(500),
        delete=lambda url, params: (
            FakeResponse(200, {"ok": True})
            if url.endswith("/memories")
            else FakeResponse(500, {"detail": "conversation down"}, text="conversation down")
        ),
    )
    result = asyncio.run(delete_character("char-1"))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert not any(call[1].rstrip("/").endswith("/characters/char-1") for call in calls)


def test_delete_character_removes_the_card_after_cleanup_succeeds(monkeypatch):
    calls = _install_client(
        monkeypatch,
        post=lambda url, body: FakeResponse(500),
        delete=lambda url, params: FakeResponse(200, {"ok": True}),
    )
    result = asyncio.run(delete_character("char-1"))
    assert result == {"ok": True}
    assert any(call[1].rstrip("/").endswith("/characters/char-1") for call in calls)


def test_create_character_fails_when_greeting_is_not_stored(monkeypatch):
    calls = _install_client(
        monkeypatch,
        post=lambda url, body: (
            FakeResponse(
                201,
                {"character": {"id": "new-id", "name": "Nova", "greeting": "Hey"}},
            )
            if url.rstrip("/").endswith("/characters")
            else FakeResponse(500, {"detail": "greeting failed"}, text="greeting failed")
        ),
        delete=lambda url, params: FakeResponse(200, {"ok": True}),
    )
    result = asyncio.run(create_character(CharacterInput(name="Nova", greeting="Hey")))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 500
    assert any(
        call[0] == "DELETE" and call[1].rstrip("/").endswith("/characters/new-id") for call in calls
    )
    assert not isinstance(result, dict)


def test_create_character_returns_the_card_when_greeting_is_stored(monkeypatch):
    body = {"character": {"id": "new-id", "name": "Nova", "greeting": "Hey"}}
    calls = _install_client(
        monkeypatch,
        post=lambda url, body_json: (
            FakeResponse(201, body)
            if url.rstrip("/").endswith("/characters")
            else FakeResponse(200, {"sessionId": "s1", "inserted": True})
        ),
        delete=lambda url, params: FakeResponse(500, {"detail": "should not delete"}),
    )
    result = asyncio.run(create_character(CharacterInput(name="Nova", greeting="Hey")))
    assert result == body
    assert not any(call[0] == "DELETE" for call in calls)
