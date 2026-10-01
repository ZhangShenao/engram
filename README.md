# Roleplay Studio

Character-first text roleplay for the web: create character cards, chat with streaming replies, inspect the exact context sent to the model each turn, and manage typed memories locally.

## Requirements

- Node.js 20+
- npm

## Setup

```bash
npm install
```

## Environment (optional LLM)

The app runs fully without credentials using a **scripted local provider** (streaming demo replies, memory extraction, context inspector).

To use an OpenAI-compatible API:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key | _(empty → scripted provider)_ |
| `LLM_BASE_URL` | Chat completions base URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |

Example `.env.local`:

```env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

## Run

```bash
npm run dev
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123).

Data is stored in `data/roleplay.db` (SQLite). Three example characters are seeded on first launch.

## Tests

```bash
npm test
```

Unit tests cover the prompt builder, memory rank/supersede, and context assembler (trim order and persona preservation).

## Demo without an API key

1. Start the dev server and open any seeded character (Lyra, Zero, or Mara).
2. Send a message — replies stream via the scripted provider.
3. Open the **Context** tab to see persona, memories, summary, recent turns, token estimates, and trim log.
4. Say `My name is Alex` then send another message — check **Memory** for a `fact` entry; edit or delete it and confirm it no longer appears in Context on the next turn.
