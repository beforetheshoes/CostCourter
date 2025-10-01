# CostCourter Python Backend

This backend is the FastAPI + Celery service that now powers CostCourter end to end. The project originated as a port of the PriceBuddy PHP/JS application into Python, and this codebase lives in the `backend/` directory as the primary implementation for local and production workflows.

## Quick Start
1. Install Python 3.11+ and `uv` (`pip install uv`).
2. (Optional) Copy `.env.example` to `.env` if you need custom overrides—the repo now ships with a `backend/.env.local` that targets localhost services.
3. Launch the local-first workflow (PostgreSQL/Redis in Docker, FastAPI on your host):
   ```bash
   # from the repository root
   ./scripts/dev/start-infra.sh          # once per session – keeps postgres/redis/scraper warm
   ./scripts/dev/run-api.sh              # hot-reloading FastAPI (uvicorn --reload)
   # optional: in another terminal if you need background jobs
   ./scripts/dev/run-worker.sh
   ```
   The API is available at <http://localhost:8000>; obtain a JWT via the auth endpoints before calling protected routes. For passwordless local access, configure `PASSKEY_RELYING_PARTY_ID=localhost` and `PASSKEY_ORIGIN=http://localhost:5173` (already set in `.env.local`) and register a passkey from the admin UI.
4. If you prefer full container orchestration, `docker compose up` still boots the entire stack (FastAPI, Celery, Postgres, Redis, scraper, etc.).

Refer to `docs/backend-architecture-blueprint.md` for architecture details; database design decisions and migrations now live entirely in the FastAPI stack.

## Celery Beat Schedule
- The beat process watches `config/celery_schedule.json` (relative to this directory by default).
- Edits to the JSON file are reloaded automatically within a few seconds; invalid JSON falls back to the default 6-hour cadence.
- Each entry may provide either a numeric interval in seconds (`"schedule": 3600`) or cron-style components (`minute`, `hour`, `day_of_week`, etc.).
- The CLI exposes the current schedule together with last/next run metadata:
  ```bash
  uv run python scripts/manage.py show-schedule
  uv run python scripts/manage.py show-schedule --json
  ```
- Manually toggling entries via the admin UI or CLI will update the JSON file and the beat watcher will apply the change without restarts.
