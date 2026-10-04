import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from engram_contracts.models import MemoryRecord, MemoryType
from memory_service.domain.extractor import create_extractor
from memory_service.domain.rank import rank_memories, should_forget
from memory_service.domain.slots import normalize_slot
from memory_service.domain.supersede import find_duplicate_memory, find_superseded_memory
from memory_service.timeutil import now_iso

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  type TEXT NOT NULL,
  text TEXT NOT NULL,
  salience DOUBLE PRECISION NOT NULL,
  slot TEXT,
  source_turn_id TEXT,
  superseded_by_id TEXT,
  deleted_at TEXT,
  forgotten_at TEXT,
  last_reinforced_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discarded_turns (
  source_turn_id TEXT PRIMARY KEY,
  discarded_at TEXT NOT NULL
);
"""


def database_url() -> str:
    return os.environ.get("MEMORY_DATABASE_URL") or os.environ.get(
        "DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_memory",
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
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS forgotten_at TEXT")
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_reinforced_at TEXT")


def row_to_memory(row: dict) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        characterId=row["character_id"],
        userId=row["user_id"],
        type=row["type"],
        text=row["text"],
        salience=float(row["salience"]),
        slot=row["slot"],
        sourceTurnId=row["source_turn_id"],
        supersededById=row["superseded_by_id"],
        deletedAt=row["deleted_at"],
        forgottenAt=row.get("forgotten_at"),
        lastReinforcedAt=row.get("last_reinforced_at"),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def list_memories(character_id: str, user_id: str) -> list[MemoryRecord]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE character_id = %s AND user_id = %s
            ORDER BY updated_at DESC
            """,
            (character_id, user_id),
        ).fetchall()
    return [row_to_memory(row) for row in rows]


def active_memories(character_id: str, user_id: str) -> list[MemoryRecord]:
    return [
        memory
        for memory in list_memories(character_id, user_id)
        if not memory.deleted_at and not memory.superseded_by_id and not memory.forgotten_at
    ]


def get_memory(memory_id: str) -> MemoryRecord | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = %s", (memory_id,)).fetchone()
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
    conn: psycopg.Connection,
) -> MemoryRecord:
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO memories (
          id, character_id, user_id, type, text, salience, slot,
          source_turn_id, superseded_by_id, deleted_at, forgotten_at,
          last_reinforced_at, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, %s, %s)
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
    row = conn.execute("SELECT * FROM memories WHERE id = %s", (memory_id,)).fetchone()
    return row_to_memory(row)


def mark_superseded(conn: psycopg.Connection, memory_id: str, by_id: str) -> None:
    conn.execute(
        "UPDATE memories SET superseded_by_id = %s, updated_at = %s WHERE id = %s",
        (by_id, now_iso(), memory_id),
    )


def _load_existing(conn: psycopg.Connection, character_id: str, user_id: str) -> list[MemoryRecord]:
    return [
        row_to_memory(row)
        for row in conn.execute(
            "SELECT * FROM memories WHERE character_id = %s AND user_id = %s",
            (character_id, user_id),
        ).fetchall()
    ]


def _reinforce_row(conn: psycopg.Connection, memory_id: str, salience: float) -> None:
    conn.execute(
        """
        UPDATE memories
        SET salience = %s, last_reinforced_at = %s, updated_at = %s, forgotten_at = NULL
        WHERE id = %s AND deleted_at IS NULL
        """,
        (min(1.0, salience), now_iso(), now_iso(), memory_id),
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
        tombstone = conn.execute(
            "SELECT source_turn_id FROM discarded_turns WHERE source_turn_id = %s",
            (turn_id,),
        ).fetchone()
        if tombstone is not None:
            return []
        existing = _load_existing(conn, character_id, user_id)
        already = [memory for memory in existing if memory.source_turn_id == turn_id]
        if already:
            return [
                memory
                for memory in already
                if not memory.deleted_at and not memory.superseded_by_id
            ]
        for candidate in candidates:
            text = candidate.text.strip()
            if not text:
                continue
            slot = normalize_slot(candidate.slot, candidate.type, text)
            prepared = candidate.model_copy(update={"text": text, "slot": slot})
            superseded = find_superseded_memory(prepared, existing)
            if superseded is None:
                duplicate = find_duplicate_memory(prepared, existing)
                if duplicate is not None:
                    _reinforce_row(conn, duplicate.id, max(duplicate.salience, prepared.salience))
                    continue
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
                        existing[index] = memory.model_copy(update={"superseded_by_id": memory_id})
                        break
            existing.append(record)
            created.append(record)
    return created


def reinforce_memories(memory_ids: list[str], step: float = 0.05) -> int:
    if not memory_ids:
        return 0
    updated = 0
    with connect() as conn:
        for memory_id in memory_ids:
            current = conn.execute(
                "SELECT salience FROM memories WHERE id = %s AND deleted_at IS NULL",
                (memory_id,),
            ).fetchone()
            if current is None:
                continue
            _reinforce_row(conn, memory_id, float(current["salience"]) + step)
            updated += 1
    return updated


def forget_stale(now_ms: float | None = None) -> int:
    moment = time.time() * 1000 if now_ms is None else now_ms
    forgotten = 0
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND superseded_by_id IS NULL AND forgotten_at IS NULL
            """
        ).fetchall()
        stamp = now_iso()
        for row in rows:
            memory = row_to_memory(row)
            if not should_forget(memory, moment):
                continue
            conn.execute(
                "UPDATE memories SET forgotten_at = %s, updated_at = %s WHERE id = %s",
                (stamp, stamp, memory.id),
            )
            forgotten += 1
    return forgotten


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
            UPDATE memories SET text = %s, type = %s, salience = %s, updated_at = %s
            WHERE id = %s
            """,
            (updated_text, updated_type, updated_salience, now_iso(), memory_id),
        )
    return get_memory(memory_id)


def soft_delete_by_source_turn(source_turn_id: str) -> int:
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO discarded_turns (source_turn_id, discarded_at)
            VALUES (%s, %s)
            ON CONFLICT (source_turn_id) DO NOTHING
            """,
            (source_turn_id, stamp),
        )
        result = conn.execute(
            """
            UPDATE memories
            SET deleted_at = %s, updated_at = %s
            WHERE source_turn_id = %s AND deleted_at IS NULL
            """,
            (stamp, stamp, source_turn_id),
        )
        return result.rowcount


def soft_delete(memory_id: str) -> bool:
    current = get_memory(memory_id)
    if current is None or current.deleted_at:
        return False
    with connect() as conn:
        result = conn.execute(
            "UPDATE memories SET deleted_at = %s, updated_at = %s WHERE id = %s",
            (now_iso(), now_iso(), memory_id),
        )
        return result.rowcount > 0


def delete_for_character(character_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))
