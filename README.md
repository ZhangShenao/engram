# Engram

Engram is an overseas, text-only roleplay chat for the web. You write character cards, talk in a dark full-height shell, and open the exact context and memories that shaped each reply.

The **harness** is Engram’s own roleplay orchestrator. It builds the prompt, keeps the persona and token budget intact, retrieves memory, calls the model, and writes memories plus the rolling summary. Character cards, conversations, and memories are separate services. The browser talks only to the gateway.

Web only. No voice, image generation, accounts, or social feed.

## Service map

| Service | Port | Owns |
|---------|------|------|
| web | 18415 | Next.js UI |
| gateway | 18410 | Public API, seed bootstrap, request log |
| character | 18411 | Character cards (`data/character.db`) |
| conversation | 18412 | Sessions, messages, rolling summary (`data/conversation.db`) |
| memory | 18413 | Extract, rank, slot supersede, edit/delete (`data/memory.db`) |
| harness | 18414 | Context assembly, prompts, model call, inspector snapshots (`data/harness.db`) |

Lyra, Zero, and Mara are seeded on an empty character database, with their greetings stored as the first assistant message.

## Run locally

Requirements: Python 3.12, Node.js 20+, npm.

```bash
./scripts/dev.sh
```

Open [http://127.0.0.1:18415](http://127.0.0.1:18415).

The script creates `.venv`, installs Python dependencies, installs the web app if needed, and starts all five services plus Next.js. It does not use the old single-process Node server.

## Run with Docker

```bash
docker compose up --build
```

The web app is published on port 18415. SQLite files live in the `engram-data` volume.

## Environment

Copy `.env.example` if you want a file. `scripts/dev.sh` and Compose also work with variables exported in the shell.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | empty | Empty uses the scripted streaming provider and the deterministic memory extractor |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-5` | OpenRouter model id. This slug is on the public model list |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Chat Completions base |
| `CHARACTER_URL` | `http://127.0.0.1:18411` | Internal |
| `CONVERSATION_URL` | `http://127.0.0.1:18412` | Internal |
| `MEMORY_URL` | `http://127.0.0.1:18413` | Internal |
| `HARNESS_URL` | `http://127.0.0.1:18414` | Internal |
| `GATEWAY_URL` | `http://127.0.0.1:18410` | Used by the Next.js proxy |
| `WEB_ORIGIN` | `http://127.0.0.1:18415` | Gateway CORS |
| `SQLITE_PATH` | per service under `data/` | Override the SQLite file |

With a key, chat and memory extraction call OpenRouter and send `HTTP-Referer: https://github.com/ZhangShenao/engram` plus `X-Title: Engram`. Without a key, the UI, memories, and context inspector still run.

## Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Tests cover trim order, persona retention, evicted turns, memory rank, slot supersede, and prompt section order. They do not need a running server or an API key.

## Phase 1 limits

Included: character cards, streaming chat, regenerate, continue, typed memories (`fact`, `relationship`, `promise`, `boundary`, `plot`), slot supersede for `user_name` only, rolling summary of evicted turns, and a context inspector.

Not included: voice, image generation, auth, social feed, native apps, embeddings, group chat, or Kubernetes.

Architecture (Chinese): [docs/architecture.md](docs/architecture.md).
