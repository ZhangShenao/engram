#!/usr/bin/env bash
# Start Engram locally. Does not use port 43123.
#
#   scripts/dev.sh [up]   With a running Docker daemon, build and start the whole stack under
#                         Docker Compose and wait until every container is healthy. Without
#                         Docker, fall back to `local`.
#   scripts/dev.sh local  Run Postgres, the five services, and Next.js as host processes.
#   scripts/dev.sh logs   Follow Compose logs. Extra arguments go to `docker compose logs`.
#   scripts/dev.sh down   Stop the Compose stack. Data stays in the engram-pg volume.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WEB_URL="http://127.0.0.1:18415"
APP_PORTS=(18410 18411 18412 18413 18414 18415)

port_busy() {
  python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0 else 1)" "$1"
}

docker_ready() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

require_docker() {
  if ! docker_ready; then
    echo "Docker with the compose plugin is not available, or the daemon is not running." >&2
    exit 1
  fi
}

compose_postgres_port() {
  docker compose config --format json \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['postgres']['ports'][0]['published'])"
}

compose_up() {
  if [[ -z "$(docker compose ps -q --status running)" ]]; then
    local pg_port port
    pg_port="$(compose_postgres_port)"
    if port_busy "$pg_port"; then
      echo "Port ${pg_port} is already in use. Stop that process, or set POSTGRES_PORT in .env to publish the Compose Postgres elsewhere." >&2
      exit 1
    fi
    for port in "${APP_PORTS[@]}"; do
      if port_busy "$port"; then
        echo "Port ${port} is already in use. Stop that process before running scripts/dev.sh." >&2
        exit 1
      fi
    done
  fi

  echo "Building and starting the Engram stack with Docker Compose..."
  if ! docker compose up -d --build --wait --wait-timeout 300; then
    docker compose ps -a >&2
    echo "The stack did not become healthy. Run: scripts/dev.sh logs" >&2
    exit 1
  fi

  docker compose ps
  echo
  echo "Engram is running at ${WEB_URL}"
  echo "Logs: scripts/dev.sh logs    Stop: scripts/dev.sh down"
}

run_local() {
  export PATH="${HOME}/.local/bin:${PATH}"
  export PYTHONPATH="${ROOT}/packages/engram_contracts:${ROOT}/services/gateway:${ROOT}/services/character:${ROOT}/services/conversation:${ROOT}/services/memory:${ROOT}/services/harness"
  export PYTHONUNBUFFERED=1

  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi

  local pg_port=5432
  if docker_ready; then
    pg_port="$(compose_postgres_port)"
  fi

  export WEB_ORIGIN="${WEB_ORIGIN:-http://127.0.0.1:18415}"
  export GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18410}"
  export CHARACTER_URL="${CHARACTER_URL:-http://127.0.0.1:18411}"
  export CONVERSATION_URL="${CONVERSATION_URL:-http://127.0.0.1:18412}"
  export MEMORY_URL="${MEMORY_URL:-http://127.0.0.1:18413}"
  export HARNESS_URL="${HARNESS_URL:-http://127.0.0.1:18414}"
  export CHARACTER_DATABASE_URL="${CHARACTER_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:${pg_port}/engram_character}"
  export CONVERSATION_DATABASE_URL="${CONVERSATION_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:${pg_port}/engram_conversation}"
  export MEMORY_DATABASE_URL="${MEMORY_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:${pg_port}/engram_memory}"
  export HARNESS_DATABASE_URL="${HARNESS_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:${pg_port}/engram_harness}"
  export GATEWAY_DATABASE_URL="${GATEWAY_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:${pg_port}/engram_gateway}"

  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi
  uv sync --frozen --quiet
  # shellcheck disable=SC1091
  source .venv/bin/activate

  if [[ ! -d web/node_modules ]]; then
    npm --prefix web install
  fi

  mkdir -p logs

  start_postgres

  local port
  for port in "${APP_PORTS[@]}"; do
    if port_busy "$port"; then
      echo "Port ${port} is already in use. Stop that process before running scripts/dev.sh." >&2
      exit 1
    fi
  done

  pids=()
  trap cleanup EXIT INT TERM

  start character python -m uvicorn character_service.main:app --host 0.0.0.0 --port 18411
  start conversation python -m uvicorn conversation_service.main:app --host 0.0.0.0 --port 18412
  start memory python -m uvicorn memory_service.main:app --host 0.0.0.0 --port 18413
  start harness python -m uvicorn harness_service.main:app --host 0.0.0.0 --port 18414

  wait_url "http://127.0.0.1:18411/health"
  wait_url "http://127.0.0.1:18412/health"
  wait_url "http://127.0.0.1:18413/health"
  wait_url "http://127.0.0.1:18414/health"

  start gateway python -m uvicorn gateway_service.main:app --host 0.0.0.0 --port 18410
  wait_url "http://127.0.0.1:18410/health"

  start web env GATEWAY_URL="http://127.0.0.1:18410" npm --prefix web run dev
  wait_url "$WEB_URL"

  echo "Engram is running at ${WEB_URL}"
  wait -n
  echo "A process exited. See logs/." >&2
  exit 1
}

wait_postgres() {
  local attempt
  for attempt in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -p 5432 -q; then
      return 0
    fi
    sleep 0.5
  done
  echo "Postgres did not accept connections on 127.0.0.1:5432." >&2
  exit 1
}

ensure_local_databases() {
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'engram') THEN
    CREATE ROLE engram LOGIN PASSWORD 'engram';
  ELSE
    ALTER ROLE engram WITH LOGIN PASSWORD 'engram';
  END IF;
END
$$;
SQL
  local db
  for db in engram_gateway engram_character engram_conversation engram_memory engram_harness; do
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
      sudo -u postgres createdb -O engram "$db"
    fi
  done
}

start_postgres() {
  if docker_ready; then
    docker compose up -d postgres
    echo "Waiting for Postgres from docker compose..."
    local attempt
    for attempt in $(seq 1 60); do
      if docker compose exec -T postgres pg_isready -U engram -d engram >/dev/null 2>&1; then
        return 0
      fi
      sleep 1
    done
    echo "Postgres container did not accept connections." >&2
    exit 1
  fi

  if ! command -v pg_isready >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-client
  fi
  if command -v service >/dev/null 2>&1; then
    sudo service postgresql start || true
  fi
  if command -v pg_lsclusters >/dev/null 2>&1; then
    local ver name port status rest
    pg_lsclusters --no-header | while read -r ver name port status rest; do
      if [[ "$status" != "online" ]]; then
        sudo pg_ctlcluster "$ver" "$name" start || true
      fi
    done
  fi
  echo "Waiting for local Postgres..."
  wait_postgres
  ensure_local_databases
}

cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}

start() {
  local name="$1"
  shift
  "$@" >"logs/${name}.log" 2>&1 &
  pids+=("$!")
}

wait_url() {
  local url="$1"
  for _ in $(seq 1 50); do
    if curl -sf "$url" >/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  echo "Timed out waiting for ${url}. See logs/." >&2
  exit 1
}

command="${1:-up}"
[[ $# -gt 0 ]] && shift

case "$command" in
  up)
    if docker_ready; then
      compose_up
    else
      echo "Docker is not available. Starting Engram as host processes instead." >&2
      run_local
    fi
    ;;
  local)
    run_local
    ;;
  logs)
    require_docker
    docker compose logs -f "$@"
    ;;
  down)
    require_docker
    docker compose down "$@"
    ;;
  *)
    echo "Usage: scripts/dev.sh [up|local|logs|down]" >&2
    exit 2
    ;;
esac
