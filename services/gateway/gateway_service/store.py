import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from gateway_service.timeutil import now_iso

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_log (
  id TEXT PRIMARY KEY,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
"""


def database_url() -> str:
    return os.environ.get("GATEWAY_DATABASE_URL") or os.environ.get(
        "DATABASE_URL",
        "postgresql://engram:engram@127.0.0.1:5432/engram_gateway",
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


def log_request(method: str, path: str, status_code: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO request_log (id, method, path, status_code, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), method, path, status_code, now_iso()),
        )
