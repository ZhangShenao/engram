import asyncio

from engram_contracts.models import ChatMessage
from llm_gateway_service.openrouter import OpenRouterProvider


class _Stream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"Hi"}}]}'
        yield 'data: {"choices":[{"delta":{"content":" there"}}]}'
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _Client:
    def __init__(self) -> None:
        self.headers = None
        self.payload = None

    def stream(self, _method, _url, headers=None, json=None):
        self.headers = headers
        self.payload = json
        return _Stream()


async def _collect(provider: OpenRouterProvider) -> list[str]:
    return [
        chunk async for chunk in provider.iter_chunks([ChatMessage(role="user", content="Hello")])
    ]


def test_chat_stream_is_not_gzip_compressed_and_prefers_low_latency():
    client = _Client()
    provider = OpenRouterProvider(client)
    chunks = asyncio.run(_collect(provider))
    assert chunks == ["Hi", " there"]
    assert client.headers["Accept-Encoding"] == "identity"
    assert client.headers["Accept"] == "text/event-stream"
    assert client.payload["stream"] is True
    assert client.payload["provider"] == {"sort": "latency"}
