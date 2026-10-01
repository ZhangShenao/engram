#!/usr/bin/env bash
# Start the five Engram services and the Next.js app. Does not use port 43123.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export PYTHONPATH="${ROOT}/packages/engram_contracts:${ROOT}/services/gateway:${ROOT}/services/character:${ROOT}/services/conversation:${ROOT}/services/memory:${ROOT}/services/harness"
export PYTHONUNBUFFERED=1
export WEB_ORIGIN="${WEB_ORIGIN:-http://127.0.0.1:18415}"
export GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18410}"
export CHARACTER_URL="${CHARACTER_URL:-http://127.0.0.1:18411}"
export CONVERSATION_URL="${CONVERSATION_URL:-http://127.0.0.1:18412}"
export MEMORY_URL="${MEMORY_URL:-http://127.0.0.1:18413}"
export HARNESS_URL="${HARNESS_URL:-http://127.0.0.1:18414}"

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

mkdir -p data logs

port_busy() {
  python -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0 else 1)" "$1"
}

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

start character env SQLITE_PATH="${ROOT}/data/character.db" python -m uvicorn character_service.main:app --host 0.0.0.0 --port 18411
start conversation env SQLITE_PATH="${ROOT}/data/conversation.db" python -m uvicorn conversation_service.main:app --host 0.0.0.0 --port 18412
start memory env SQLITE_PATH="${ROOT}/data/memory.db" python -m uvicorn memory_service.main:app --host 0.0.0.0 --port 18413
start harness env SQLITE_PATH="${ROOT}/data/harness.db" python -m uvicorn harness_service.main:app --host 0.0.0.0 --port 18414

wait_url "http://127.0.0.1:18411/health"
wait_url "http://127.0.0.1:18412/health"
wait_url "http://127.0.0.1:18413/health"
wait_url "http://127.0.0.1:18414/health"

start gateway env SQLITE_PATH="${ROOT}/data/gateway.db" python -m uvicorn gateway_service.main:app --host 0.0.0.0 --port 18410
wait_url "http://127.0.0.1:18410/health"

start web env GATEWAY_URL="http://127.0.0.1:18410" npm --prefix web run dev
wait_url "http://127.0.0.1:18415"

echo "Engram is running at http://127.0.0.1:18415"
wait -n
echo "A process exited. See logs/." >&2
exit 1
