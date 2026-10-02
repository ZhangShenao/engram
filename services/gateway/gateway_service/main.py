import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from engram_contracts.constants import LOCAL_USER_ID
from engram_contracts.models import CharacterInput

from gateway_service.store import init_db, log_request

logger = logging.getLogger("engram.gateway")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def env_url(name: str, default: str) -> str:
    return os.environ.get(name, default).rstrip("/")


def character_url() -> str:
    return env_url("CHARACTER_URL", "http://127.0.0.1:18411")


def conversation_url() -> str:
    return env_url("CONVERSATION_URL", "http://127.0.0.1:18412")


def memory_url() -> str:
    return env_url("MEMORY_URL", "http://127.0.0.1:18413")


def harness_url() -> str:
    return env_url("HARNESS_URL", "http://127.0.0.1:18414")


async def bootstrap() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        ready = False
        for _ in range(40):
            try:
                character_health = await client.get(f"{character_url()}/health")
                conversation_health = await client.get(f"{conversation_url()}/health")
                if character_health.status_code == 200 and conversation_health.status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                ready = False
            await asyncio.sleep(0.25)
        if not ready:
            logger.warning("character or conversation service was not ready; skipping seed")
            return
        seeded = await client.post(f"{character_url()}/internal/seed")
        seeded.raise_for_status()
        for character in seeded.json().get("characters", []):
            await client.post(
                f"{conversation_url()}/internal/ensure-greeting",
                json={
                    "characterId": character["id"],
                    "userId": LOCAL_USER_ID,
                    "greeting": character.get("greeting") or "",
                },
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bootstrap()
    yield


app = FastAPI(title="Engram Gateway", lifespan=lifespan)
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
    return {"status": "ok", "service": "gateway"}


def _proxy_error(response: httpx.Response) -> JSONResponse:
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload and "error" not in payload:
            payload = {"error": payload["detail"] if isinstance(payload["detail"], str) else payload["detail"]}
    except Exception:
        payload = {"error": response.text[:300] or "Request failed"}
    return JSONResponse(payload, status_code=response.status_code)


@app.get("/api/characters")
async def list_characters():
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{character_url()}/characters")
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.post("/api/characters", status_code=201)
async def create_character(payload: CharacterInput):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{character_url()}/characters",
            json=payload.model_dump(by_alias=True),
        )
        if response.status_code >= 400:
            return _proxy_error(response)
        body = response.json()
        character = body["character"]
        await client.post(
            f"{conversation_url()}/internal/ensure-greeting",
            json={
                "characterId": character["id"],
                "userId": LOCAL_USER_ID,
                "greeting": character.get("greeting") or "",
            },
        )
    return body


@app.get("/api/characters/{character_id}")
async def get_character(character_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{character_url()}/characters/{character_id}")
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.put("/api/characters/{character_id}")
async def update_character(character_id: str, payload: CharacterInput):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.put(
            f"{character_url()}/characters/{character_id}",
            json=payload.model_dump(by_alias=True),
        )
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.delete("/api/characters/{character_id}")
async def delete_character(character_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.delete(f"{memory_url()}/memories", params={"characterId": character_id})
        await client.delete(f"{conversation_url()}/sessions/by-character/{character_id}")
        response = await client.delete(f"{character_url()}/characters/{character_id}")
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.get("/api/chats")
async def recent_chats():
    async with httpx.AsyncClient(timeout=30) as client:
        chats_response = await client.get(
            f"{conversation_url()}/sessions/recent",
            params={"userId": LOCAL_USER_ID},
        )
        characters_response = await client.get(f"{character_url()}/characters")
    if chats_response.status_code >= 400:
        return _proxy_error(chats_response)
    if characters_response.status_code >= 400:
        return _proxy_error(characters_response)
    by_id = {item["id"]: item for item in characters_response.json().get("characters", [])}
    chats = []
    for chat in chats_response.json().get("chats", []):
        character = by_id.get(chat["characterId"])
        if not character:
            continue
        chats.append(
            {
                "sessionId": chat["sessionId"],
                "characterId": chat["characterId"],
                "name": character["name"],
                "tagline": character.get("tagline") or "",
                "lastMessage": chat.get("lastMessage") or "",
                "updatedAt": chat.get("updatedAt"),
            }
        )
    return {"chats": chats}


@app.get("/api/chats/{character_id}")
async def get_chat(character_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        character_response = await client.get(f"{character_url()}/characters/{character_id}")
        if character_response.status_code >= 400:
            return _proxy_error(character_response)
        session_response = await client.post(
            f"{conversation_url()}/sessions/ensure",
            json={"characterId": character_id, "userId": LOCAL_USER_ID},
        )
        if session_response.status_code >= 400:
            return _proxy_error(session_response)
        session_id = session_response.json()["sessionId"]
        messages_response = await client.get(
            f"{conversation_url()}/sessions/{session_id}/messages"
        )
        summary_response = await client.get(
            f"{conversation_url()}/sessions/{session_id}/summary"
        )
    if messages_response.status_code >= 400:
        return _proxy_error(messages_response)
    return {
        "sessionId": session_id,
        "character": character_response.json()["character"],
        "messages": messages_response.json().get("messages", []),
        "summary": summary_response.json().get("summary", ""),
    }


async def _proxy_turn(character_id: str, mode: str, message: str):
    payload = {
        "characterId": character_id,
        "userId": LOCAL_USER_ID,
        "mode": mode,
        "message": message,
    }

    # Peek at the upstream status so a JSON error is not mislabeled as SSE.
    client = httpx.AsyncClient(timeout=None)
    request = client.build_request("POST", f"{harness_url()}/turns/stream", json=payload)
    response = await client.send(request, stream=True)
    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        return Response(content=body, status_code=response.status_code, media_type="application/json")

    async def generate_open():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

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
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{memory_url()}/memories",
            params={"characterId": character_id, "userId": LOCAL_USER_ID},
        )
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.patch("/api/memories/{memory_id}")
async def patch_memory(memory_id: str, request: Request):
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(f"{memory_url()}/memories/{memory_id}", json=body)
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(f"{memory_url()}/memories/{memory_id}")
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()


@app.get("/api/inspector/{character_id}")
async def inspector(character_id: str):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{harness_url()}/inspections/{character_id}",
            params={"userId": LOCAL_USER_ID},
        )
    if response.status_code >= 400:
        return _proxy_error(response)
    return response.json()
