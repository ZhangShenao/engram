import json
import logging

import httpx

from engram_contracts.models import CharacterCard, MemoryRecord, VerbatimTurn
from harness_service.context.assembler import assemble_context
from harness_service.context.summary import format_evicted_turns_for_summary
from harness_service.llm.openrouter import create_provider
from harness_service.settings import character_url, conversation_url, memory_url
from harness_service.store import save_inspection

logger = logging.getLogger("engram.harness")

CONTINUE_INSTRUCTION = (
    "Continue the scene from your last line. Add the next beat in character. "
    "Do not repeat yourself."
)


class TurnError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


async def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        detail = response.text[:300] or "Upstream request failed"
        raise TurnError(response.status_code, detail)
    return response.json()


async def stream_turn(character_id: str, user_id: str, mode: str, message: str):
    async with httpx.AsyncClient(timeout=60) as client:
        character_response = await client.get(f"{character_url()}/characters/{character_id}")
        if character_response.status_code == 404:
            raise TurnError(404, "Character not found")
        character_payload = await _json(character_response)
        character = CharacterCard.model_validate(character_payload["character"])

        session_payload = await _json(
            await client.post(
                f"{conversation_url()}/sessions/ensure",
                json={"characterId": character_id, "userId": user_id},
            )
        )
        session_id = session_payload["sessionId"]

        async def messages() -> list[dict]:
            payload = await _json(
                await client.get(f"{conversation_url()}/sessions/{session_id}/messages")
            )
            return payload["messages"]

        replace_message_id: str | None = None
        if mode == "chat":
            text = (message or "").strip()
            if not text:
                raise TurnError(400, "Message required")
            created = await _json(
                await client.post(
                    f"{conversation_url()}/sessions/{session_id}/messages",
                    json={"role": "user", "content": text},
                )
            )
            user_message_id = created["message"]["id"]
            history = [item for item in await messages() if item["id"] != user_message_id]
            latest = text
            rank_query = text
        elif mode == "regenerate":
            history_all = await messages()
            if not history_all or history_all[-1]["role"] != "assistant":
                raise TurnError(400, "Nothing to regenerate yet.")
            users = [item for item in history_all if item["role"] == "user"]
            if not users:
                raise TurnError(400, "Send a message before regenerating.")
            last_user = users[-1]
            user_index = next(
                index for index, item in enumerate(history_all) if item["id"] == last_user["id"]
            )
            history = history_all[:user_index]
            latest = last_user["content"]
            rank_query = latest
            replace_message_id = history_all[-1]["id"]
        elif mode == "continue":
            history = await messages()
            if not any(item["role"] == "assistant" for item in history):
                raise TurnError(400, "Nothing to continue yet.")
            latest = CONTINUE_INSTRUCTION
            users = [item for item in history if item["role"] == "user"]
            rank_query = users[-1]["content"] if users else latest
        else:
            raise TurnError(400, "Unknown mode")

        summary_payload = await _json(
            await client.get(f"{conversation_url()}/sessions/{session_id}/summary")
        )
        ranked_payload = await _json(
            await client.post(
                f"{memory_url()}/memories/rank",
                json={"characterId": character_id, "userId": user_id, "query": rank_query},
            )
        )
        memories = [MemoryRecord.model_validate(item) for item in ranked_payload["memories"]]
        verbatim = [VerbatimTurn.model_validate(item) for item in history]
        assembled = assemble_context(
            character=character,
            memories=memories,
            summary=summary_payload.get("summary") or "",
            verbatim_turns=verbatim,
            latest_user_message=latest,
            rank_query=rank_query,
        )
        inspector = assembled.model_dump(by_alias=True)
        save_inspection(character_id, user_id, session_id, inspector)
        yield sse({"type": "inspector", "inspector": inspector})

        provider = create_provider()
        parts: list[str] = []
        try:
            async for chunk in provider.iter_chunks(assembled.messages):
                parts.append(chunk)
                yield sse({"type": "chunk", "text": chunk})
            content = "".join(parts).strip()
            if not content:
                yield sse({"type": "error", "message": "The model returned an empty reply."})
                return
            if replace_message_id:
                deleted = await client.delete(
                    f"{conversation_url()}/sessions/{session_id}/messages/{replace_message_id}"
                )
                if deleted.status_code >= 400:
                    raise TurnError(deleted.status_code, "Could not replace the previous reply.")
            saved = await _json(
                await client.post(
                    f"{conversation_url()}/sessions/{session_id}/messages",
                    json={"role": "assistant", "content": content},
                )
            )
            extract_user = "" if mode == "continue" else rank_query
            try:
                await client.post(
                    f"{memory_url()}/memories/extract",
                    json={
                        "characterId": character_id,
                        "userId": user_id,
                        "userMessage": extract_user,
                        "assistantMessage": content,
                        "turnId": saved["message"]["id"],
                    },
                )
            except httpx.HTTPError:
                logger.exception("memory extract request failed")
            if assembled.evicted_turns:
                await client.post(
                    f"{conversation_url()}/sessions/{session_id}/summary/append",
                    json={"text": format_evicted_turns_for_summary(assembled.evicted_turns)},
                )
            yield sse(
                {
                    "type": "done",
                    "messageId": saved["message"]["id"],
                    "content": content,
                    "sessionId": session_id,
                    "provider": provider.name,
                }
            )
        except TurnError as exc:
            yield sse({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001 — surface generation failures on the SSE channel
            logger.exception("turn failed")
            yield sse({"type": "error", "message": str(exc) or "Stream failed"})
