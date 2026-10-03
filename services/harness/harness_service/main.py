from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from harness_service.llm.openrouter import open_llm_client
from harness_service.orchestrator import TurnError, open_internal_client, stream_turn
from harness_service.store import init_db, latest_inspection


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = open_internal_client()
    app.state.llm = open_llm_client()
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.llm.aclose()


app = FastAPI(title="Engram Harness", lifespan=lifespan)
init_db()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class TurnRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    user_id: str = Field(default="local", alias="userId")
    mode: str = "chat"
    message: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "harness"}


@app.post("/turns/stream")
async def turns(body: TurnRequest, request: Request):
    generator = stream_turn(
        body.character_id,
        body.user_id,
        body.mode,
        body.message,
        client=request.app.state.http,
        llm_client=request.app.state.llm,
    )
    try:
        # Surface lookup errors before the response is committed as a stream.
        first = await generator.__anext__()
    except StopAsyncIteration:
        await generator.aclose()
        return JSONResponse({"error": "Empty turn"}, status_code=500)
    except TurnError as exc:
        await generator.aclose()
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    except Exception:
        await generator.aclose()
        raise

    async def rest():
        yield first
        async for chunk in generator:
            yield chunk

    return StreamingResponse(rest(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/inspections/{character_id}")
def get_inspection(character_id: str, userId: str = "local"):
    return {"inspector": latest_inspection(character_id, userId)}
