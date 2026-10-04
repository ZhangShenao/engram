import json
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from engram_contracts.timeutil import now_iso

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS mq_messages (
  id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  locked_until TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mq_messages_ready ON mq_messages (topic, available_at);
"""

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def database_url() -> str:
    return os.environ.get(
        "MQ_DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_mq",
    )


def _stamp(moment: datetime | None = None) -> str:
    value = moment or datetime.now(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


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


def publish(topic: str, payload: dict) -> str:
    message_id = str(uuid.uuid4())
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mq_messages (id, topic, payload_json, attempts, available_at, created_at)
            VALUES (%s, %s, %s, 0, %s, %s)
            """,
            (message_id, topic, json.dumps(payload), stamp, stamp),
        )
    return message_id


def claim(topic: str) -> dict | None:
    """Lock one ready message. Returns None when the topic is idle."""
    now = datetime.now(UTC)
    stamp = _stamp(now)
    locked = _stamp(now + timedelta(seconds=LOCK_SECONDS))
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE mq_messages SET
              locked_until = %s,
              attempts = attempts + 1
            WHERE id = (
              SELECT id FROM mq_messages
              WHERE topic = %s
                AND available_at <= %s
                AND (locked_until IS NULL OR locked_until <= %s)
              ORDER BY created_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING id, topic, payload_json, attempts
            """,
            (locked, topic, stamp, stamp),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "topic": row["topic"],
        "payload": json.loads(row["payload_json"]),
        "attempts": row["attempts"],
    }


def ack(message_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM mq_messages WHERE id = %s", (message_id,))


def nack(message_id: str, attempts: int) -> None:
    if attempts >= MAX_ATTEMPTS:
        ack(message_id)
        return
    available = _stamp(datetime.now(UTC) + timedelta(seconds=min(30, attempts * 2)))
    with connect() as conn:
        conn.execute(
            """
            UPDATE mq_messages
            SET locked_until = NULL, available_at = %s
            WHERE id = %s
            """,
            (available, message_id),
        )
