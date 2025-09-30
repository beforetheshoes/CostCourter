#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Restart the Python stack (FastAPI, Celery, Postgres, Redis, Scraper), run DB migrations,
wait for health, and print recent logs.

Usage:
  bash scripts/dev/restart-stack.sh [--rebuild] [--follow]

Options:
  --rebuild   Rebuild Python images (fastapi, celery-worker, celery-beat, migrate, etl)
  --follow    After restart, follow FastAPI and Scraper logs

Environment:
  COMPOSE_FILE   Override compose file (default: docker-compose.yml)
USAGE
}

REBUILD=false
FOLLOW=false
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --rebuild) REBUILD=true ;;
    --follow)  FOLLOW=true ;;
    *) echo "Unknown arg: $arg" >&2; usage; exit 1 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE_DEFAULT="$ROOT_DIR/docker-compose.yml"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_FILE_DEFAULT}"

echo "[info] Using compose file: $COMPOSE_FILE"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "[info] Stopping any existing stack (if running)…"
compose down --remove-orphans >/dev/null 2>&1 || true

if [ "$REBUILD" = true ]; then
  echo "[info] Rebuilding core images…"
  compose build --no-cache fastapi celery-worker celery-beat migrate etl || true
fi

echo "[info] Bringing up core dependencies (postgres, redis, scraper)…"
compose up -d postgres redis scraper

echo "[info] Running DB migrations…"
compose up -d migrate

MIGRATE_ID="$(compose ps -q migrate)"
if [ -n "$MIGRATE_ID" ]; then
  echo "[info] Waiting for migrate to complete…"
  SECS=0
  TIMEOUT=120
  while true; do
    STATUS="$(docker inspect -f '{{.State.Status}}' "$MIGRATE_ID" 2>/dev/null || echo unknown)"
    if [ "$STATUS" = "exited" ]; then
      CODE="$(docker inspect -f '{{.State.ExitCode}}' "$MIGRATE_ID" 2>/dev/null || echo 1)"
      if [ "$CODE" = "0" ]; then
        echo "[ok] migrate completed successfully"
        break
      else
        echo "[err] migrate failed with exit code $CODE" >&2
        compose logs --no-color --tail=200 migrate || true
        exit 1
      fi
    fi
    if [ "$SECS" -ge "$TIMEOUT" ]; then
      echo "[warn] migrate still not finished after ${TIMEOUT}s; continuing" >&2
      break
    fi
    sleep 2; SECS=$((SECS+2))
  done
fi

echo "[info] Starting application services (fastapi, celery-worker, celery-beat)…"
compose up -d fastapi celery-worker celery-beat

FASTAPI_ID="$(compose ps -q fastapi)"
if [ -n "$FASTAPI_ID" ]; then
  echo "[info] Waiting for FastAPI to become healthy…"
  SECS=0
  TIMEOUT=120
  while true; do
    HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$FASTAPI_ID" 2>/dev/null || echo none)"
    if [ "$HEALTH" = "healthy" ]; then
      echo "[ok] FastAPI is healthy"
      break
    fi
    if [ "$SECS" -ge "$TIMEOUT" ]; then
      echo "[warn] FastAPI not healthy after ${TIMEOUT}s; continuing" >&2
      break
    fi
    sleep 2; SECS=$((SECS+2))
  done
fi

echo "[info] Service status:"
compose ps

echo "[info] Recent logs (migrate, fastapi, scraper)…"
compose logs --no-color --tail=200 migrate || true
compose logs --no-color --tail=200 fastapi || true
compose logs --no-color --tail=200 scraper || true

if [ "$FOLLOW" = true ]; then
  echo "[info] Following logs: fastapi, scraper (Ctrl+C to stop)"
  compose logs -f fastapi scraper
fi

echo "[done] Stack restarted and logs printed."
