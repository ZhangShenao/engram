from pathlib import Path

from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from engram_contracts.models import MEMORY_TYPES, MemoryType

from memory_service.store import (
    active_memories,
    delete_for_character,
    extract_and_store,
    init_db,
    rank_for_character,
    soft_delete,
    update_memory,
)

app = FastAPI(title="Engram Memory")
init_db()


class RankBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    user_id: str = Field(default="local", alias="userId")
    query: str = ""


class ExtractBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    user_id: str = Field(alias="userId")
    user_message: str = Field(alias="userMessage")
    assistant_message: str = Field(alias="assistantMessage")
    turn_id: str = Field(alias="turnId")


class MemoryPatch(BaseModel):
    text: str | None = None
    type: MemoryType | None = None
    salience: float | None = None


def dump_memory(memory) -> dict:
    return memory.model_dump(by_alias=True)


@app.get("/health")
def health():
    return {"status": "ok", "service": "memory"}


@app.get("/memories")
def get_memories(characterId: str, userId: str = "local"):
    return {"memories": [dump_memory(item) for item in active_memories(characterId, userId)]}


@app.post("/memories/rank")
def post_rank(body: RankBody):
    ranked = rank_for_character(body.character_id, body.user_id, body.query)
    return {"memories": [dump_memory(item) for item in ranked]}


@app.post("/memories/extract")
async def post_extract(body: ExtractBody):
    created = await extract_and_store(
        body.character_id,
        body.user_id,
        body.user_message,
        body.assistant_message,
        body.turn_id,
    )
    return {"memories": [dump_memory(item) for item in created]}


@app.patch("/memories/{memory_id}")
def patch_memory(memory_id: str, body: MemoryPatch):
    if body.type is not None and body.type not in MEMORY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid memory type")
    if body.salience is not None and not 0 <= body.salience <= 1:
        raise HTTPException(status_code=400, detail="Salience must be between 0 and 1")
    updated = update_memory(memory_id, body.text, body.type, body.salience)
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"memory": dump_memory(updated)}


@app.delete("/memories/{memory_id}")
def remove_memory(memory_id: str):
    if not soft_delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@app.delete("/memories")
def remove_for_character(characterId: str):
    delete_for_character(characterId)
    return {"ok": True}
