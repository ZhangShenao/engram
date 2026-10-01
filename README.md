# Engram

**Engram** is an overseas, Character.AI-style **text-only** roleplay chat for the web. Create character cards, stream in-character replies, inspect the exact context sent to the model each turn, and manage typed memories locally. Web only — no native app.

## Requirements

- Node.js 20+
- npm

## Setup

```bash
npm install
```

## Run

```bash
npm run dev
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123).

Data persists in `data/roleplay.db` (SQLite). Three example characters are seeded on first launch.

## Environment (LLM)

Without credentials, Engram uses a **scripted streaming provider** so chat, memory extraction, and the context inspector still work end to end.

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key for chat + LLM memory extraction | _(empty → scripted provider)_ |
| `LLM_BASE_URL` | OpenAI-compatible chat completions base URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |

Example `.env.local`:

```env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

## Tests

```bash
npm test
```

Unit tests cover the prompt builder, memory rank/supersede, and context assembler (trim order, persona preservation, evicted turns).

## Architecture

Product architecture (Chinese, for PO review): [docs/architecture.md](docs/architecture.md).

## Phase 1 scope (limits)

Included: character CRUD, streaming chat, context inspector, memory panel, local SQLite, pluggable LLM + memory extractors.

**Not** in phase 1: voice, image generation, user auth, social feed, native mobile apps, or multi-user cloud sync.

## Demo without an API key

1. Open any seeded character (Lyra, Zero, or Mara).
2. Send a message — replies stream via the scripted provider.
3. Use the **Context** tab to see persona, memories, summary, recent turns, token estimates, and trim log.
4. Say `My name is Alex`, send again — check **Memory** for a `fact`; edit or delete it and confirm it no longer appears in Context on the next turn.
