import asyncio
import json

import httpx

from harness_service.orchestrator import _inflight_extracts, stream_turn, timings_payload

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


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Provider:
    name = "scripted"

    async def iter_chunks(self, messages):
        yield "Fresh line"


def _events(chunks: list[bytes]) -> list[dict]:
    parsed = []
    for chunk in chunks:
        for line in chunk.decode().splitlines():
            if line.startswith("data:"):
                parsed.append(json.loads(line[5:].strip()))
    return parsed


def test_timings_split_orchestration_first_token_and_generation():
    timings = timings_payload(
        started=0.0,
        model_started=0.5,
        first_token_at=0.75,
        model_finished=2.0,
        extract_ms=30,
    )
    assert timings["orchestrationMs"] == 500
    assert timings["modelFirstTokenMs"] == 250
    assert timings["modelTotalMs"] == 1500
    assert timings["extractMs"] == 30
    assert timings["stages"] == [
        {"name": "modelFirstToken", "ms": 250},
        {"name": "modelTotal", "ms": 1500},
        {"name": "extract", "ms": 30},
    ]


def test_chat_overlaps_prefetch_and_extracts_after_done(monkeypatch):
    character_gate = asyncio.Event()
    write_gate = asyncio.Event()
    rank_started = asyncio.Event()
    summary_started = asyncio.Event()
    stored: dict = {}
    phase: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.entered = False

        async def __aenter__(self):
            self.entered = True
            return self

        async def __aexit__(self, *args):
            self.entered = True
            return False

        async def get(self, url, params=None):
            if url.rstrip("/").endswith("/characters/c1"):
                await character_gate.wait()
                return _Response(200, {"character": CHARACTER})
            if url.rstrip("/").endswith("/sessions/s1/summary"):
                summary_started.set()
                return _Response(200, {"summary": ""})
            if url.rstrip("/").endswith("/sessions/s1/messages"):
                return _Response(
                    200,
                    {
                        "messages": [
                            {"id": "g", "role": "assistant", "content": "Welcome."},
                            {"id": "u1", "role": "user", "content": "Hello"},
                        ]
                    },
                )
            raise AssertionError(f"unexpected GET {url}")

        async def post(self, url, json=None):
            if url.rstrip("/").endswith("/memories/rank"):
                rank_started.set()
                assert (json or {}).get("query") == "Hello"
                return _Response(200, {"memories": []})
            if url.rstrip("/").endswith("/sessions/ensure"):
                return _Response(200, {"sessionId": "s1", "created": True})
            if url.rstrip("/").endswith("/sessions/s1/messages"):
                if (json or {}).get("role") == "user":
                    await write_gate.wait()
                    return _Response(
                        201,
                        {"message": {"id": "u1", "role": "user", "content": "Hello"}},
                    )
                return _Response(
                    201,
                    {"message": {"id": "a1", "role": "assistant", "content": "Fresh line"}},
                )
            if url.rstrip("/").endswith("/memories/extract"):
                phase.append("extract")
                return _Response(200, {"memories": []})
            raise AssertionError(f"unexpected POST {url} {json}")

    def save(*_args, **_kwargs):
        return "insp-1"

    def update(inspection_id, payload):
        stored["id"] = inspection_id
        stored["timings"] = payload["timings"]

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("harness_service.orchestrator.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("harness_service.orchestrator.create_provider", lambda *_a, **_k: _Provider())
    monkeypatch.setattr("harness_service.orchestrator.save_inspection", save)
    monkeypatch.setattr("harness_service.orchestrator.update_inspection", update)

    async def scenario():
        generator = stream_turn("c1", "local", "chat", "Hello")
        pending = asyncio.create_task(generator.__anext__())
        await asyncio.wait_for(rank_started.wait(), timeout=1)
        assert not character_gate.is_set()
        character_gate.set()
        await asyncio.wait_for(summary_started.wait(), timeout=1)
        assert not write_gate.is_set()
        write_gate.set()
        chunks = [await pending]
        if b'"type": "done"' in chunks[0]:
            phase.append("done")
        async for chunk in generator:
            chunks.append(chunk)
            if b'"type": "done"' in chunk:
                phase.append("done")
        return chunks

    events = _events(asyncio.run(scenario()))
    done = events[-1]
    assert done["type"] == "done"
    assert done["timings"]["extractMs"] is None
    assert done["timings"]["orchestrationMs"] >= 0
    assert done["timings"]["modelFirstTokenMs"] >= 0
    assert done["timings"]["modelTotalMs"] >= done["timings"]["modelFirstTokenMs"]
    assert phase == ["done", "extract"]
    assert stored["id"] == "insp-1"
    assert stored["timings"]["extractMs"] >= 0
    names = [stage["name"] for stage in stored["timings"]["stages"]]
    assert names == [
        "character",
        "session",
        "rank",
        "prefetch",
        "writeUser",
        "readHistory",
        "summary",
        "contextLoad",
        "assemble",
        "saveInspection",
        "modelFirstToken",
        "modelTotal",
        "saveAssistant",
        "extract",
    ]


def test_stream_turn_keeps_the_provided_client(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("opened a new HTTP client")

    monkeypatch.setattr("harness_service.orchestrator.httpx.AsyncClient", boom)
    monkeypatch.setattr("harness_service.orchestrator.create_provider", lambda *_a, **_k: _Provider())
    monkeypatch.setattr("harness_service.orchestrator.save_inspection", lambda *_a, **_k: None)

    client = _Reusable()
    chunks = asyncio.run(_drain(client))
    assert _events(chunks)[-1]["type"] == "done"
    assert client.closed is False


class _Reusable:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self):
        self.closed = True

    async def get(self, url, params=None):
        if url.rstrip("/").endswith("/characters/c1"):
            return _Response(200, {"character": CHARACTER})
        if url.rstrip("/").endswith("/summary"):
            return _Response(200, {"summary": ""})
        if url.rstrip("/").endswith("/messages"):
            return _Response(
                200,
                {"messages": [{"id": "u1", "role": "user", "content": "Hello"}]},
            )
        raise AssertionError(url)

    async def post(self, url, json=None):
        if url.rstrip("/").endswith("/sessions/ensure"):
            return _Response(200, {"sessionId": "s1", "created": False})
        if url.rstrip("/").endswith("/messages"):
            role = (json or {}).get("role")
            return _Response(201, {"message": {"id": "m1", "role": role, "content": "x"}})
        if url.rstrip("/").endswith("/memories/rank"):
            return _Response(200, {"memories": []})
        if url.rstrip("/").endswith("/memories/extract"):
            return _Response(200, {"memories": []})
        raise AssertionError(url)


async def _drain(client):
    return [chunk async for chunk in stream_turn("c1", "local", "chat", "Hello", client=client)]


def test_turns_route_reuses_lifespan_clients(monkeypatch):
    import harness_service.main as main

    seen: dict = {}

    async def fake_stream(*_args, client=None, llm_client=None):
        seen["client"] = client
        seen["llm"] = llm_client
        yield b'data: {"type": "inspector"}\n\n'

    monkeypatch.setattr(main, "stream_turn", fake_stream)

    async def scenario():
        async with main.app.router.lifespan_context(main.app):
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://harness") as http:
                response = await http.post(
                    "/turns/stream",
                    json={"characterId": "c1", "message": "Hello"},
                )
            assert response.status_code == 200
            assert seen["client"] is main.app.state.http
            assert seen["llm"] is main.app.state.llm
            assert seen["client"].is_closed is False
        assert seen["client"].is_closed is True

    asyncio.run(scenario())


def test_regenerate_discards_only_after_the_replaced_reply_extract(monkeypatch):
    extract_gate = asyncio.Event()
    done_seen = asyncio.Event()
    replace_seen = asyncio.Event()
    order: list[str] = []
    _inflight_extracts.clear()

    class Client:
        async def get(self, url, params=None):
            if url.rstrip("/").endswith("/characters/c1"):
                return _Response(200, {"character": CHARACTER})
            if url.rstrip("/").endswith("/summary"):
                return _Response(200, {"summary": ""})
            if url.rstrip("/").endswith("/messages"):
                return _Response(
                    200,
                    {
                        "messages": [
                            {"id": "u1", "role": "user", "content": "Hello"},
                            {"id": "a2", "role": "assistant", "content": "Old reply"},
                        ]
                    },
                )
            raise AssertionError(url)

        async def post(self, url, json=None):
            path = url.rstrip("/")
            if path.endswith("/memories/extract"):
                order.append("extract-start")
                await extract_gate.wait()
                order.append("extract-end")
                return _Response(200, {"memories": []})
            if path.endswith("/discard-turn"):
                order.append("discard")
                return _Response(200, {"ok": True, "discarded": 1})
            if path.endswith("/messages/a2/replace"):
                order.append("replace")
                replace_seen.set()
                return _Response(
                    201,
                    {"message": {"id": "a3", "role": "assistant", "content": "Fresh line"}},
                )
            if path.endswith("/sessions/ensure"):
                return _Response(200, {"sessionId": "s1", "created": False})
            if path.endswith("/messages"):
                role = (json or {}).get("role")
                message_id = "a2" if role == "assistant" else "u-new"
                return _Response(201, {"message": {"id": message_id, "role": role, "content": "x"}})
            if path.endswith("/memories/rank"):
                return _Response(200, {"memories": []})
            raise AssertionError(url)

    monkeypatch.setattr(
        "harness_service.orchestrator.create_provider", lambda *_a, **_k: _Provider()
    )
    monkeypatch.setattr(
        "harness_service.orchestrator.save_inspection", lambda *_a, **_k: None
    )
    client = Client()

    async def consume_chat():
        async for chunk in stream_turn("c1", "local", "chat", "Hello", client=client):
            if b'"type": "done"' in chunk:
                done_seen.set()

    async def consume_regen():
        return [chunk async for chunk in stream_turn("c1", "local", "regenerate", "", client=client)]

    async def scenario():
        chat_task = asyncio.create_task(consume_chat())
        await asyncio.wait_for(done_seen.wait(), timeout=1)

        async def extract_started():
            while "extract-start" not in order:
                await asyncio.sleep(0)

        await asyncio.wait_for(extract_started(), timeout=1)
        regen_task = asyncio.create_task(consume_regen())
        await asyncio.wait_for(replace_seen.wait(), timeout=1)
        assert "discard" not in order
        extract_gate.set()
        await regen_task
        await chat_task
        assert order.index("extract-end") < order.index("discard")

    asyncio.run(scenario())
