import asyncio
import json

import httpx

from harness_service.orchestrator import CONTINUE_INSTRUCTION, regeneration_context, stream_turn


def test_regenerating_a_reply_drops_back_to_the_user_turn():
    history = [
        {"id": "g", "role": "assistant", "content": "Welcome."},
        {"id": "u", "role": "user", "content": "Hello"},
        {"id": "a", "role": "assistant", "content": "Reply"},
    ]
    kept, latest, query, replace_id = regeneration_context(history)
    assert [item["id"] for item in kept] == ["g"]
    assert latest == "Hello"
    assert query == "Hello"
    assert replace_id == "a"


def test_regenerating_a_continuation_keeps_the_earlier_assistant_reply():
    history = [
        {"id": "u", "role": "user", "content": "Hello"},
        {"id": "a1", "role": "assistant", "content": "The first reply stays."},
        {"id": "a2", "role": "assistant", "content": "The continuation goes."},
    ]
    kept, latest, query, replace_id = regeneration_context(history)
    assert [item["id"] for item in kept] == ["u", "a1"]
    assert latest == CONTINUE_INSTRUCTION
    assert query == "Hello"
    assert replace_id == "a2"


CHARACTER = {
    "id": "c1",
    "name": "Lyra",
    "tagline": "Mage",
    "description": "A mage",
    "personality": "Wise",
    "scenario": "Tower",
    "exampleDialogues": [],
    "greeting": "Welcome.",
    "speechStyle": "",
    "boundaries": "Never OOC.",
    "createdAt": "2026-01-01T00:00:00.000Z",
    "updatedAt": "2026-01-01T00:00:00.000Z",
}

CONTINUATION = [
    {"id": "u1", "role": "user", "content": "Tell me a secret.", "createdAt": "t1"},
    {"id": "a1", "role": "assistant", "content": "The first reply stays.", "createdAt": "t2"},
    {"id": "a2", "role": "assistant", "content": "The continuation goes.", "createdAt": "t3"},
]


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Provider:
    name = "scripted"

    def __init__(self) -> None:
        self.messages = None

    async def iter_chunks(self, messages):
        self.messages = messages
        yield "Fresh line"


def _events(chunks: list[bytes]) -> list[dict]:
    parsed = []
    for chunk in chunks:
        for line in chunk.decode().splitlines():
            if line.startswith("data:"):
                parsed.append(json.loads(line[5:].strip()))
    return parsed


def _run_regenerate(monkeypatch, messages, *, fail_replace=False, fail_discard=False):
    calls: list[tuple] = []
    provider = _Provider()

    def respond(method: str, url: str, body: dict | None = None):
        if method == "GET" and url.rstrip("/").endswith("/characters/c1"):
            return _Response(200, {"character": CHARACTER})
        if method == "POST" and url.rstrip("/").endswith("/sessions/ensure"):
            return _Response(200, {"sessionId": "s1", "created": False})
        if method == "GET" and url.rstrip("/").endswith("/sessions/s1/messages"):
            return _Response(200, {"messages": messages})
        if method == "GET" and url.rstrip("/").endswith("/sessions/s1/summary"):
            return _Response(200, {"summary": ""})
        if method == "POST" and url.rstrip("/").endswith("/memories/rank"):
            return _Response(200, {"memories": []})
        if method == "POST" and url.rstrip("/").endswith("/replace"):
            if fail_replace:
                return _Response(500, {"detail": "db down"}, text="db down")
            return _Response(
                201,
                {
                    "message": {
                        "id": "a3",
                        "role": "assistant",
                        "content": (body or {}).get("content", ""),
                        "createdAt": "t4",
                    }
                },
            )
        if method == "POST" and url.rstrip("/").endswith("/memories/discard-turn"):
            if fail_discard:
                return _Response(500, {"detail": "memory down"}, text="memory down")
            return _Response(200, {"ok": True, "discarded": 1})
        if method == "POST" and url.rstrip("/").endswith("/memories/extract"):
            return _Response(200, {"memories": []})
        if method == "POST" and url.rstrip("/").endswith("/summary/append"):
            return _Response(200, {"summary": ""})
        if method == "DELETE":
            return _Response(200, {"ok": True})
        raise AssertionError(f"unexpected {method} {url}")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            calls.append(("GET", url, None))
            return respond("GET", url)

        async def post(self, url, json=None):
            calls.append(("POST", url, json))
            return respond("POST", url, json)

        async def delete(self, url, params=None):
            calls.append(("DELETE", url, params))
            return respond("DELETE", url)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("harness_service.orchestrator.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("harness_service.orchestrator.create_provider", lambda: provider)
    monkeypatch.setattr("harness_service.orchestrator.save_inspection", lambda *args, **kwargs: None)

    async def collect():
        return [chunk async for chunk in stream_turn("c1", "local", "regenerate", "")]

    events = _events(asyncio.run(collect()))
    return calls, events, provider


def test_continuation_regenerate_keeps_the_earlier_reply_and_replaces_atomically(monkeypatch):
    calls, events, provider = _run_regenerate(monkeypatch, CONTINUATION)
    contents = [message.content for message in provider.messages]
    assert any("The first reply stays." in content for content in contents)
    assert all("The continuation goes." not in content for content in contents)
    assert contents[-1] == CONTINUE_INSTRUCTION
    posts = [call for call in calls if call[0] == "POST"]
    replace_at = next(index for index, call in enumerate(posts) if call[1].endswith("/replace"))
    discard_at = next(index for index, call in enumerate(posts) if call[1].endswith("/discard-turn"))
    extract_at = next(index for index, call in enumerate(posts) if call[1].endswith("/extract"))
    assert replace_at < discard_at < extract_at
    assert posts[replace_at][1].endswith("/messages/a2/replace")
    assert posts[discard_at][2] == {"sourceTurnId": "a2"}
    assert not any(call[0] == "DELETE" for call in calls)
    assert events[-1]["type"] == "done"
    assert events[-1]["messageId"] == "a3"


def test_failed_replace_does_not_delete_the_old_reply_or_its_memories(monkeypatch):
    calls, events, _provider = _run_regenerate(monkeypatch, CONTINUATION, fail_replace=True)
    assert events[-1]["type"] == "error"
    assert not any(call[1].endswith("/discard-turn") for call in calls)
    assert not any(call[1].endswith("/extract") for call in calls)
    assert not any(call[0] == "DELETE" for call in calls)


def test_discard_runs_before_extract_and_a_discard_failure_skips_extract(monkeypatch):
    calls, events, _provider = _run_regenerate(monkeypatch, CONTINUATION, fail_discard=True)
    assert any(call[1].endswith("/messages/a2/replace") for call in calls)
    assert any(call[1].endswith("/discard-turn") for call in calls)
    assert not any(call[1].endswith("/extract") for call in calls)
    assert events[-1]["type"] == "error"
    assert not any(call[0] == "DELETE" for call in calls)
