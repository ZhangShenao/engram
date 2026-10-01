import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from gateway_service.timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_log (
  id TEXT PRIMARY KEY,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("SQLITE_PATH", "data/gateway.db")


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


def log_request(method: str, path: str, status_code: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO request_log (id, method, path, status_code, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), method, path, status_code, now_iso()),
        )
