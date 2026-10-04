# Engram

Engram is an overseas, text-only roleplay chat for the web. You write character cards, talk in a dark full-height shell, and open the exact context and memories that shaped each reply.

**context-service** is Engram’s roleplay orchestrator. It owns the transcript, builds the prompt, keeps the persona and token budget intact, retrieves memory, and calls **llm-gateway**. The browser talks only to **chat-service**, which owns character cards and the public HTTP API.

Web only. No voice, image generation, accounts, or social feed.

## Service map

| Service | Port | Owns |
|---------|------|------|
| web | 18415 | Next.js UI |
| chat | 18410 HTTP | Public API, character cards, seed bootstrap, request log (`engram_chat`) |
| context | 18411 gRPC | Sessions, messages, summary, prompt, inspector (`engram_context`) |
| memory | 18413 gRPC | Extract, rank, hierarchical slots, decay, edit/delete (`engram_memory`) |
| llm-gateway | 18414 gRPC | OpenRouter and the scripted provider, session pin, pre-token failover |

Lyra, Zero, and Mara are seeded on an empty character database, with their greetings stored as the first assistant message.

## Run locally

Requirements: Docker with the compose plugin. Without Docker: [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 20+, npm, and PostgreSQL 16. uv installs Python 3.12 itself if it is missing.

```bash
./scripts/dev.sh          # build and start the whole stack
./scripts/dev.sh logs     # follow logs; extra args go to `docker compose logs`
./scripts/dev.sh down     # stop; data stays in the engram-pg volume
```

Open [http://127.0.0.1:18415](http://127.0.0.1:18415).

With a running Docker daemon, `./scripts/dev.sh` runs `docker compose up -d --build --wait`. Compose starts `postgres:16`, waits for `pg_isready`, then starts the services in dependency order. The script returns once every container, including the web app, passes its healthcheck. Each service gets its own `DATABASE_URL` on that server. Compose reads `.env` for `OPENROUTER_*`. If another Postgres already listens on 5432, set `POSTGRES_PORT` to publish the Compose Postgres on a different host port.

Without Docker, or with `./scripts/dev.sh local`, the script runs everything as host processes. It loads `.env`, runs `uv sync --frozen` to create `.venv` from `uv.lock`, and installs the web app if needed. It starts one Postgres server and waits until it accepts connections, then starts chat, context, memory, llm-gateway, and Next.js with logs in `logs/`. With Docker available it runs only Postgres in Compose. Otherwise it starts the local PostgreSQL cluster, creates the `engram` role, and creates `engram_chat`, `engram_context`, `engram_memory`, and `engram_mq`. An existing Compose volume created before this split does not pick up new databases; remove the `engram-pg` volume once so `scripts/init-postgres.sql` runs again.

## Environment

Copy `.env.example` if you want a file. `scripts/dev.sh` and Compose also work with variables exported in the shell.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | empty | Empty uses the scripted streaming provider and the deterministic memory extractor |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-5` | OpenRouter model id. This slug is on the public model list |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Chat Completions base |
| `GATEWAY_URL` | `http://127.0.0.1:18410` | Used by the Next.js proxy; this is chat-service |
| `CONTEXT_TARGET` | `127.0.0.1:18411` | gRPC |
| `MEMORY_TARGET` | `127.0.0.1:18413` | gRPC |
| `LLM_TARGET` | `127.0.0.1:18414` | gRPC |
| `WEB_ORIGIN` | `http://127.0.0.1:18415` | Chat CORS |
| `CHAT_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_chat` | Character cards and request log |
| `CONTEXT_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_context` | Sessions, messages, summary, inspections |
| `MEMORY_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_memory` | Memories |
| `MQ_DATABASE_URL` | `postgresql://engram:engram@127.0.0.1:5432/engram_mq` | Extract and reinforce queue |

Inside Compose, each container receives `DATABASE_URL` pointed at host `postgres` and its own database. A service uses its `*_DATABASE_URL` when set, and otherwise `DATABASE_URL`.

With a key, chat and memory extraction call OpenRouter and send `HTTP-Referer: https://github.com/ZhangShenao/engram` plus `X-Title: Engram`. Without a key, the UI, memories, and context inspector still run.

## Python dependencies

The backend is one uv project. [`pyproject.toml`](pyproject.toml) lists runtime dependencies under `[project]` and dev tools (pytest, ruff, pre-commit) under the `dev` dependency group. [`uv.lock`](uv.lock) pins every version and is committed. [`.python-version`](.python-version) pins Python 3.12.

```bash
uv sync                      # create or update .venv with runtime + dev dependencies
uv add <package>             # add a runtime dependency and update uv.lock
uv add --dev <package>       # add a dev tool
uv lock --upgrade-package <package>   # bump one package
```

Always commit `pyproject.toml` and `uv.lock` together. CI and the Docker image install with `uv sync --frozen`, so a stale lock fails the build instead of resolving silently. The Docker image skips the `dev` group.

## Tests

```bash
uv sync
uv run pytest
```

Tests cover trim order, persona retention, evicted turns, memory rank, slot supersede, and prompt section order. They do not need a running server or an API key. Leave `OPENROUTER_API_KEY` empty so the scripted provider is used.

## Lint and format

Python uses [ruff](https://docs.astral.sh/ruff/) for both lint and formatting, configured in `pyproject.toml` (line length 100, Python 3.12, import sorting included). The web app uses its existing ESLint config.

[`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs these on every `git commit`. Install the hook once per clone (each worktree shares it):

```bash
uv run pre-commit install
```

On commit, the hook fixes whitespace and end-of-file newlines, checks YAML, TOML, and JSON, checks that `uv.lock` matches `pyproject.toml`, runs `ruff check --fix` and `ruff format` on staged Python files, and runs ESLint when files under `web/src` change. If a hook rewrites a file, the commit stops; review the change, `git add` it, and commit again.

```bash
uv run pre-commit run --all-files   # everything, as CI runs it
uv run ruff check --fix .           # lint only
uv run ruff format .                # format only
```

The ESLint hook needs `web/node_modules`; run `npm --prefix web install` first.

## Git workflow

Branch from `main` and open a pull request. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on pushes to `main`. It cancels a run when a newer commit supersedes it. The job starts PostgreSQL 16, creates `engram_chat`, `engram_context`, `engram_memory`, and `engram_mq` from [`scripts/init-postgres.sql`](scripts/init-postgres.sql), installs Python dependencies with `uv sync --frozen` and the web app with `npm ci`, and runs `pre-commit run --all-files`, the same hooks as a local commit. It then runs [`scripts/quality_report.py`](scripts/quality_report.py) with those service `DATABASE_URL`s and an empty `OPENROUTER_API_KEY`. That script runs `pytest` and fails the job when statement coverage is under 65%, duplicated lines are over 5%, or `ruff check` / `ruff format --check` report anything. It then runs `npm run build` in `web/`. No repository secrets are required. When the job finishes, it updates one quality-report comment on the pull request.

`main` rejects direct pushes, including from admins. Changes land through a pull request, and the `ci` check must pass before merge. The branch must be up to date with `main`.

Never commit `.env`. It is listed in `.gitignore`. Copy `.env.example` for local variables.

## Phase 1 limits

Included: character cards, streaming chat, regenerate, continue, typed memories (`fact`, `relationship`, `promise`, `boundary`, `plot`), slot supersede for `user_name` only, rolling summary of evicted turns, and a context inspector.

Not included: voice, image generation, auth, social feed, native apps, embeddings, group chat, or Kubernetes.

Architecture (Chinese): [docs/architecture.md](docs/architecture.md). One chat turn: [docs/chat-turn.md](docs/chat-turn.md).

Notes for training a local roleplay model on an Apple-silicon Mac, written for this harness: [docs/model-training/README.md](docs/model-training/README.md).
