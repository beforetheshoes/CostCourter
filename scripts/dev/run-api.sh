#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

FASTAPI_CONTAINER_ID="$(compose ps -q fastapi || true)"
if [ -n "$FASTAPI_CONTAINER_ID" ]; then
  FASTAPI_RUNNING="$(docker inspect -f '{{.State.Running}}' "$FASTAPI_CONTAINER_ID" 2>/dev/null || echo false)"
  if [ "$FASTAPI_RUNNING" = "true" ]; then
    echo "[dev] Stopping docker fastapi container to free port 8000..."
    compose stop fastapi >/dev/null
  fi
fi

if command -v lsof >/dev/null 2>&1; then
  EXISTING_UVICORN_PIDS="$( (lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true) | tr '\n' ' ')"
  if [ -n "$EXISTING_UVICORN_PIDS" ]; then
    echo "[dev] Terminating local processes holding port 8000 ($EXISTING_UVICORN_PIDS)..."
    # Sending SIGTERM first allows uvicorn reload parent/child processes to shut down cleanly.
    kill $EXISTING_UVICORN_PIDS 2>/dev/null || true
    # Wait briefly for the port to be released, then escalate to SIGKILL if needed.
    for _ in 1 2 3; do
      sleep 1
      if ! lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
        break
      fi
    done
    if lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[dev] Forcing port release with SIGKILL..."
      kill -9 $EXISTING_UVICORN_PIDS 2>/dev/null || true
    fi
  fi
fi

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  echo "[dev] Creating uv environment (this is a one-time step)..."
  (cd "$BACKEND_DIR" && uv sync --all-extras)
fi

echo "[dev] Applying latest database migrations..."
(cd "$BACKEND_DIR" && uv run alembic upgrade head)

echo "[dev] Starting FastAPI (uvicorn --reload)..."
(cd "$BACKEND_DIR" \
  && uv run uvicorn app.main:app \
    --reload \
    --host 0.0.0.0 \
    --port 8000 \
    --reload-dir app \
    --reload-dir alembic \
    --reload-exclude '.venv/*' \
    --reload-exclude 'tests/*')
