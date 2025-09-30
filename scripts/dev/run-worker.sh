#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  echo "[dev] Creating uv environment (this is a one-time step)..."
  (cd "$BACKEND_DIR" && uv sync --all-extras)
fi

echo "[dev] Launching Celery worker (Ctrl+C to stop)..."
(cd "$BACKEND_DIR" && uv run celery -A app.worker worker -l info)
