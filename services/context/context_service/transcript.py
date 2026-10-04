import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from engram_contracts.constants import DEFAULT_MODEL_ID, DEFAULT_PROVIDER
from engram_contracts.timeutil import now_iso

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  llm_provider TEXT,
  llm_model TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(character_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  seq BIGINT GENERATED ALWAYS AS IDENTITY,
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_summaries (
  session_id TEXT PRIMARY KEY,
  summary_text TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def database_url() -> str:
    return os.environ.get("CONTEXT_DATABASE_URL") or os.environ.get(
        "DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_context",
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
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS llm_provider TEXT")
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS llm_model TEXT")


def _message(row: dict) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "createdAt": row["created_at"],
    }


def _find_session(conn: psycopg.Connection, character_id: str, user_id: str) -> str | None:
    existing = conn.execute(
        "SELECT id FROM chat_sessions WHERE character_id = %s AND user_id = %s",
        (character_id, user_id),
    ).fetchone()
    return existing["id"] if existing else None


def ensure_session(character_id: str, user_id: str) -> tuple[str, bool]:
    with connect() as conn:
        existing_id = _find_session(conn, character_id, user_id)
        if existing_id:
            return existing_id, False
        session_id = str(uuid.uuid4())
        stamp = now_iso()
        try:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, character_id, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session_id, character_id, user_id, stamp, stamp),
            )
        except UniqueViolation:
            conn.rollback()
            existing_id = _find_session(conn, character_id, user_id)
            if existing_id is None:
                raise
            return existing_id, False
        return session_id, True


def list_messages(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at FROM messages
            WHERE session_id = %s ORDER BY created_at ASC, seq ASC
            """,
            (session_id,),
        ).fetchall()
    return [_message(row) for row in rows]


def add_message(session_id: str, role: str, content: str) -> dict:
    message_id = str(uuid.uuid4())
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (message_id, session_id, role, content, stamp),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
            (stamp, session_id),
        )
    return {"id": message_id, "role": role, "content": content, "createdAt": stamp}


def replace_message(session_id: str, message_id: str, role: str, content: str) -> dict | None:
    """Insert the replacement and delete the old message in one transaction."""
    new_id = str(uuid.uuid4())
    stamp = now_iso()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM messages WHERE id = %s AND session_id = %s",
            (message_id, session_id),
        ).fetchone()
        if not existing:
            return None
        conn.execute(
            """
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (new_id, session_id, role, content, stamp),
        )
        deleted = conn.execute(
            "DELETE FROM messages WHERE id = %s AND session_id = %s",
            (message_id, session_id),
        )
        if deleted.rowcount != 1:
            raise RuntimeError("replaced message disappeared before it could be swapped")
        conn.execute(
            "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
            (stamp, session_id),
        )
    return {"id": new_id, "role": role, "content": content, "createdAt": stamp}


def delete_message(session_id: str, message_id: str) -> bool:
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM messages WHERE id = %s AND session_id = %s",
            (message_id, session_id),
        )
        return result.rowcount > 0


def get_summary(session_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT summary_text FROM session_summaries WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    return row["summary_text"] if row else ""


def append_summary(session_id: str, chunk: str) -> str:
    previous = get_summary(session_id)
    combined = f"{previous}\n{chunk}" if previous else chunk
    trimmed = combined[-4000:] if len(combined) > 4000 else combined
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO session_summaries (session_id, summary_text, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
              summary_text = EXCLUDED.summary_text,
              updated_at = EXCLUDED.updated_at
            """,
            (session_id, trimmed, stamp),
        )
    return trimmed


def recent_sessions(user_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id AS session_id, s.character_id,
              COALESCE(
                (SELECT content FROM messages m
                 WHERE m.session_id = s.id
                 ORDER BY m.created_at DESC, m.seq DESC LIMIT 1),
                ''
              ) AS last_message,
              COALESCE(
                (SELECT created_at FROM messages m
                 WHERE m.session_id = s.id
                 ORDER BY m.created_at DESC, m.seq DESC LIMIT 1),
                s.updated_at
              ) AS updated_at
            FROM chat_sessions s
            WHERE s.user_id = %s
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "sessionId": row["session_id"],
            "characterId": row["character_id"],
            "lastMessage": row["last_message"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def delete_by_character(character_id: str) -> None:
    with connect() as conn:
        sessions = conn.execute(
            "SELECT id FROM chat_sessions WHERE character_id = %s",
            (character_id,),
        ).fetchall()
        ids = [row["id"] for row in sessions]
        for session_id in ids:
            conn.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            conn.execute("DELETE FROM session_summaries WHERE session_id = %s", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE character_id = %s", (character_id,))
        inspections = conn.execute("SELECT to_regclass('public.inspections') AS name").fetchone()
        if inspections and inspections["name"]:
            conn.execute("DELETE FROM inspections WHERE character_id = %s", (character_id,))


def get_pin(session_id: str) -> tuple[str, str]:
    with connect() as conn:
        row = conn.execute(
            "SELECT llm_provider, llm_model FROM chat_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
    if row is None or not row["llm_provider"] or not row["llm_model"]:
        return DEFAULT_PROVIDER, DEFAULT_MODEL_ID
    return row["llm_provider"], row["llm_model"]


def set_pin(session_id: str, provider: str, model: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE chat_sessions
            SET llm_provider = %s, llm_model = %s, updated_at = %s
            WHERE id = %s
            """,
            (provider, model, now_iso(), session_id),
        )


def ensure_greeting(character_id: str, user_id: str, greeting: str) -> tuple[str, bool]:
    session_id, _created = ensure_session(character_id, user_id)
    if list_messages(session_id):
        return session_id, False
    if greeting.strip():
        add_message(session_id, "assistant", greeting)
        return session_id, True
    return session_id, False


def session_exists(session_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id = %s", (session_id,)).fetchone()
    return row is not None
