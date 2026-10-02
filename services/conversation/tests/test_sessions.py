import threading
import uuid
from contextlib import contextmanager

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from conversation_service.main import app
from conversation_service.store import (
    add_message,
    connect,
    database_url,
    delete_by_character,
    ensure_session,
    init_db,
    list_messages,
    replace_message,
)


def test_ensure_session_is_idempotent():
    init_db()
    character_id = f"char-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    try:
        first_id, created = ensure_session(character_id, user_id)
        second_id, created_again = ensure_session(character_id, user_id)
        assert created is True
        assert created_again is False
        assert second_id == first_id
    finally:
        delete_by_character(character_id)


def test_ensure_session_rereads_when_insert_hits_unique_violation(monkeypatch):
    init_db()
    character_id = f"seen-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    winner = str(uuid.uuid4())
    stamp = "2026-01-01T00:00:00.000Z"
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (id, character_id, user_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (winner, character_id, user_id, stamp, stamp),
        )
        conn.commit()

    from conversation_service import store as session_store

    calls = {"n": 0}
    real_find = session_store._find_session

    def hide_the_committed_row_once(conn, character_id: str, user_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_find(conn, character_id, user_id)

    monkeypatch.setattr(session_store, "_find_session", hide_the_committed_row_once)
    try:
        session_id, created = ensure_session(character_id, user_id)
        assert calls["n"] >= 2
        assert session_id == winner
        assert created is False
    finally:
        delete_by_character(character_id)


def test_ensure_session_returns_the_existing_row_after_unique_violation():
    init_db()
    character_id = f"race-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    winner = str(uuid.uuid4())
    stamp = "2026-01-01T00:00:00.000Z"
    started = threading.Event()
    release = threading.Event()
    holder_error: list[BaseException] = []

    def hold_lock() -> None:
        conn = psycopg.connect(database_url(), row_factory=dict_row)
        try:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, character_id, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (winner, character_id, user_id, stamp, stamp),
            )
            started.set()
            release.wait(5)
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — surface the holder failure to the test
            holder_error.append(exc)
            conn.rollback()
            started.set()
        finally:
            conn.close()

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert started.wait(5)
    outcome: dict = {}

    def race() -> None:
        try:
            outcome["value"] = ensure_session(character_id, user_id)
        except BaseException as exc:  # noqa: BLE001 — the assertion reports it
            outcome["error"] = exc

    racer = threading.Thread(target=race)
    racer.start()
    try:
        racer.join(0.3)
        release.set()
        racer.join(5)
        holder.join(5)
        assert holder_error == []
        assert "error" not in outcome
        assert outcome["value"] == (winner, False)
    finally:
        release.set()
        racer.join(5)
        holder.join(5)
        delete_by_character(character_id)


def test_replace_message_swaps_the_reply_and_keeps_the_user_turn():
    init_db()
    character_id = f"char-{uuid.uuid4()}"
    try:
        session_id, _created = ensure_session(character_id, "local")
        user = add_message(session_id, "user", "Hi")
        old = add_message(session_id, "assistant", "Old reply")
        replaced = replace_message(session_id, old["id"], "assistant", "New reply")
        assert replaced is not None
        messages = list_messages(session_id)
        assert [message["content"] for message in messages] == ["Hi", "New reply"]
        assert messages[0]["id"] == user["id"]
        assert messages[1]["id"] == replaced["id"]
        assert old["id"] not in {message["id"] for message in messages}
    finally:
        delete_by_character(character_id)


def test_replace_route_is_atomic_for_callers():
    init_db()
    character_id = f"char-{uuid.uuid4()}"
    try:
        session_id, _created = ensure_session(character_id, "local")
        old = add_message(session_id, "assistant", "Old reply")
        with TestClient(app) as client:
            response = client.post(
                f"/sessions/{session_id}/messages/{old['id']}/replace",
                json={"role": "assistant", "content": "New reply"},
            )
        assert response.status_code == 201
        messages = list_messages(session_id)
        assert [message["content"] for message in messages] == ["New reply"]
        assert messages[0]["id"] == response.json()["message"]["id"]
    finally:
        delete_by_character(character_id)


def test_replace_of_a_missing_message_inserts_nothing():
    init_db()
    character_id = f"char-{uuid.uuid4()}"
    try:
        session_id, _created = ensure_session(character_id, "local")
        add_message(session_id, "user", "Hi")
        before = list_messages(session_id)
        assert replace_message(session_id, "missing", "assistant", "Nope") is None
        assert list_messages(session_id) == before
    finally:
        delete_by_character(character_id)


def test_replace_message_does_not_commit_when_the_delete_fails(monkeypatch):
    events = {"committed": False, "rolled_back": False, "sql": []}

    class Result:
        def __init__(self, row=None, rowcount: int = 1) -> None:
            self._row = row
            self.rowcount = rowcount

        def fetchone(self):
            return self._row

    class Conn:
        def execute(self, sql, params=None):
            events["sql"].append(sql)
            if "DELETE FROM messages" in sql:
                raise RuntimeError("delete failed")
            if "SELECT" in sql:
                return Result({"id": "old"})
            return Result()

    @contextmanager
    def fake_connect():
        conn = Conn()
        try:
            yield conn
            events["committed"] = True
        except Exception:
            events["rolled_back"] = True
            raise

    monkeypatch.setattr("conversation_service.store.connect", fake_connect)
    try:
        replace_message("session", "old", "assistant", "new")
    except RuntimeError as exc:
        assert str(exc) == "delete failed"
    else:
        raise AssertionError("delete failure should abort the replacement")
    assert events["rolled_back"] is True
    assert events["committed"] is False
    script = "\n".join(events["sql"])
    assert script.index("INSERT INTO messages") < script.index("DELETE FROM messages")
