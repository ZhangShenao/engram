# Working on Engram

Engram is a Python harness plus four services, and a Next.js web app. The harness is our roleplay orchestrator, not a third-party product.

## Boundaries

- The browser calls only the gateway (`services/gateway`). Next proxies `/gateway/*` to it.
- `character` owns cards. `conversation` owns sessions, messages, and summary text. `memory` owns extract, rank, slot supersede, and user edits. `harness` owns prompt assembly, the token budget, the model call, and inspector snapshots.
- Services talk over HTTP. They do not open each other’s SQLite files.
- `packages/engram_contracts` is Pydantic shapes and shared constants only. Do not put prompt or ranking algorithms there.

## Where prompts live

- Persona prefix, example anchors, output shape, re-anchor: `services/harness/harness_service/persona/stability.py`
- Section order: `services/harness/harness_service/prompt/templates.py`
- Memory and summary blocks: `services/harness/harness_service/prompt/builder.py`
- Trim order and the message list sent to the model: `services/harness/harness_service/context/assembler.py`
- Model call: `services/harness/harness_service/llm/`
- One chat turn: `services/harness/harness_service/orchestrator.py`

Do not paste system-prompt strings into the gateway or the web app.

## Add a memory slot

1. Add a constant in `services/memory/memory_service/domain/slots.py` (`MEMORY_SLOTS`).
2. Return it from `infer_memory_slot` for the right type and text, or set `slot` on the extractor candidate.
3. `find_superseded_memory` already matches on slot. Same slot supersedes; different slots stay side by side.
4. Teach the deterministic extractor and the LLM extractor prompt about the new slot.
5. Add a pytest: two memories in the slot supersede; an unrelated fact does not.

Phase 1 has one slot, `user_name`.

## Add or change a model

1. Set `OPENROUTER_MODEL` to an id from `https://openrouter.ai/api/v1/models`.
2. The default in `packages/engram_contracts/engram_contracts/constants.py` is `anthropic/claude-sonnet-5`. Change that default only when you mean to change the product default.
3. Keep `HTTP-Referer` and `X-Title: Engram` on both chat and memory-extraction calls.
4. Leave the empty-key path on `ScriptedLLMProvider` and `DeterministicMemoryExtractor`.

## Tests

From the repo root, with the virtualenv activated:

```bash
pytest
```

```bash
./scripts/dev.sh
```

Web: http://127.0.0.1:18415. Do not reuse ports 3000, 5173, 8080, or 43123.
