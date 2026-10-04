import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from chat_service.characters import (
    count_characters,
    get_character,
    init_db,
    list_characters,
    log_request,
    update_character,
)
from chat_service.characters import (
    create_character as insert_character,
)
from chat_service.characters import (
    delete_character as remove_character,
)
from chat_service.rpc import ContextClient, MemoryClient, RpcError
from chat_service.seed import SEED_CHARACTERS
from engram_contracts.constants import LOCAL_USER_ID
from engram_contracts.models import CharacterInput
from engram_contracts.rpc import engram_pb2

logger = logging.getLogger("engram.chat")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _dump(character) -> dict:
    return character.model_dump(by_alias=True)


async def _wait_ready(context: ContextClient, memory: MemoryClient) -> bool:
    for _ in range(40):
        try:
            context_health = await context._stub.Check(engram_pb2.HealthRequest(), timeout=2)
            memory_health = await memory._stub.Check(engram_pb2.HealthRequest(), timeout=2)
            if context_health.status == "ok" and memory_health.status == "ok":
                return True
        except grpc.aio.AioRpcError:
            pass
        await asyncio.sleep(0.25)
    return False


async def bootstrap(context: ContextClient) -> None:
    if not await _wait_ready(context, app.state.memory):
        logger.warning("context or memory service was not ready; skipping seed")
        return
    if count_characters() == 0:
        for payload in SEED_CHARACTERS:
            insert_character(payload)
    for character in list_characters():
        try:
            await context.ensure_greeting(character.id, LOCAL_USER_ID, character.greeting or "")
        except RpcError:
            logger.exception("greeting failed for %s", character.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.context = ContextClient()
    app.state.memory = MemoryClient()
    try:
        await bootstrap(app.state.context)
        yield
    finally:
        await app.state.context.aclose()
        await app.state.memory.aclose()


app = FastAPI(title="Engram Chat", lifespan=lifespan)
init_db()

origins = [
    origin.strip()
    for origin in os.environ.get(
        "WEB_ORIGIN",
        "http://127.0.0.1:18415,http://localhost:18415",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_request(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/health":
        try:
            log_request(request.method, request.url.path, response.status_code)
        except Exception:
            logger.exception("request log failed")
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "chat"}


@app.get("/api/characters")
async def list_character_cards():
    return {"characters": [_dump(item) for item in list_characters()]}


@app.post("/api/characters", status_code=201)
async def post_character(payload: CharacterInput):
    if not payload.name.strip():
        return _error(400, "Name is required")
    character = insert_character(payload)
    try:
        await app.state.context.ensure_greeting(
            character.id, LOCAL_USER_ID, character.greeting or ""
        )
    except RpcError as exc:
        remove_character(character.id)
        return _error(exc.status, exc.message)
    return {"character": _dump(character)}


@app.get("/api/characters/{character_id}")
async def get_character_card(character_id: str):
    character = get_character(character_id)
    if character is None:
        return _error(404, "Character not found")
    return {"character": _dump(character)}


@app.put("/api/characters/{character_id}")
async def put_character(character_id: str, payload: CharacterInput):
    if not payload.name.strip():
        return _error(400, "Name is required")
    character = update_character(character_id, payload)
    if character is None:
        return _error(404, "Character not found")
    return {"character": _dump(character)}


async def delete_character_tree(character_id: str, memory: MemoryClient, context: ContextClient):
    try:
        await memory.delete_character(character_id)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    try:
        await context.delete_character(character_id)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    if not remove_character(character_id):
        return _error(404, "Character not found")
    return {"ok": True}


@app.delete("/api/characters/{character_id}")
async def delete_character_route(character_id: str):
    return await delete_character_tree(character_id, app.state.memory, app.state.context)


@app.get("/api/chats")
async def recent_chats():
    try:
        chats = await app.state.context.list_recent(LOCAL_USER_ID)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    by_id = {item.id: item for item in list_characters()}
    visible = []
    for chat in chats:
        character = by_id.get(chat["characterId"])
        if not character:
            continue
        visible.append(
            {
                "sessionId": chat["sessionId"],
                "characterId": chat["characterId"],
                "name": character.name,
                "tagline": character.tagline or "",
                "lastMessage": chat.get("lastMessage") or "",
                "updatedAt": chat.get("updatedAt"),
            }
        )
    return {"chats": visible}


@app.get("/api/chats/{character_id}")
async def get_chat(character_id: str):
    character = get_character(character_id)
    if character is None:
        return _error(404, "Character not found")
    try:
        chat = await app.state.context.get_chat(character_id, LOCAL_USER_ID)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    return {
        "sessionId": chat["sessionId"],
        "character": _dump(character),
        "messages": chat["messages"],
        "summary": chat["summary"],
    }


async def _proxy_turn(character_id: str, mode: str, message: str):
    character = get_character(character_id)
    if character is None:
        return _error(404, "Character not found")
    started = time.perf_counter()
    try:
        frames = await app.state.context.stream_turn(
            character.model_dump_json(by_alias=True),
            LOCAL_USER_ID,
            mode,
            message,
        )
    except RpcError as exc:
        logger.info(
            "chat turn character=%s mode=%s headers_ms=%s status=%s",
            character_id,
            mode,
            _elapsed_ms(started),
            exc.status,
        )
        return _error(exc.status, exc.message)
    headers_ms = _elapsed_ms(started)

    async def generate_open():
        first_byte_ms: int | None = None
        try:
            async for chunk in frames:
                if first_byte_ms is None:
                    first_byte_ms = _elapsed_ms(started)
                yield chunk
        finally:
            logger.info(
                "chat turn character=%s mode=%s headers_ms=%s first_byte_ms=%s total_ms=%s",
                character_id,
                mode,
                headers_ms,
                first_byte_ms,
                _elapsed_ms(started),
            )

    return StreamingResponse(generate_open(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/chats/{character_id}/stream")
async def stream_chat(character_id: str, request: Request):
    body = await request.json()
    return await _proxy_turn(character_id, "chat", str(body.get("message") or ""))


@app.post("/api/chats/{character_id}/regenerate")
async def regenerate(character_id: str):
    return await _proxy_turn(character_id, "regenerate", "")


@app.post("/api/chats/{character_id}/continue")
async def continue_chat(character_id: str):
    return await _proxy_turn(character_id, "continue", "")


@app.get("/api/memories/{character_id}")
async def list_memories(character_id: str):
    try:
        memories = await app.state.memory.list_memories(character_id, LOCAL_USER_ID)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    return {"memories": memories}


@app.patch("/api/memories/{memory_id}")
async def patch_memory(memory_id: str, request: Request):
    body = await request.json()
    try:
        memory = await app.state.memory.update(memory_id, body)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    return {"memory": memory}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    try:
        await app.state.memory.delete(memory_id)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    return {"ok": True}


@app.get("/api/inspector/{character_id}")
async def inspector(character_id: str):
    try:
        payload = await app.state.context.inspection(character_id, LOCAL_USER_ID)
    except RpcError as exc:
        return _error(exc.status, exc.message)
    return {"inspector": payload}
