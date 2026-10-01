import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from engram_contracts.models import MemoryCandidate, MemoryRecord, MemoryType

from memory_service.domain.extractor import create_extractor
from memory_service.domain.rank import rank_memories
from memory_service.domain.slots import infer_memory_slot
from memory_service.domain.supersede import find_superseded_memory
from memory_service.timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  type TEXT NOT NULL,
  text TEXT NOT NULL,
  salience REAL NOT NULL,
  slot TEXT,
  source_turn_id TEXT,
  superseded_by_id TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("SQLITE_PATH", "data/memory.db")


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


def row_to_memory(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        characterId=row["character_id"],
        userId=row["user_id"],
        type=row["type"],
        text=row["text"],
        salience=row["salience"],
        slot=row["slot"],
        sourceTurnId=row["source_turn_id"],
        supersededById=row["superseded_by_id"],
        deletedAt=row["deleted_at"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def list_memories(character_id: str, user_id: str) -> list[MemoryRecord]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE character_id = ? AND user_id = ?
            ORDER BY updated_at DESC
            """,
            (character_id, user_id),
        ).fetchall()
    return [row_to_memory(row) for row in rows]


def active_memories(character_id: str, user_id: str) -> list[MemoryRecord]:
    return [
        memory
        for memory in list_memories(character_id, user_id)
        if not memory.deleted_at and not memory.superseded_by_id
    ]


def get_memory(memory_id: str) -> MemoryRecord | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return row_to_memory(row) if row else None


def insert_memory(
    memory_id: str,
    character_id: str,
    user_id: str,
    memory_type: str,
    text: str,
    salience: float,
    slot: str | None,
    source_turn_id: str | None,
    conn: sqlite3.Connection,
) -> MemoryRecord:
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO memories (
          id, character_id, user_id, type, text, salience, slot,
          source_turn_id, superseded_by_id, deleted_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (
            memory_id,
            character_id,
            user_id,
            memory_type,
            text,
            salience,
            slot,
            source_turn_id,
            stamp,
            stamp,
        ),
    )
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return row_to_memory(row)


def mark_superseded(conn: sqlite3.Connection, memory_id: str, by_id: str) -> None:
    conn.execute(
        "UPDATE memories SET superseded_by_id = ?, updated_at = ? WHERE id = ?",
        (by_id, now_iso(), memory_id),
    )


async def extract_and_store(
    character_id: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: str,
) -> list[MemoryRecord]:
    extractor = create_extractor()
    candidates = await extractor.extract(user_message, assistant_message)
    created: list[MemoryRecord] = []
    with connect() as conn:
        existing = [
            row_to_memory(row)
            for row in conn.execute(
                "SELECT * FROM memories WHERE character_id = ? AND user_id = ?",
                (character_id, user_id),
            ).fetchall()
        ]
        for candidate in candidates:
            text = candidate.text.strip()
            if not text:
                continue
            slot = candidate.slot or infer_memory_slot(candidate.type, text)
            prepared = candidate.model_copy(update={"text": text, "slot": slot})
            superseded = find_superseded_memory(prepared, existing)
            memory_id = str(uuid.uuid4())
            record = insert_memory(
                memory_id,
                character_id,
                user_id,
                prepared.type,
                text,
                prepared.salience,
                slot,
                turn_id,
                conn,
            )
            if superseded is not None:
                mark_superseded(conn, superseded.id, memory_id)
                for index, memory in enumerate(existing):
                    if memory.id == superseded.id:
                        existing[index] = memory.model_copy(
                            update={"superseded_by_id": memory_id}
                        )
                        break
            existing.append(record)
            created.append(record)
    return created


def rank_for_character(character_id: str, user_id: str, query: str) -> list[MemoryRecord]:
    return rank_memories(list_memories(character_id, user_id), query)


def update_memory(
    memory_id: str,
    text: str | None,
    memory_type: MemoryType | None,
    salience: float | None,
) -> MemoryRecord | None:
    current = get_memory(memory_id)
    if current is None or current.deleted_at:
        return None
    updated_text = text if text is not None else current.text
    updated_type = memory_type or current.type
    updated_salience = current.salience if salience is None else salience
    with connect() as conn:
        conn.execute(
            """
            UPDATE memories SET text = ?, type = ?, salience = ?, updated_at = ?
            WHERE id = ?
            """,
            (updated_text, updated_type, updated_salience, now_iso(), memory_id),
        )
    return get_memory(memory_id)


def soft_delete(memory_id: str) -> bool:
    current = get_memory(memory_id)
    if current is None or current.deleted_at:
        return False
    with connect() as conn:
        result = conn.execute(
            "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now_iso(), now_iso(), memory_id),
        )
        return result.rowcount > 0


def delete_for_character(character_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM memories WHERE character_id = ?", (character_id,))
