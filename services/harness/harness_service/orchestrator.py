import asyncio
import json
import logging
import time

import httpx

from engram_contracts.models import CharacterCard, MemoryRecord, VerbatimTurn
from harness_service.context.assembler import assemble_context
from harness_service.context.summary import format_evicted_turns_for_summary
from harness_service.llm.openrouter import create_provider
from harness_service.settings import character_url, conversation_url, memory_url
from harness_service.store import save_inspection, update_inspection

logger = logging.getLogger("engram.harness")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

CONTINUE_INSTRUCTION = (
    "Continue the scene from your last line. Add the next beat in character. "
    "Do not repeat yourself."
)

HTTP_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

# Assistant message id -> extract still running after `done`. Regenerate must
# wait for this before discard, or the late insert survives the replaced reply.
_inflight_extracts: dict[str, asyncio.Task] = {}


class TurnError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def open_internal_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60, limits=HTTP_LIMITS)


async def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        detail = response.text[:300] or "Upstream request failed"
        raise TurnError(response.status_code, detail)
    return response.json()


def _elapsed_ms(start: float, end: float) -> int:
    return max(0, int((end - start) * 1000))


# Stable order for the context panel and logs. Parallel hops still keep their own duration.
STAGE_ORDER = (
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
    "replaceAssistant",
    "discardMemories",
    "summaryAppend",
    "extract",
)


async def _span(spans: dict[str, int], name: str, awaitable):
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        spans[name] = _elapsed_ms(started, time.perf_counter())


def timings_payload(
    *,
    started: float,
    model_started: float | None,
    first_token_at: float | None,
    model_finished: float | None,
    extract_ms: int | None,
    spans: dict[str, int] | None = None,
) -> dict:
    orchestration_end = model_started if model_started is not None else time.perf_counter()
    recorded = dict(spans or {})
    if model_started is not None and first_token_at is not None:
        recorded["modelFirstToken"] = _elapsed_ms(model_started, first_token_at)
    if model_started is not None and model_finished is not None:
        recorded["modelTotal"] = _elapsed_ms(model_started, model_finished)
    if extract_ms is not None:
        recorded["extract"] = extract_ms
    known = [{"name": name, "ms": recorded[name]} for name in STAGE_ORDER if name in recorded]
    extra = [
        {"name": name, "ms": recorded[name]}
        for name in recorded
        if name not in STAGE_ORDER
    ]
    return {
        "orchestrationMs": _elapsed_ms(started, orchestration_end),
        "modelFirstTokenMs": recorded.get("modelFirstToken"),
        "modelTotalMs": recorded.get("modelTotal"),
        "extractMs": extract_ms,
        "stages": known + extra,
    }


def _log_timings(mode: str, timings: dict) -> None:
    stages = " ".join(f"{stage['name']}={stage['ms']}ms" for stage in timings.get("stages", []))
    logger.info("turn timings mode=%s %s", mode, stages)


def _store_timings(inspection_id: str | None, inspector: dict, timings: dict) -> None:
    if not inspection_id:
        return
    inspector["timings"] = timings
    try:
        update_inspection(inspection_id, inspector)
    except Exception:
        logger.exception("could not store turn timings")


async def _gather_first_error(*awaitables):
    tasks = [asyncio.ensure_future(item) for item in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _drop_task(task: asyncio.Task) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        return


def regeneration_context(history_all: list[dict]) -> tuple[list[dict], str, str, str]:
    """Prompt history, latest line, rank query, and the assistant message to replace.

    A continuation is an assistant message whose predecessor is also assistant.
    Regenerating it keeps that earlier reply and only replaces the last message.
    """
    if not history_all or history_all[-1]["role"] != "assistant":
        raise TurnError(400, "Nothing to regenerate yet.")
    replace_message_id = history_all[-1]["id"]
    previous = history_all[-2] if len(history_all) >= 2 else None
    if previous is not None and previous["role"] == "assistant":
        history = history_all[:-1]
        users = [item for item in history if item["role"] == "user"]
        rank_query = users[-1]["content"] if users else CONTINUE_INSTRUCTION
        return history, CONTINUE_INSTRUCTION, rank_query, replace_message_id
    users = [item for item in history_all if item["role"] == "user"]
    if not users:
        raise TurnError(400, "Send a message before regenerating.")
    last_user = users[-1]
    user_index = next(
        index for index, item in enumerate(history_all) if item["id"] == last_user["id"]
    )
    return history_all[:user_index], last_user["content"], last_user["content"], replace_message_id


async def _load_character(client: httpx.AsyncClient, character_id: str) -> CharacterCard:
    response = await client.get(f"{character_url()}/characters/{character_id}")
    if response.status_code == 404:
        raise TurnError(404, "Character not found")
    payload = await _json(response)
    return CharacterCard.model_validate(payload["character"])


async def _ensure_session(client: httpx.AsyncClient, character_id: str, user_id: str) -> str:
    payload = await _json(
        await client.post(
            f"{conversation_url()}/sessions/ensure",
            json={"characterId": character_id, "userId": user_id},
        )
    )
    return payload["sessionId"]


async def _load_messages(client: httpx.AsyncClient, session_id: str) -> list[dict]:
    payload = await _json(
        await client.get(f"{conversation_url()}/sessions/{session_id}/messages")
    )
    return payload["messages"]


async def _load_summary(client: httpx.AsyncClient, session_id: str) -> str:
    payload = await _json(
        await client.get(f"{conversation_url()}/sessions/{session_id}/summary")
    )
    return payload.get("summary") or ""


async def _rank_memories(
    client: httpx.AsyncClient, character_id: str, user_id: str, query: str
) -> list[MemoryRecord]:
    payload = await _json(
        await client.post(
            f"{memory_url()}/memories/rank",
            json={"characterId": character_id, "userId": user_id, "query": query},
        )
    )
    return [MemoryRecord.model_validate(item) for item in payload["memories"]]


async def _prepare_turn(
    client: httpx.AsyncClient,
    character_id: str,
    user_id: str,
    mode: str,
    message: str,
    spans: dict[str, int],
) -> tuple[CharacterCard, str, list[dict], str, str, str | None, list[MemoryRecord], str]:
    """Load everything the prompt needs. Independent reads run together."""
    if mode == "chat":
        text = (message or "").strip()
        if not text:
            raise TurnError(400, "Message required")
        # Rank only needs the user text, so it overlaps the character and session reads.
        prefetch_started = time.perf_counter()
        character, session_id, memories = await _gather_first_error(
            _span(spans, "character", _load_character(client, character_id)),
            _span(spans, "session", _ensure_session(client, character_id, user_id)),
            _span(spans, "rank", _rank_memories(client, character_id, user_id, text)),
        )
        spans["prefetch"] = _elapsed_ms(prefetch_started, time.perf_counter())
        context_started = time.perf_counter()
        summary_task = asyncio.create_task(
            _span(spans, "summary", _load_summary(client, session_id))
        )
        try:

            async def _write_user():
                return await _json(
                    await client.post(
                        f"{conversation_url()}/sessions/{session_id}/messages",
                        json={"role": "user", "content": text},
                    )
                )

            created = await _span(spans, "writeUser", _write_user())
            user_message_id = created["message"]["id"]

            async def _history():
                return [
                    item
                    for item in await _load_messages(client, session_id)
                    if item["id"] != user_message_id
                ]

            history = await _span(spans, "readHistory", _history())
            summary = await summary_task
        except BaseException:
            await _drop_task(summary_task)
            raise
        spans["contextLoad"] = _elapsed_ms(context_started, time.perf_counter())
        return character, session_id, history, text, text, None, memories, summary

    if mode not in {"regenerate", "continue"}:
        raise TurnError(400, "Unknown mode")

    prefetch_started = time.perf_counter()
    character, session_id = await _gather_first_error(
        _span(spans, "character", _load_character(client, character_id)),
        _span(spans, "session", _ensure_session(client, character_id, user_id)),
    )
    spans["prefetch"] = _elapsed_ms(prefetch_started, time.perf_counter())
    context_started = time.perf_counter()
    summary_task = asyncio.create_task(
        _span(spans, "summary", _load_summary(client, session_id))
    )
    try:
        history_all = await _span(spans, "readHistory", _load_messages(client, session_id))
        if mode == "regenerate":
            history, latest, rank_query, replace_message_id = regeneration_context(history_all)
        else:
            if not any(item["role"] == "assistant" for item in history_all):
                raise TurnError(400, "Nothing to continue yet.")
            history = history_all
            latest = CONTINUE_INSTRUCTION
            users = [item for item in history if item["role"] == "user"]
            rank_query = users[-1]["content"] if users else latest
            replace_message_id = None
        summary, memories = await _gather_first_error(
            summary_task,
            _span(spans, "rank", _rank_memories(client, character_id, user_id, rank_query)),
        )
    except BaseException:
        await _drop_task(summary_task)
        raise
    spans["contextLoad"] = _elapsed_ms(context_started, time.perf_counter())
    return (
        character,
        session_id,
        history,
        latest,
        rank_query,
        replace_message_id,
        memories,
        summary,
    )


async def _extract_quietly(
    client: httpx.AsyncClient,
    *,
    character_id: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: str,
) -> int:
    started = time.perf_counter()
    try:
        await client.post(
            f"{memory_url()}/memories/extract",
            json={
                "characterId": character_id,
                "userId": user_id,
                "userMessage": user_message,
                "assistantMessage": assistant_message,
                "turnId": turn_id,
            },
        )
    except httpx.HTTPError:
        logger.exception("memory extract request failed")
    return _elapsed_ms(started, time.perf_counter())


async def _await_inflight_extract(turn_id: str) -> None:
    task = _inflight_extracts.get(turn_id)
    if task is None:
        return
    try:
        await asyncio.shield(task)
    except Exception:
        logger.exception("in-flight extract failed before discard")


async def _stream_turn(
    character_id: str,
    user_id: str,
    mode: str,
    message: str,
    client: httpx.AsyncClient,
    llm_client: httpx.AsyncClient | None,
):
    started = time.perf_counter()
    model_started: float | None = None
    first_token_at: float | None = None
    model_finished: float | None = None
    inspection_id: str | None = None
    inspector: dict = {}
    spans: dict[str, int] = {}

    def current_timings(extract_ms: int | None) -> dict:
        return timings_payload(
            started=started,
            model_started=model_started,
            first_token_at=first_token_at,
            model_finished=model_finished,
            extract_ms=extract_ms,
            spans=spans,
        )

    (
        character,
        session_id,
        history,
        latest,
        rank_query,
        replace_message_id,
        memories,
        summary,
    ) = await _prepare_turn(client, character_id, user_id, mode, message, spans)
    verbatim = [VerbatimTurn.model_validate(item) for item in history]
    assemble_started = time.perf_counter()
    assembled = assemble_context(
        character=character,
        memories=memories,
        summary=summary,
        verbatim_turns=verbatim,
        latest_user_message=latest,
        rank_query=rank_query,
    )
    spans["assemble"] = _elapsed_ms(assemble_started, time.perf_counter())
    inspector = assembled.model_dump(by_alias=True)
    save_started = time.perf_counter()
    inspection_id = save_inspection(character_id, user_id, session_id, inspector)
    spans["saveInspection"] = _elapsed_ms(save_started, time.perf_counter())
    yield sse({"type": "inspector", "inspector": inspector})

    provider = create_provider(llm_client)
    parts: list[str] = []
    try:
        model_started = time.perf_counter()
        async for chunk in provider.iter_chunks(assembled.messages):
            if first_token_at is None:
                first_token_at = time.perf_counter()
            parts.append(chunk)
            yield sse({"type": "chunk", "text": chunk})
        model_finished = time.perf_counter()
        content = "".join(parts).strip()
        if not content:
            timings = current_timings(None)
            _store_timings(inspection_id, inspector, timings)
            _log_timings(mode, timings)
            yield sse({"type": "error", "message": "The model returned an empty reply.", "timings": timings})
            return
        if replace_message_id:

            async def _replace():
                return await _json(
                    await client.post(
                        f"{conversation_url()}/sessions/{session_id}/messages/{replace_message_id}/replace",
                        json={"role": "assistant", "content": content},
                    )
                )

            async def _discard():
                discarded = await client.post(
                    f"{memory_url()}/memories/discard-turn",
                    json={"sourceTurnId": replace_message_id},
                )
                if discarded.status_code >= 400:
                    raise TurnError(
                        discarded.status_code,
                        "Could not clear memories from the discarded reply.",
                    )
                return discarded

            saved = await _span(spans, "replaceAssistant", _replace())
            await _await_inflight_extract(replace_message_id)
            await _span(spans, "discardMemories", _discard())
        else:

            async def _save_assistant():
                return await _json(
                    await client.post(
                        f"{conversation_url()}/sessions/{session_id}/messages",
                        json={"role": "assistant", "content": content},
                    )
                )

            saved = await _span(spans, "saveAssistant", _save_assistant())
        if assembled.evicted_turns:

            async def _append_summary():
                return await client.post(
                    f"{conversation_url()}/sessions/{session_id}/summary/append",
                    json={"text": format_evicted_turns_for_summary(assembled.evicted_turns)},
                )

            await _span(spans, "summaryAppend", _append_summary())
        timings = current_timings(None)
        _store_timings(inspection_id, inspector, timings)
        # The browser unlocks on this event. Extraction stays on the same
        # response so it still finishes, but it must not sit in front of `done`.
        yield sse(
            {
                "type": "done",
                "messageId": saved["message"]["id"],
                "content": content,
                "sessionId": session_id,
                "provider": provider.name,
                "timings": timings,
            }
        )
    except TurnError as exc:
        timings = current_timings(None)
        _store_timings(inspection_id, inspector, timings)
        _log_timings(mode, timings)
        yield sse({"type": "error", "message": exc.message, "timings": timings})
        return
    except Exception as exc:  # noqa: BLE001 — surface generation failures on the SSE channel
        logger.exception("turn failed")
        timings = current_timings(None)
        _store_timings(inspection_id, inspector, timings)
        _log_timings(mode, timings)
        yield sse(
            {"type": "error", "message": str(exc) or "Stream failed", "timings": timings}
        )
        return

    extract_user = "" if mode == "continue" else rank_query
    turn_id = saved["message"]["id"]
    extract_task = asyncio.create_task(
        _extract_quietly(
            client,
            character_id=character_id,
            user_id=user_id,
            user_message=extract_user,
            assistant_message=content,
            turn_id=turn_id,
        )
    )
    _inflight_extracts[turn_id] = extract_task
    try:
        extract_ms = await extract_task
        timings = current_timings(extract_ms)
        _store_timings(inspection_id, inspector, timings)
        _log_timings(mode, timings)
    except Exception:
        logger.exception("post-turn bookkeeping failed")
    finally:
        if _inflight_extracts.get(turn_id) is extract_task:
            _inflight_extracts.pop(turn_id, None)


async def stream_turn(
    character_id: str,
    user_id: str,
    mode: str,
    message: str,
    client: httpx.AsyncClient | None = None,
    llm_client: httpx.AsyncClient | None = None,
):
    if client is None:
        async with open_internal_client() as owned:
            async for chunk in _stream_turn(
                character_id, user_id, mode, message, owned, llm_client
            ):
                yield chunk
        return
    async for chunk in _stream_turn(character_id, user_id, mode, message, client, llm_client):
        yield chunk
