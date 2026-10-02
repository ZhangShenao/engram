#!/usr/bin/env bash
# Start Postgres, the five Engram services, and the Next.js app. Does not use port 43123.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export PYTHONPATH="${ROOT}/packages/engram_contracts:${ROOT}/services/gateway:${ROOT}/services/character:${ROOT}/services/conversation:${ROOT}/services/memory:${ROOT}/services/harness"
export PYTHONUNBUFFERED=1

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export WEB_ORIGIN="${WEB_ORIGIN:-http://127.0.0.1:18415}"
export GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18410}"
export CHARACTER_URL="${CHARACTER_URL:-http://127.0.0.1:18411}"
export CONVERSATION_URL="${CONVERSATION_URL:-http://127.0.0.1:18412}"
export MEMORY_URL="${MEMORY_URL:-http://127.0.0.1:18413}"
export HARNESS_URL="${HARNESS_URL:-http://127.0.0.1:18414}"
export CHARACTER_DATABASE_URL="${CHARACTER_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:5432/engram_character}"
export CONVERSATION_DATABASE_URL="${CONVERSATION_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:5432/engram_conversation}"
export MEMORY_DATABASE_URL="${MEMORY_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:5432/engram_memory}"
export HARNESS_DATABASE_URL="${HARNESS_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:5432/engram_harness}"
export GATEWAY_DATABASE_URL="${GATEWAY_DATABASE_URL:-postgresql://engram:engram@127.0.0.1:5432/engram_gateway}"

if [[ ! -x .venv/bin/python ]]; then
  rm -rf .venv
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r requirements.txt

if [[ ! -d web/node_modules ]]; then
  npm --prefix web install
fi

mkdir -p logs

port_busy() {
  python -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0 else 1)" "$1"
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
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
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
    while read -r ver name port status rest; do
      if [[ "$status" != "online" ]]; then
        sudo pg_ctlcluster "$ver" "$name" start || true
      fi
    done < <(pg_lsclusters --no-header)
  fi
  echo "Waiting for local Postgres..."
  wait_postgres
  ensure_local_databases
}

start_postgres

for port in 18410 18411 18412 18413 18414 18415; do
  if port_busy "$port"; then
    echo "Port ${port} is already in use. Stop that process before running scripts/dev.sh." >&2
    exit 1
  fi
done

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

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
wait_url "http://127.0.0.1:18415"

echo "Engram is running at http://127.0.0.1:18415"
wait -n
echo "A process exited. See logs/." >&2
exit 1
