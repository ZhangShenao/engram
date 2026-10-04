import asyncio

from fastapi.responses import StreamingResponse

from chat_service.main import _proxy_turn, app
from chat_service.rpc import RpcError
from engram_contracts.models import CharacterCard

CHARACTER = CharacterCard.model_validate(
    {
        "id": "c1",
        "name": "Lyra",
        "greeting": "Welcome.",
        "createdAt": "2026-01-01T00:00:00.000Z",
        "updatedAt": "2026-01-01T00:00:00.000Z",
    }
)


class _Context:
    def __init__(self, frames=None, error: RpcError | None = None) -> None:
        self.frames = frames or [b'data: {"type": "chunk", "text": "Hi"}\n\n']
        self.error = error
        self.closed = False

    async def stream_turn(self, character_json, user_id, mode, message):
        if self.error:
            raise self.error

        async def generate():
            for frame in self.frames:
                yield frame

        return generate()

    async def aclose(self):
        self.closed = True


def test_proxy_turn_does_not_close_the_shared_client(monkeypatch):
    context = _Context()
    app.state.context = context
    monkeypatch.setattr("chat_service.main.get_character", lambda character_id: CHARACTER)

    async def scenario():
        response = await _proxy_turn("c1", "chat", "Hello")
        assert isinstance(response, StreamingResponse)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        return body

    body = asyncio.run(scenario())
    assert b"Hi" in body
    assert context.closed is False


def test_proxy_turn_error_does_not_close_the_shared_client(monkeypatch):
    context = _Context(error=RpcError(502, "context down"))
    app.state.context = context
    monkeypatch.setattr("chat_service.main.get_character", lambda character_id: CHARACTER)
    response = asyncio.run(_proxy_turn("c1", "chat", "Hello"))
    assert response.status_code == 502
    assert context.closed is False
