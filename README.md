# CostCourter (FastAPI Edition)

CostCourter is now a Python-first toolchain for experimenting with price tracking, bulk catalog management, and notification workflows. The project began as a port of the PriceBuddy PHP/JS application into a Python/FastAPI + TypeScript/Vue stack, and the legacy implementation has since been retired; only the FastAPI backend, Vue 3 admin, and supporting services remain. At this stage the app is for personal testing and refinement—feel free to iterate locally without worrying about production cutovers.

## Project Layout

```
backend/            FastAPI application, SQLModel data layer, Celery workers, Alembic migrations
frontend/           Vue 3 + Pinia admin experience with Vitest coverage
docs/               Architecture notes, migration log, blueprint
docker-compose.yml  Root compose file for local orchestration
```

## Quickstart

1. Install [uv](https://docs.astral.sh/uv/) (Python 3.13 is managed automatically).
2. Copy `.env.example` → `.env` (replace the legacy `.env/` directory if it still exists) and adjust values if you expose services on different ports.
3. Copy `backend/.env.example` → `backend/.env` and tweak Redis/Postgres credentials if needed.
4. Bring the stack up:
   ```bash
   docker compose up --build
   ```
   (Services expose only the FastAPI and frontend ports by default; Redis/Postgres/Scraper/SearXNG stay on the internal Docker network. Add temporary `ports` mappings in a local override file if you need host access.)
   The stack now provisions a private [SearXNG](https://searxng.org/) container that FastAPI talks to via `http://searxng:8080/search`; no public port is published so the search instance is isolated from the host.
5. Run migrations:
   ```bash
   cd backend
   uv run alembic upgrade head
   ```
6. Start the services locally for development:
   ```bash
   # Backend API + Celery worker
   cd backend
   uv run fastapi dev app/main.py  # or uvicorn for production-style runs
   uv run celery -A app.worker worker --loglevel=info

   # Frontend admin (in a separate shell)
   cd frontend
   npm install
   npm run dev
   ```
   Passkey authentication is available locally once `backend/.env.local` (or your environment) defines `PASSKEY_RELYING_PARTY_ID=localhost` and `PASSKEY_ORIGIN=http://localhost:5173`; use the home page to register a passkey or sign in with an existing one.

### SearXNG configuration

- Compose defaults wire the API to the internal `searxng` service (`SEARXNG_URL=http://searxng:8080/search`) running the `searxng/searxng:latest` image.
- If you run the backend outside Docker, point `SEARXNG_URL` at whichever SearXNG endpoint you expose locally (e.g. `http://localhost:8082/search`).
- The bundled container is private by design—no host port is published—so only other services on the Docker network can access it.

## Tooling

- `uv run ruff check` – linting
- `uv run mypy .` – static typing across application code, tests, and scripts
- `uv run pytest --cov=app --cov=tests` – backend tests (≥95% coverage target)
- `npm run test` inside `frontend/` – Vitest unit coverage

Targeted regression suites covering notifications, catalog backups, product quick add flows, and health reporting live under `backend/tests/`; run them individually during focused work (e.g. `uv run pytest tests/test_notifications_service.py`).

## Status

The previous PHP codebase, Filament UI, and associated Docker setup have been removed. Architectural notes now live in `docs/backend-architecture-blueprint.md`. Authentication/RBAC is intentionally deferred until the Python stack is fully hardened. To reference the original PHP implementation, revisit Git history prior to the legacy removal.

## License

See [LICENSE.md](LICENSE.md) for project licensing details.
