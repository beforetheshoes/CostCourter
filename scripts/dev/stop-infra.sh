#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "[dev] Stopping Postgres and Redis containers..."
compose stop postgres redis

MSG="Containers stopped. Use 'docker compose rm postgres redis' to remove them fully if desired."
echo "[dev] $MSG"
