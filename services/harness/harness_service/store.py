import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from harness_service.timeutil import now_iso

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspections (
  seq BIGINT GENERATED ALWAYS AS IDENTITY,
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def database_url() -> str:
    return os.environ.get("HARNESS_DATABASE_URL") or os.environ.get(
        "DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_harness",
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


def save_inspection(character_id: str, user_id: str, session_id: str, payload: dict) -> str:
    inspection_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO inspections
                (id, character_id, user_id, session_id, payload_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                inspection_id,
                character_id,
                user_id,
                session_id,
                json.dumps(payload),
                now_iso(),
            ),
        )
    return inspection_id


def update_inspection(inspection_id: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE inspections SET payload_json = %s WHERE id = %s",
            (json.dumps(payload), inspection_id),
        )


def latest_inspection(character_id: str, user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM inspections
            WHERE character_id = %s AND user_id = %s
            ORDER BY created_at DESC, seq DESC
            LIMIT 1
            """,
            (character_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload_json"])
