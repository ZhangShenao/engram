"""Memory extraction calls the model only through llm-gateway."""

import os

import grpc

from engram_contracts.constants import DEFAULT_MODEL_ID, DEFAULT_PROVIDER
from engram_contracts.rpc import engram_pb2, engram_pb2_grpc

_channel: grpc.aio.Channel | None = None
_stub: engram_pb2_grpc.LlmStub | None = None


def _stub_for() -> engram_pb2_grpc.LlmStub:
    global _channel, _stub
    if _stub is None:
        target = os.environ.get("LLM_TARGET", "127.0.0.1:18414")
        _channel = grpc.aio.insecure_channel(target)
        _stub = engram_pb2_grpc.LlmStub(_channel)
    return _stub


async def aclose() -> None:
    global _channel, _stub
    if _channel is not None:
        await _channel.close()
    _channel = None
    _stub = None


async def complete_json(messages: list[dict], model: str | None = None) -> str:
    request = engram_pb2.CompleteJsonRequest(
        pin=engram_pb2.ModelPin(provider=DEFAULT_PROVIDER, model=model or DEFAULT_MODEL_ID),
        messages=[
            engram_pb2.LlmMessage(role=item["role"], content=item["content"]) for item in messages
        ],
        temperature=0.2,
    )
    try:
        response = await _stub_for().CompleteJson(request, timeout=60)
    except grpc.aio.AioRpcError:
        return "{}"
    if response.error:
        return "{}"
    return response.content or "{}"
