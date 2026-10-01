import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from conversation_service.timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(character_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
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


def db_path() -> str:
    return os.environ.get("SQLITE_PATH", "data/conversation.db")


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


def _message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "createdAt": row["created_at"],
    }


def ensure_session(character_id: str, user_id: str) -> tuple[str, bool]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM chat_sessions WHERE character_id = ? AND user_id = ?",
            (character_id, user_id),
        ).fetchone()
        if existing:
            return existing["id"], False
        session_id = str(uuid.uuid4())
        stamp = now_iso()
        conn.execute(
            """
            INSERT INTO chat_sessions (id, character_id, user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, character_id, user_id, stamp, stamp),
        )
        return session_id, True


def list_messages(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at FROM messages
            WHERE session_id = ? ORDER BY created_at ASC, rowid ASC
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
            VALUES (?, ?, ?, ?, ?)
            """,
            (message_id, session_id, role, content, stamp),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (stamp, session_id),
        )
    return {"id": message_id, "role": role, "content": content, "createdAt": stamp}


def delete_message(session_id: str, message_id: str) -> bool:
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM messages WHERE id = ? AND session_id = ?",
            (message_id, session_id),
        )
        return result.rowcount > 0


def get_summary(session_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT summary_text FROM session_summaries WHERE session_id = ?",
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
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              summary_text = excluded.summary_text,
              updated_at = excluded.updated_at
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
                 ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1),
                ''
              ) AS last_message,
              COALESCE(
                (SELECT created_at FROM messages m
                 WHERE m.session_id = s.id
                 ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1),
                s.updated_at
              ) AS updated_at
            FROM chat_sessions s
            WHERE s.user_id = ?
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
            "SELECT id FROM chat_sessions WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        ids = [row["id"] for row in sessions]
        for session_id in ids:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE character_id = ?", (character_id,))


def session_exists(session_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None
