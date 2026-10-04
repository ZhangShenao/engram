import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from context_service.context.assembler import assemble_context
from context_service.context.summary import format_evicted_turns_for_summary
from context_service.inspections import get_inspection, save_inspection, update_inspection
from engram_contracts.constants import SCRIPTED_PROVIDER
from engram_contracts.models import CharacterCard, ChatMessage, VerbatimTurn

logger = logging.getLogger("engram.context")
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

STAGE_ORDER = (
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


class TurnError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _elapsed_ms(start: float, end: float) -> int:
    return max(0, int((end - start) * 1000))


async def _span(spans: dict[str, int], name: str, awaitable):
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        spans[name] = _elapsed_ms(started, time.perf_counter())


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
    extra = [{"name": name, "ms": recorded[name]} for name in recorded if name not in STAGE_ORDER]
    return {
        "orchestrationMs": _elapsed_ms(started, orchestration_end),
        "modelFirstTokenMs": recorded.get("modelFirstToken"),
        "modelTotalMs": recorded.get("modelTotal"),
        "extractMs": extract_ms,
        "stages": known + extra,
    }


def stamp_extract(inspection_id: str, extract_ms: int) -> None:
    payload = get_inspection(inspection_id)
    if payload is None:
        return
    timings = dict(payload.get("timings") or {})
    timings["extractMs"] = extract_ms
    stages = [stage for stage in timings.get("stages", []) if stage.get("name") != "extract"]
    stages.append({"name": "extract", "ms": extract_ms})
    timings["stages"] = stages
    payload["timings"] = timings
    update_inspection(inspection_id, payload)


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


async def _prepare_turn(character, user_id, mode, message, spans, transcript, memory):
    character_id = character.id
    if mode == "chat":
        text = (message or "").strip()
        if not text:
            raise TurnError(400, "Message required")
        prefetch_started = time.perf_counter()
        session_task = asyncio.create_task(
            _span(spans, "session", transcript.ensure_session(character_id, user_id))
        )
        rank_task = asyncio.create_task(
            _span(spans, "rank", memory.rank(character_id, user_id, text))
        )
        try:
            session_id, _created = await session_task
        except BaseException:
            await _drop_task(rank_task)
            raise
        summary_task = asyncio.create_task(
            _span(spans, "summary", transcript.get_summary(session_id))
        )
        try:
            memories = await rank_task
        except BaseException:
            await _drop_task(summary_task)
            raise
        spans["prefetch"] = _elapsed_ms(prefetch_started, time.perf_counter())
        context_started = time.perf_counter()
        try:
            created = await _span(
                spans,
                "writeUser",
                transcript.add_message(session_id, "user", text),
            )
            user_message_id = created["id"]

            async def _history():
                messages = await transcript.list_messages(session_id)
                return [item for item in messages if item["id"] != user_message_id]

            history = await _span(spans, "readHistory", _history())
            summary = await summary_task
        except BaseException:
            await _drop_task(summary_task)
            raise
        spans["contextLoad"] = _elapsed_ms(context_started, time.perf_counter())
        return session_id, history, text, text, None, memories, summary

    if mode not in {"regenerate", "continue"}:
        raise TurnError(400, "Unknown mode")

    prefetch_started = time.perf_counter()
    session_id, _created = await _span(
        spans, "session", transcript.ensure_session(character_id, user_id)
    )
    spans["prefetch"] = _elapsed_ms(prefetch_started, time.perf_counter())
    context_started = time.perf_counter()
    summary_task = asyncio.create_task(_span(spans, "summary", transcript.get_summary(session_id)))
    try:
        history_all = await _span(spans, "readHistory", transcript.list_messages(session_id))
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
            _span(spans, "rank", memory.rank(character_id, user_id, rank_query)),
        )
    except BaseException:
        await _drop_task(summary_task)
        raise
    spans["contextLoad"] = _elapsed_ms(context_started, time.perf_counter())
    return session_id, history, latest, rank_query, replace_message_id, memories, summary


def _inspector_payload(assembled) -> dict:
    return assembled.model_dump(by_alias=True, exclude={"packed_memory_ids"})


async def stream_turn(
    character: CharacterCard,
    user_id: str,
    mode: str,
    message: str,
    *,
    transcript,
    memory,
    llm,
    queue,
) -> AsyncIterator[bytes]:
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
        session_id,
        history,
        latest,
        rank_query,
        replace_message_id,
        memories,
        summary,
    ) = await _prepare_turn(character, user_id, mode, message, spans, transcript, memory)
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
    inspector = _inspector_payload(assembled)
    save_started = time.perf_counter()
    inspection_id = save_inspection(character.id, user_id, session_id, inspector)
    spans["saveInspection"] = _elapsed_ms(save_started, time.perf_counter())
    yield sse({"type": "inspector", "inspector": inspector})

    pin = await transcript.get_pin(session_id)
    parts: list[str] = []
    try:
        model_started = time.perf_counter()
        async for chunk in llm.iter_chunks(assembled.messages, pin):
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
            yield sse(
                {
                    "type": "error",
                    "message": "The model returned an empty reply.",
                    "timings": timings,
                }
            )
            return
        if replace_message_id:
            saved = await _span(
                spans,
                "replaceAssistant",
                transcript.replace_message(session_id, replace_message_id, "assistant", content),
            )
            if saved is None:
                raise TurnError(404, "Message not found")
            await _span(spans, "discardMemories", memory.discard_turn(replace_message_id))
        else:
            saved = await _span(
                spans,
                "saveAssistant",
                transcript.add_message(session_id, "assistant", content),
            )
        if assembled.evicted_turns:
            await _span(
                spans,
                "summaryAppend",
                transcript.append_summary(
                    session_id,
                    format_evicted_turns_for_summary(assembled.evicted_turns),
                ),
            )
        served = (
            getattr(llm, "served_provider", SCRIPTED_PROVIDER),
            getattr(llm, "served_model", ""),
        )
        if served[0] and served[0] != SCRIPTED_PROVIDER and served != pin:
            await transcript.set_pin(session_id, served[0], served[1])
        timings = current_timings(None)
        _store_timings(inspection_id, inspector, timings)
        yield sse(
            {
                "type": "done",
                "messageId": saved["id"],
                "content": content,
                "sessionId": session_id,
                "provider": served[0],
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
        yield sse({"type": "error", "message": str(exc) or "Stream failed", "timings": timings})
        return

    extract_user = "" if mode == "continue" else rank_query
    queue.publish(
        "memory.extract",
        {
            "characterId": character.id,
            "userId": user_id,
            "userMessage": extract_user,
            "assistantMessage": content,
            "turnId": saved["id"],
            "inspectionId": inspection_id,
        },
    )
    queue.publish(
        "memory.reinforce",
        {"memoryIds": list(assembled.packed_memory_ids)},
    )
    _log_timings(mode, timings)


# Re-export for callers that annotate messages.
__all__ = [
    "ChatMessage",
    "TurnError",
    "regeneration_context",
    "sse",
    "stamp_extract",
    "stream_turn",
    "timings_payload",
]
