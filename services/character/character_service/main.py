from pathlib import Path

from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

from fastapi import FastAPI, HTTPException

from engram_contracts.models import CharacterInput

from character_service.seed import SEED_CHARACTERS
from character_service.store import (
    count_characters,
    create_character,
    delete_character,
    get_character,
    init_db,
    list_characters,
    update_character,
)

app = FastAPI(title="Engram Character")
init_db()


def dump_character(character):
    return character.model_dump(by_alias=True)


@app.get("/health")
def health():
    return {"status": "ok", "service": "character"}


@app.get("/characters")
def get_all():
    return {"characters": [dump_character(item) for item in list_characters()]}


@app.get("/characters/{character_id}")
def get_one(character_id: str):
    character = get_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"character": dump_character(character)}


@app.post("/characters", status_code=201)
def post_one(payload: CharacterInput):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    character = create_character(payload)
    return {"character": dump_character(character)}


@app.put("/characters/{character_id}")
def put_one(character_id: str, payload: CharacterInput):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    character = update_character(character_id, payload)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"character": dump_character(character)}


@app.delete("/characters/{character_id}")
def remove_one(character_id: str):
    if not delete_character(character_id):
        raise HTTPException(status_code=404, detail="Character not found")
    return {"ok": True}


@app.post("/internal/seed")
def seed():
    if count_characters() == 0:
        for payload in SEED_CHARACTERS:
            create_character(payload)
    return {"characters": [dump_character(item) for item in list_characters()]}
