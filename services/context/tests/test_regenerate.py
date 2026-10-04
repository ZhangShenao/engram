import asyncio
import json

from context_service.orchestrator import (
    CONTINUE_INSTRUCTION,
    TurnError,
    regeneration_context,
    stream_turn,
)
from engram_contracts.models import CharacterCard


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

CONTINUATION = [
    {"id": "u1", "role": "user", "content": "Tell me a secret.", "createdAt": "t1"},
    {"id": "a1", "role": "assistant", "content": "The first reply stays.", "createdAt": "t2"},
    {"id": "a2", "role": "assistant", "content": "The continuation goes.", "createdAt": "t3"},
]


class _Llm:
    served_provider = "scripted"
    served_model = "scripted"

    def __init__(self) -> None:
        self.messages = None

    async def iter_chunks(self, messages, pin):
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
    phase: list[str] = []
    llm = _Llm()

    class Transcript:
        async def ensure_session(self, character_id, user_id):
            return "s1", False

        async def list_messages(self, session_id):
            return messages

        async def get_summary(self, session_id):
            return ""

        async def get_pin(self, session_id):
            return ("openrouter", "anthropic/claude-sonnet-5")

        async def set_pin(self, session_id, provider, model):
            return None

        async def append_summary(self, session_id, text):
            return text

        async def add_message(self, session_id, role, content):
            return {"id": "a-new", "role": role, "content": content}

        async def replace_message(self, session_id, message_id, role, content):
            calls.append(("replace", message_id, content))
            if fail_replace:
                raise TurnError(500, "db down")
            return {"id": "a3", "role": role, "content": content}

    class Memory:
        async def rank(self, character_id, user_id, query):
            return []

        async def discard_turn(self, source_turn_id):
            calls.append(("discard", source_turn_id))
            if fail_discard:
                raise TurnError(502, "Could not clear memories from the discarded reply.")

    class Queue:
        def publish(self, topic, payload):
            calls.append(("publish", topic, payload.get("turnId")))
            if topic == "memory.extract":
                phase.append("extract")

    monkeypatch.setattr(
        "context_service.orchestrator.save_inspection", lambda *args, **kwargs: None
    )

    async def collect():
        chunks = []
        async for chunk in stream_turn(
            CHARACTER,
            "local",
            "regenerate",
            "",
            transcript=Transcript(),
            memory=Memory(),
            llm=llm,
            queue=Queue(),
        ):
            chunks.append(chunk)
            if b'"type": "done"' in chunk:
                phase.append("done")
            if b'"type": "error"' in chunk:
                phase.append("error")
        return chunks

    return calls, _events(asyncio.run(collect())), llm, phase


def test_continuation_regenerate_keeps_the_earlier_reply_and_replaces_atomically(monkeypatch):
    calls, events, llm, phase = _run_regenerate(monkeypatch, CONTINUATION)
    contents = [message.content for message in llm.messages]
    assert any("The first reply stays." in content for content in contents)
    assert all("The continuation goes." not in content for content in contents)
    assert contents[-1] == CONTINUE_INSTRUCTION
    replace_at = next(index for index, call in enumerate(calls) if call[0] == "replace")
    discard_at = next(index for index, call in enumerate(calls) if call[0] == "discard")
    extract_at = next(
        index
        for index, call in enumerate(calls)
        if call[0] == "publish" and call[1] == "memory.extract"
    )
    assert replace_at < discard_at < extract_at
    assert calls[replace_at][1] == "a2"
    assert calls[discard_at][1] == "a2"
    assert events[-1]["type"] == "done"
    assert events[-1]["messageId"] == "a3"
    assert phase.index("done") < phase.index("extract")
    assert events[-1]["timings"]["extractMs"] is None


def test_failed_replace_does_not_delete_the_old_reply_or_its_memories(monkeypatch):
    calls, events, _llm, phase = _run_regenerate(monkeypatch, CONTINUATION, fail_replace=True)
    assert events[-1]["type"] == "error"
    assert not any(call[0] == "discard" for call in calls)
    assert "extract" not in phase


def test_discard_failure_skips_extract(monkeypatch):
    calls, events, _llm, phase = _run_regenerate(monkeypatch, CONTINUATION, fail_discard=True)
    assert any(call[0] == "replace" and call[1] == "a2" for call in calls)
    assert any(call[0] == "discard" for call in calls)
    assert events[-1]["type"] == "error"
    assert "extract" not in phase
