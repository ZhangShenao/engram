import asyncio
import os

from engram_contracts.rpc import engram_pb2
from llm_gateway_service.scripted import ScriptedLLMProvider
from llm_gateway_service.server import LlmService


def test_scripted_provider_streams_without_a_network_call(monkeypatch):
    monkeypatch.setenv("SCRIPTED_CHUNK_DELAY_MS", "0")
    provider = ScriptedLLMProvider()

    async def collect():
        from engram_contracts.models import ChatMessage

        return [
            chunk
            async for chunk in provider.iter_chunks(
                [ChatMessage(role="user", content="Hello from the tower")]
            )
        ]

    chunks = asyncio.run(collect())
    assert "".join(chunks).strip()


def test_gateway_serves_scripted_when_no_key_is_configured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SCRIPTED_CHUNK_DELAY_MS", "0")
    os.environ.pop("OPENROUTER_API_KEY", None)
    service = LlmService(client=None)
    request = engram_pb2.CompleteRequest(
        pin=engram_pb2.ModelPin(provider="openrouter", model="anthropic/claude-sonnet-5"),
        messages=[engram_pb2.LlmMessage(role="user", content="Hello")],
        temperature=0.8,
    )

    async def collect():
        health = await service.Check(engram_pb2.HealthRequest(), None)
        events = [event async for event in service.Complete(request, None)]
        json_reply = await service.CompleteJson(
            engram_pb2.CompleteJsonRequest(
                pin=request.pin,
                messages=list(request.messages),
                temperature=0.2,
            ),
            None,
        )
        return health, events, json_reply

    health, events, json_reply = asyncio.run(collect())
    assert health.status == "ok"
    assert any(event.text for event in events)
    assert events[-1].done is True
    assert events[-1].served.provider == "scripted"
    assert json_reply.error
