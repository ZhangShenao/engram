import asyncio

import httpx
from fastapi.responses import StreamingResponse

from gateway_service.main import _proxy_turn, app


class _Upstream:
    def __init__(self, status_code: int, body: bytes = b"") -> None:
        self.status_code = status_code
        self._body = body
        self.closed = False

    async def aiter_bytes(self):
        yield b'data: {"type": "chunk", "text": "Hi"}\n\n'

    async def aread(self):
        return self._body

    async def aclose(self):
        self.closed = True


class _Shared:
    def __init__(self, upstream: _Upstream) -> None:
        self.upstream = upstream
        self.closed = False

    def build_request(self, method, url, json=None, headers=None):
        self.headers = headers
        return httpx.Request(method, url)

    async def send(self, request, stream=False):
        assert stream is True
        return self.upstream

    async def aclose(self):
        self.closed = True


def test_proxy_turn_does_not_close_the_shared_client():
    upstream = _Upstream(200)
    shared = _Shared(upstream)
    app.state.http = shared

    async def scenario():
        response = await _proxy_turn("c1", "chat", "Hello")
        assert isinstance(response, StreamingResponse)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        return body

    body = asyncio.run(scenario())
    assert b"Hi" in body
    assert shared.headers["Accept-Encoding"] == "identity"
    assert upstream.closed is True
    assert shared.closed is False


def test_proxy_turn_error_does_not_close_the_shared_client():
    upstream = _Upstream(502, b'{"error":"harness down"}')
    shared = _Shared(upstream)
    app.state.http = shared

    response = asyncio.run(_proxy_turn("c1", "chat", "Hello"))
    assert response.status_code == 502
    assert upstream.closed is True
    assert shared.closed is False
