"""Pin a session to one provider, and fail over only before the first token."""

from collections.abc import AsyncIterator, Awaitable, Callable

from engram_contracts.constants import DEFAULT_MODEL_ID, DEFAULT_PROVIDER, SCRIPTED_PROVIDER
from engram_contracts.models import ChatMessage

Pin = tuple[str, str]
StreamFn = Callable[[list[ChatMessage], str, float], AsyncIterator[str]]
JsonFn = Callable[[list[ChatMessage], str, float], Awaitable[str]]


class ProviderFailure(Exception):
    """The attempt produced no tokens, so another pin may still serve this turn."""


class StreamBroken(Exception):
    """Tokens were already emitted. The turn fails instead of switching models."""


def has_api_key() -> bool:
    import os

    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def normalize_chain(pin: Pin, fallback: list[Pin]) -> list[Pin]:
    chain: list[Pin] = []
    for provider, model in [pin, *fallback]:
        item = (provider or DEFAULT_PROVIDER, model or DEFAULT_MODEL_ID)
        if item not in chain:
            chain.append(item)
    return chain or [(DEFAULT_PROVIDER, DEFAULT_MODEL_ID)]


async def stream_with_failover(
    messages: list[ChatMessage],
    pin: Pin,
    fallback: list[Pin],
    *,
    temperature: float,
    openrouter_stream: StreamFn,
    scripted_stream: StreamFn,
) -> AsyncIterator[tuple[str, Pin]]:
    """Yield (text, served_pin). Scripted is chosen up front when there is no key."""
    if not has_api_key():
        served = (SCRIPTED_PROVIDER, "scripted")
        async for text in scripted_stream(messages, served[1], temperature):
            yield text, served
        return

    chain = [item for item in normalize_chain(pin, fallback) if item[0] != SCRIPTED_PROVIDER]
    if not chain:
        chain = [(DEFAULT_PROVIDER, DEFAULT_MODEL_ID)]
    last_error: Exception | None = None
    for candidate in chain:
        emitted = False
        try:
            async for text in openrouter_stream(messages, candidate[1], temperature):
                emitted = True
                yield text, candidate
            return
        except Exception as exc:
            last_error = exc
            if emitted:
                raise StreamBroken(str(exc)) from exc
    raise ProviderFailure(str(last_error) if last_error else "no provider available")


async def json_with_failover(
    messages: list[ChatMessage],
    pin: Pin,
    fallback: list[Pin],
    *,
    temperature: float,
    openrouter_json: JsonFn,
) -> tuple[str, Pin]:
    if not has_api_key():
        raise ProviderFailure("scripted provider does not extract JSON")
    chain = [item for item in normalize_chain(pin, fallback) if item[0] != SCRIPTED_PROVIDER]
    last_error: Exception | None = None
    for candidate in chain:
        try:
            content = await openrouter_json(messages, candidate[1], temperature)
            return content, candidate
        except Exception as exc:
            last_error = exc
    raise ProviderFailure(str(last_error) if last_error else "no provider available")
