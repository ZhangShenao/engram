import asyncio
import logging
import os
from pathlib import Path

import grpc
from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from engram_contracts.models import ChatMessage
from engram_contracts.rpc import engram_pb2, engram_pb2_grpc
from llm_gateway_service.openrouter import OpenRouterProvider, open_llm_client
from llm_gateway_service.router import (
    ProviderFailure,
    StreamBroken,
    json_with_failover,
    stream_with_failover,
)
from llm_gateway_service.scripted import ScriptedLLMProvider

logger = logging.getLogger("engram.llm")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _messages(items) -> list[ChatMessage]:
    return [ChatMessage(role=item.role, content=item.content) for item in items]


def _pins(primary, fallback) -> tuple[tuple[str, str], list[tuple[str, str]]]:
    pin = (primary.provider, primary.model)
    chain = [(item.provider, item.model) for item in fallback]
    return pin, chain


class LlmService(engram_pb2_grpc.LlmServicer):
    def __init__(self, client) -> None:
        self._provider = OpenRouterProvider(client)
        self._scripted = ScriptedLLMProvider()

    async def Check(self, request, context):
        return engram_pb2.HealthResponse(status="ok")

    async def Complete(self, request, context):
        pin, fallback = _pins(request.pin, request.fallback)
        messages = _messages(request.messages)
        temperature = request.temperature or 0.8
        served = None
        try:
            async for text, used in stream_with_failover(
                messages,
                pin,
                fallback,
                temperature=temperature,
                openrouter_stream=self._provider.iter_chunks,
                scripted_stream=self._scripted.iter_chunks,
            ):
                served = used
                yield engram_pb2.CompleteEvent(
                    text=text,
                    served=engram_pb2.ModelPin(provider=used[0], model=used[1]),
                )
        except (ProviderFailure, StreamBroken) as exc:
            yield engram_pb2.CompleteEvent(error=str(exc), done=True)
            return
        if served is None:
            yield engram_pb2.CompleteEvent(error="The model returned an empty reply.", done=True)
            return
        yield engram_pb2.CompleteEvent(
            done=True,
            served=engram_pb2.ModelPin(provider=served[0], model=served[1]),
        )

    async def CompleteJson(self, request, context):
        pin, fallback = _pins(request.pin, request.fallback)
        try:
            content, served = await json_with_failover(
                _messages(request.messages),
                pin,
                fallback,
                temperature=request.temperature or 0.2,
                openrouter_json=self._provider.complete_text,
            )
        except ProviderFailure as exc:
            return engram_pb2.CompleteJsonResponse(error=str(exc))
        return engram_pb2.CompleteJsonResponse(
            content=content,
            served=engram_pb2.ModelPin(provider=served[0], model=served[1]),
        )


async def serve() -> None:
    port = os.environ.get("LLM_PORT", "18414")
    client = open_llm_client()
    server = grpc.aio.server()
    engram_pb2_grpc.add_LlmServicer_to_server(LlmService(client), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    logger.info("llm-gateway listening on %s", port)
    try:
        await server.wait_for_termination()
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
