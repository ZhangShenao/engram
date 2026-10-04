import asyncio
import json

from context_service.orchestrator import stream_turn, timings_payload
from engram_contracts.models import CharacterCard

CHARACTER = CharacterCard.model_validate(
    {
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
)


class _Llm:
    served_provider = "scripted"
    served_model = "scripted"

    async def iter_chunks(self, messages, pin):
        yield "Fresh line"


class _Queue:
    def __init__(self, phase: list[str]) -> None:
        self.phase = phase

    def publish(self, topic: str, payload: dict) -> None:
        if topic == "memory.extract":
            self.phase.append("extract")


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


def test_chat_overlaps_rank_and_publishes_extract_after_done(monkeypatch):
    session_gate = asyncio.Event()
    rank_gate = asyncio.Event()
    write_gate = asyncio.Event()
    rank_started = asyncio.Event()
    summary_started = asyncio.Event()
    stored: dict = {}
    phase: list[str] = []

    class Transcript:
        async def ensure_session(self, character_id, user_id):
            await session_gate.wait()
            return "s1", True

        async def get_summary(self, session_id):
            summary_started.set()
            return ""

        async def add_message(self, session_id, role, content):
            if role == "user":
                await write_gate.wait()
                return {"id": "u1", "role": role, "content": content}
            return {"id": "a1", "role": role, "content": content}

        async def list_messages(self, session_id):
            return [
                {"id": "g", "role": "assistant", "content": "Welcome."},
                {"id": "u1", "role": "user", "content": "Hello"},
            ]

        async def get_pin(self, session_id):
            return ("openrouter", "anthropic/claude-sonnet-5")

        async def set_pin(self, session_id, provider, model):
            return None

        async def append_summary(self, session_id, text):
            return text

        async def replace_message(self, session_id, message_id, role, content):
            return {"id": "a3", "role": role, "content": content}

    class Memory:
        async def rank(self, character_id, user_id, query):
            assert query == "Hello"
            rank_started.set()
            await rank_gate.wait()
            return []

        async def discard_turn(self, source_turn_id):
            return None

    def save(*_args, **_kwargs):
        return "insp-1"

    def update(inspection_id, payload):
        stored["id"] = inspection_id
        stored["timings"] = payload["timings"]

    monkeypatch.setattr("context_service.orchestrator.save_inspection", save)
    monkeypatch.setattr("context_service.orchestrator.update_inspection", update)

    async def scenario():
        generator = stream_turn(
            CHARACTER,
            "local",
            "chat",
            "Hello",
            transcript=Transcript(),
            memory=Memory(),
            llm=_Llm(),
            queue=_Queue(phase),
        )
        pending = asyncio.create_task(generator.__anext__())
        await asyncio.wait_for(rank_started.wait(), timeout=1)
        assert not session_gate.is_set()
        session_gate.set()
        await asyncio.wait_for(summary_started.wait(), timeout=1)
        assert not rank_gate.is_set()
        rank_gate.set()
        assert not write_gate.is_set()
        write_gate.set()
        chunks = [await pending]
        async for chunk in generator:
            chunks.append(chunk)
            if b'"type": "done"' in chunk:
                phase.append("done")
        return chunks

    events = _events(asyncio.run(scenario()))
    done = next(event for event in events if event["type"] == "done")
    assert done["timings"]["extractMs"] is None
    assert done["provider"] == "scripted"
    assert phase == ["done", "extract"]
    assert stored["id"] == "insp-1"
    assert stored["timings"]["extractMs"] is None
    names = [stage["name"] for stage in stored["timings"]["stages"]]
    assert names[:3] == ["session", "rank", "prefetch"]
    assert "summary" in names
    assert "writeUser" in names
    assert "extract" not in names
    assert "character" not in names
