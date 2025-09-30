#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "[dev] Ensuring Postgres, Redis, SearXNG, and Scraper containers are running..."
compose up -d postgres redis searxng scraper

compose ps postgres redis searxng scraper

echo
cat <<'MSG'
[dev] Postgres is available on localhost:5432 (user: costcourter, password: change-me)
[dev] Redis is available on localhost:6379
[dev] SearXNG runs on the internal Docker network (fastapi reaches http://searxng:8080/search)
[dev] Scraper is available on http://localhost:3000
MSG
