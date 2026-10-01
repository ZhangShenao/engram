import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from harness_service.timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspections (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("SQLITE_PATH", "data/harness.db")


@contextmanager
def connect():
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
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
        conn.executescript(SCHEMA)


def save_inspection(character_id: str, user_id: str, session_id: str, payload: dict) -> str:
    inspection_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO inspections (id, character_id, user_id, session_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
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


def latest_inspection(character_id: str, user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM inspections
            WHERE character_id = ? AND user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (character_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload_json"])
