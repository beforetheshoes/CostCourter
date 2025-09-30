# Engineering Working Agreement

## Mission
CostCourter now runs on a FastAPI-based Python stack backed by PostgreSQL, Redis, and Celery. The initiative started as a port of the PriceBuddy PHP/JS application into Python and TypeScript, and our mandate is to continue refining parity with that retired system while improving developer efficiency, reliability, and scalability. The legacy stack has been removed from the repository, so the Python services act as the sole implementation during personal testing.

## Architecture Snapshot
- **FastAPI REST API** providing public and authenticated admin endpoints.
- **SQLModel/SQLAlchemy + PostgreSQL** as the primary data layer with Alembic-managed migrations.
- **Celery workers and beat** using Redis for the message broker (and optional result backend) to run price retrieval, cache regeneration, and notification jobs.
- **External services** such as the existing scraper and SearXNG remain separate containers reachable over internal HTTP.
- **Observability** through structured logging (structlog) with hooks for the current monitoring stack.

See `docs/backend-architecture-blueprint.md` for the detailed blueprint; that document also captures the current domain model.

## Delivery Principles
- **Test-Driven Development**: Write failing tests first to capture intent, then implement the minimal code to pass, and finally refactor while keeping tests green.
- **Tooling**: Manage Python environments and dependency workflows exclusively with `uv`; avoid `pip`, `virtualenv`, or other package managers.
- **Test Quality Gate**: Maintain ≥95% coverage with `pytest --cov`; all tests must pass with no skips, xfails, or ignored scenarios.
- **Static Quality Gate**: `black`, `ruff`, and `mypy` must succeed before any commit. Format code with Black, lint with Ruff, and keep typings sound—no exceptions.
- **No Suppression Directives**: Do not introduce `# noqa`, `# type: ignore`, `# pragma: no cover`, `@pytest.skip`, or similar bypass commands in this repository.
- **Continuous Verification**: Expand tests whenever new behaviour is introduced, protect against regressions, and keep the automated checks in local scripts/CI up to date.

Adhering to these agreements ensures the migration stays intentional, observable, and production-ready at every iteration.

## Reference Notes
- Architecture and domain details: `docs/backend-architecture-blueprint.md`.
