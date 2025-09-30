# Python Backend Architecture Blueprint

This blueprint captures the agreed architecture for the Python-based CostCourter backend so the engineering, infra, and data teams can align ahead of implementation. CostCourter began as a port of the PriceBuddy PHP/JS application into Python and TypeScript, and the blueprint highlights how the replatformed services map to (and improve upon) that legacy behaviour.

## Target Service Topology
- **FastAPI application** exposed over HTTP, serving public REST endpoints as well as authenticated admin APIs.
- **Celery worker** pool handling asynchronous jobs (price fetch, cache rebuild, notifications) sharing the same codebase as the FastAPI app.
- **Celery beat** scheduler dispatching periodic tasks (price refresh cadence, housekeeping, cache eviction).
- **PostgreSQL** as the primary relational datastore for users, products, stores, URLs, tags, notification settings, and historical price records.
- **Redis** acting as the Celery broker and lightweight cache, with room to extend for rate limiting or session storage.
- **Existing scraping microservices** (scraper and SearXNG) continue to run as separate containers, communicating with the FastAPI service through internal HTTP endpoints.

## Data Flow Overview
1. REST API receives authenticated requests, applies RBAC/permission checks, and orchestrates reads/writes against PostgreSQL using SQLModel/SQLAlchemy.
2. Mutating operations that require background processing enqueue Celery tasks via Redis (e.g., schedule price checks, send notifications).
3. Celery workers pull tasks from Redis, interact with external services (scraper, notification providers), and persist traces/outcomes back to PostgreSQL.
4. Celery beat seeds scheduled jobs (e.g., nightly price sync) with configuration captured in the same code repository.
5. Structured logging across services emits JSON logs that can be shipped to the existing stack (Loki/ELK) with minimal changes.

## Repository & Docker Layout
```
costcourter/
├─ backend/                      # New Python backend root
│  ├─ app/
│  │  ├─ api/                    # FastAPI routers grouped by domain
│  │  ├─ core/                   # Config, security, logging, dependencies
│  │  ├─ models/                 # SQLModel entities and Pydantic schemas
│  │  ├─ services/               # Business logic / use-cases
│  │  ├─ tasks/                  # Celery task definitions
│  │  └─ worker.py               # Celery application entrypoint
│  ├─ alembic/                   # Migration environment & versions
│  ├─ tests/                     # pytest suite (unit + integration)
│  ├─ pyproject.toml             # Project metadata & dependencies
│  ├─ uv.lock / poetry.lock      # Generated resolver output (UV preferred)
│  └─ README.md                  # Backend-specific onboarding
├─ docker-compose.yml            # FastAPI + Celery + Postgres/Redis development stack
```

## Environment Variable Mapping
| Legacy (.env)                | Purpose                                            | Python backend variable             | Notes |
|------------------------------|----------------------------------------------------|-------------------------------------|-------|
| `APP_NAME`                   | Display name used in notifications/logging         | `APP_NAME` (same)                   | Surface via settings module.
| `APP_ENV`                    | Runtime environment marker                         | `ENVIRONMENT`                       | Controls logging level & debug flags.
| `APP_DEBUG`                  | Toggle debug/trace behavior                        | `DEBUG`                             | Drives FastAPI debug + verbose logging.
| `APP_TIMEZONE`               | Default timezone for scheduled jobs                | `TZ`                                | Also configure Celery timezone.
| `APP_URL`                    | Base URL for generating absolute links             | `BASE_URL`                          | Used in notification templates.
| `APP_LOCALE`                 | Default locale for text                            | `DEFAULT_LOCALE`                    | Feed into translation hooks.
| `APP_CURRENCY_LOCALE`        | Currency formatting                                | `CURRENCY_LOCALE`                   | Backed by Babel for formatting.
| `DB_CONNECTION= mysql`       | DB driver selector                                 | (replaced)                          | Python stack assumes PostgreSQL.
| `DB_HOST`/`DB_PORT`          | Database endpoint                                  | `POSTGRES_HOST` / `POSTGRES_PORT`   | Default `127.0.0.1:5432` in dev.
| `DB_DATABASE`                | Database name                                      | `POSTGRES_DB`                       |
| `DB_USERNAME` / `DB_PASSWORD`| DB credentials                                     | `POSTGRES_USER` / `POSTGRES_PASSWORD` |
| `SESSION_DRIVER`             | Session persistence driver                         | (not used)                          | Session mgmt handled via JWT.
| `QUEUE_CONNECTION`           | Queue backend                                      | `CELERY_BROKER_URL`                 | Format: `redis://:password@host:port/0`.
| `CACHE_STORE`                | Cache provider                                     | `CACHE_BACKEND`                     | Default: Redis; fallback to in-memory.
| `REDIS_HOST`/`REDIS_PORT`    | Redis endpoint                                     | `REDIS_HOST` / `REDIS_PORT`         | Broker + cache.
| `MAIL_*`                     | SMTP config                                        | `SMTP_*`                            | Maintain parity for notification service.
| `AWS_*`                      | Object storage integration                         | `AWS_*` (same)                      | Reserved for future file uploads.
| `VITE_APP_NAME`              | Frontend bootstrapping                             | (unchanged)                         | No direct FastAPI equivalent.

Additional Python-specific settings to introduce:
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- `CELERY_RESULT_BACKEND` (optional Postgres/Redis)
- `SEARXNG_URL`, `SCRAPER_BASE_URL`
- `NOTIFIER_PUSHOVER_TOKEN`, etc., mirroring existing notification integrations.

## Store Onboarding Workflow

Operators can now provision stores in the Python stack before attaching
product URLs. Every store tracks selector metadata, locale, and currency so the
scraper strategies remain explicit and auditable.

1. **CLI bootstrap (preferred for ops scripting)**
   ```bash
   uv run python backend/scripts/manage.py create-store \
       --owner-email ops@example.com \
       --name "Contoso" \
       --slug contoso \
       --website-url https://contoso.example \
       --domain contoso.example \
       --domain www.contoso.example \
       --locale en_US \
       --currency USD \
       --selector title=css:.product-title \
       --selector price=json:$.price.value \
       --selector image=attr:img::src \
       --test-url https://contoso.example/item/sku123 \
       --notes "Imported from legacy catalog"
   ```
   The command ensures the owner exists, normalises currency casing, and writes
   selector metadata to PostgreSQL.

2. **Vue admin UI (`/stores`)** – exposes creation and editing flows with
   domain, selector, locale, and currency fields. Updates persist immediately
   via the FastAPI `/stores` endpoints.

3. **Verification** – the catalog drill-down view now lists all tracked URLs per
   product, including the owning store, locale, currency, and primary/active
   flags for quick validation.

## Admin Bulk Operations & Metrics

### Bulk Import API (`POST /api/product-urls/bulk-import`)
- Accepts a list of URL payloads (each with an optional `set_primary` flag), an
  optional `product_id` to append to an existing product, and a `search_query`
  hint when creating a new product from scratch.
- Returns a summary containing the target product identifiers, created URL
  records (with `product_url_id`, `store_id`, and scraped pricing metadata),
  plus a `skipped` array describing duplicates or validation failures.
- On success, the service reuses the quick-add logic to create/normalise stores,
  builds price history entries when a scrape returns pricing, and rebuilds the
  product price cache. Operators can flip `enqueue_refresh` to push the product
  onto Celery immediately.
- Exercised by `backend/tests/api/test_product_urls.py::test_bulk_import_*` and
  the Vue bulk-import flow covered in
  `frontend/tests/views/SearchView.test.ts`.

### Dashboard Metrics (`GET /api/admin/dashboard`)
- Surfaces aggregate totals (`products`, `favourites`, `active_urls`), spotlight
  products (recent favourites with trend/price information), and grouped views
  that mirror the retired Filament dashboard.
- The Vue home view consumes this endpoint through `useAdminMetricsStore`
  and renders it via `AdminDashboardMetrics.vue`. Regression coverage lives in
  `backend/tests/api/test_dashboard_metrics.py`,
  `frontend/tests/stores/useAdminMetricsStore.test.ts`, and
  `frontend/tests/components/AdminDashboardMetrics.test.ts`.

## Product Lifecycle & Deletion
- The FastAPI catalog service preserves the safeguards that existed in the legacy stack when deleting a product.
  `catalog.delete_product` removes dependent price history rows, product URLs, and tag
  links inside a single transaction to prevent orphaned data.
- Deletion is gated by the same ownership checks used elsewhere in the catalog module,
  so operators cannot purge another user's data unless they are superusers.
- Regression coverage: `backend/tests/api/test_catalog.py::test_delete_product_cascades_urls_and_prices`
  verifies the cascade and ensures no manual clean-up is required before issuing the
  `DELETE /api/products/{id}` call or using the Vue admin delete action.

## Developer Notebook (`notebooks/catalog_explorer.py`)
- A marimo notebook lives under `backend/notebooks/` to help engineers inspect the
  catalog via the same SQLModel services used by the API.
- Launch with `uv run marimo run notebooks/catalog_explorer.py`; the notebook honours
  the configured environment (`.env`) so connections target the same Postgres instance
  used by the app.
- The UI provides:
  - Owner selector to scope data by `user_id`.
  - Computed catalog payloads via `catalog.list_products`, matching the REST response.
  - Drill-down tables for product URLs and price history, including store metadata.
  - Aggregate counts to validate migrations or quick-add/bulk-import runs.
- Because the notebook reuses `catalog` services, any logic changes (e.g., price cache
  rebuilds) surface immediately during exploratory work, making it a living piece of
  documentation for new contributors.

## Cutover Considerations (High Level)
- Keep regression suites aligned with behaviours covered by the retired application so new features do not drift from proven workflows.
- Establish and document the data synchronization strategy used during migration (e.g., nightly ETL or dual-write adapters) so future backfills remain reproducible.
- Document rollback triggers (API health, Celery queue depth, database integrity) alongside proactive monitoring dashboards.
