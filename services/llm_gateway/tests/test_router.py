import asyncio

import pytest

from engram_contracts.models import ChatMessage
from llm_gateway_service.router import (
    ProviderFailure,
    StreamBroken,
    json_with_failover,
    stream_with_failover,
)


async def _scripted(messages, model, temperature):
    yield "scripted"


async def _fail_open(messages, model, temperature):
    raise RuntimeError(f"down:{model}")
    yield ""


async def _second_open(messages, model, temperature):
    if model == "first":
        raise RuntimeError("down")
    yield "ok"


async def _break_after_token(messages, model, temperature):
    yield "half"
    raise RuntimeError("cut")


def test_without_a_key_the_scripted_provider_is_selected(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def collect():
        served = []
        async for text, pin in stream_with_failover(
            [ChatMessage(role="user", content="Hi")],
            ("openrouter", "anthropic/claude-sonnet-5"),
            [("openrouter", "other")],
            temperature=0.8,
            openrouter_stream=_fail_open,
            scripted_stream=_scripted,
        ):
            served.append((text, pin))
        return served

    assert asyncio.run(collect()) == [("scripted", ("scripted", "scripted"))]


def test_failover_retries_the_whole_turn_before_the_first_token(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    async def collect():
        chunks = []
        async for text, pin in stream_with_failover(
            [ChatMessage(role="user", content="Hi")],
            ("openrouter", "first"),
            [("openrouter", "second")],
            temperature=0.8,
            openrouter_stream=_second_open,
            scripted_stream=_scripted,
        ):
            chunks.append((text, pin))
        return chunks

    assert asyncio.run(collect()) == [("ok", ("openrouter", "second"))]


def test_a_failure_after_the_first_token_does_not_switch_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    async def collect():
        async for _text, _pin in stream_with_failover(
            [ChatMessage(role="user", content="Hi")],
            ("openrouter", "first"),
            [("openrouter", "second")],
            temperature=0.8,
            openrouter_stream=_break_after_token,
            scripted_stream=_scripted,
        ):
            pass

    with pytest.raises(StreamBroken):
        asyncio.run(collect())


def test_json_failover_walks_the_chain(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    async def complete(messages, model, temperature):
        if model == "first":
            raise RuntimeError("down")
        return "{}"

    content, pin = asyncio.run(
        json_with_failover(
            [ChatMessage(role="user", content="Hi")],
            ("openrouter", "first"),
            [("openrouter", "second")],
            temperature=0.2,
            openrouter_json=complete,
        )
    )
    assert content == "{}"
    assert pin == ("openrouter", "second")


def test_json_without_a_key_is_not_a_scripted_failover(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderFailure):
        asyncio.run(
            json_with_failover(
                [ChatMessage(role="user", content="Hi")],
                ("openrouter", "anthropic/claude-sonnet-5"),
                [],
                temperature=0.2,
                openrouter_json=_fail_open,
            )
        )
