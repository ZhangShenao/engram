import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from character_service.timeutil import now_iso
from engram_contracts.models import CharacterCard, CharacterInput, ExampleDialogue

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tagline TEXT NOT NULL,
  description TEXT NOT NULL,
  personality TEXT NOT NULL,
  scenario TEXT NOT NULL,
  example_dialogues TEXT NOT NULL,
  greeting TEXT NOT NULL,
  speech_style TEXT NOT NULL,
  boundaries TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def database_url() -> str:
    return os.environ.get("CHARACTER_DATABASE_URL") or os.environ.get(
        "DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_character",
    )


@contextmanager
def connect():
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)


def _dialogues(raw: str) -> list[ExampleDialogue]:
    parsed = json.loads(raw or "[]")
    return [ExampleDialogue.model_validate(item) for item in parsed]


def row_to_character(row: dict) -> CharacterCard:
    return CharacterCard(
        id=row["id"],
        name=row["name"],
        tagline=row["tagline"],
        description=row["description"],
        personality=row["personality"],
        scenario=row["scenario"],
        exampleDialogues=_dialogues(row["example_dialogues"]),
        greeting=row["greeting"],
        speechStyle=row["speech_style"],
        boundaries=row["boundaries"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def list_characters() -> list[CharacterCard]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM characters ORDER BY updated_at DESC").fetchall()
    return [row_to_character(row) for row in rows]


def get_character(character_id: str) -> CharacterCard | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM characters WHERE id = %s", (character_id,)).fetchone()
    return row_to_character(row) if row else None


def count_characters() -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM characters").fetchone()
    return int(row["c"])


def create_character(payload: CharacterInput, character_id: str | None = None) -> CharacterCard:
    new_id = character_id or str(uuid.uuid4())
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO characters (
              id, name, tagline, description, personality, scenario,
              example_dialogues, greeting, speech_style, boundaries, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                new_id,
                payload.name.strip(),
                payload.tagline,
                payload.description,
                payload.personality,
                payload.scenario,
                json.dumps([item.model_dump() for item in payload.example_dialogues]),
                payload.greeting,
                payload.speech_style,
                payload.boundaries,
                stamp,
                stamp,
            ),
        )
    character = get_character(new_id)
    if character is None:
        raise RuntimeError("character insert failed")
    return character


def update_character(character_id: str, payload: CharacterInput) -> CharacterCard | None:
    stamp = now_iso()
    with connect() as conn:
        result = conn.execute(
            """
            UPDATE characters SET
              name=%s, tagline=%s, description=%s, personality=%s, scenario=%s,
              example_dialogues=%s, greeting=%s, speech_style=%s, boundaries=%s, updated_at=%s
            WHERE id=%s
            """,
            (
                payload.name.strip(),
                payload.tagline,
                payload.description,
                payload.personality,
                payload.scenario,
                json.dumps([item.model_dump() for item in payload.example_dialogues]),
                payload.greeting,
                payload.speech_style,
                payload.boundaries,
                stamp,
                character_id,
            ),
        )
        if result.rowcount == 0:
            return None
    return get_character(character_id)


def delete_character(character_id: str) -> bool:
    with connect() as conn:
        result = conn.execute("DELETE FROM characters WHERE id = %s", (character_id,))
        return result.rowcount > 0
