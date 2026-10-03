# Engram

Engram is an overseas, text-only roleplay chat for the web. You write character cards, talk in a dark full-height shell, and open the exact context and memories that shaped each reply.

The **harness** is Engram’s own roleplay orchestrator. It builds the prompt, keeps the persona and token budget intact, retrieves memory, calls the model, and writes memories plus the rolling summary. Character cards, conversations, and memories are separate services. The browser talks only to the gateway.

Web only. No voice, image generation, accounts, or social feed.

## Service map

| Service | Port | Owns |
|---------|------|------|
| web | 18415 | Next.js UI |
| gateway | 18410 | Public API, seed bootstrap, request log |
| character | 18411 | Character cards (`engram_character`) |
| conversation | 18412 | Sessions, messages, rolling summary (`engram_conversation`) |
| memory | 18413 | Extract, rank, slot supersede, edit/delete (`engram_memory`) |
| harness | 18414 | Context assembly, prompts, model call, inspector snapshots (`engram_harness`) |

Lyra, Zero, and Mara are seeded on an empty character database, with their greetings stored as the first assistant message.

## Run locally

Requirements: Docker with the compose plugin. Without Docker: Python 3.12, Node.js 20+, npm, and PostgreSQL 16.

```bash
./scripts/dev.sh          # build and start the whole stack
./scripts/dev.sh logs     # follow logs; extra args go to `docker compose logs`
./scripts/dev.sh down     # stop; data stays in the engram-pg volume
```

Open [http://127.0.0.1:18415](http://127.0.0.1:18415).

With a running Docker daemon, `./scripts/dev.sh` runs `docker compose up -d --build --wait`. Compose starts `postgres:16`, waits for `pg_isready`, then starts the services in dependency order. The script returns once every container, including the web app, passes its healthcheck. Each service gets its own `DATABASE_URL` on that server. Compose reads `.env` for `OPENROUTER_*`. If another Postgres already listens on 5432, set `POSTGRES_PORT` to publish the Compose Postgres on a different host port.

Without Docker, or with `./scripts/dev.sh local`, the script runs everything as host processes. It loads `.env`, creates `.venv`, installs Python dependencies, and installs the web app if needed. It starts one Postgres server and waits until it accepts connections, then starts all five services plus Next.js with logs in `logs/`. With Docker available it runs only Postgres in Compose. Otherwise it starts the local PostgreSQL cluster, creates the `engram` role, and creates `engram_gateway`, `engram_character`, `engram_conversation`, `engram_memory`, and `engram_harness`. It does not use the old single-process Node server.

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
| `CHARACTER_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_character` | Character cards |
| `CONVERSATION_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_conversation` | Sessions, messages, summary |
| `MEMORY_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_memory` | Memories |
| `HARNESS_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_harness` | Inspector snapshots |
| `GATEWAY_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_gateway` | Request log |

Inside Compose, each container receives `DATABASE_URL` pointed at host `postgres` and its own database. A service uses its `*_DATABASE_URL` when set, and otherwise `DATABASE_URL`.

With a key, chat and memory extraction call OpenRouter and send `HTTP-Referer: https://github.com/ZhangShenao/engram` plus `X-Title: Engram`. Without a key, the UI, memories, and context inspector still run.

## Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Tests cover trim order, persona retention, evicted turns, memory rank, slot supersede, and prompt section order. They do not need a running server or an API key. Leave `OPENROUTER_API_KEY` empty so the scripted provider is used.

## Git workflow

Branch from `main` and open a pull request. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on pushes to `main`. It cancels a run when a newer commit supersedes it. The job starts PostgreSQL 16, creates `engram_gateway`, `engram_character`, `engram_conversation`, `engram_memory`, and `engram_harness` from [`scripts/init-postgres.sql`](scripts/init-postgres.sql), then runs [`scripts/quality_report.py`](scripts/quality_report.py) with those service `DATABASE_URL`s and an empty `OPENROUTER_API_KEY`. That script runs `pytest` and fails the job when statement coverage is under 65% or duplicated lines are over 5%. It then runs `npm ci` and `npm run build` in `web/`. No repository secrets are required. When the job finishes, it updates one quality-report comment on the pull request.

`main` rejects direct pushes, including from admins. Changes land through a pull request, and the `ci` check must pass before merge. The branch must be up to date with `main`.

Never commit `.env`. It is listed in `.gitignore`. Copy `.env.example` for local variables.

## Phase 1 limits

Included: character cards, streaming chat, regenerate, continue, typed memories (`fact`, `relationship`, `promise`, `boundary`, `plot`), slot supersede for `user_name` only, rolling summary of evicted turns, and a context inspector.

Not included: voice, image generation, auth, social feed, native apps, embeddings, group chat, or Kubernetes.

Architecture (Chinese): [docs/architecture.md](docs/architecture.md). One chat turn: [docs/chat-turn.md](docs/chat-turn.md).

Notes for training a local roleplay model on an Apple-silicon Mac, written for this harness: [docs/model-training/README.md](docs/model-training/README.md).
