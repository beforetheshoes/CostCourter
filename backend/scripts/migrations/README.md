# Data Migration Playbook

This directory hosts the ETL commands that mirror the legacy CostCourter ➝ FastAPI data flow.
Each command is idempotent and reuses the shared fixtures in `app/fixtures/`,
keeping automated tests and local rehearsal runs aligned.

## Script Overview

| Script | Purpose |
| --- | --- |
| `load_users.py` | Copy users and identity records from the legacy PostgreSQL schema into the FastAPI database. |
| `load_catalog.py` | Migrate stores, products, URLs, tags, and price history. |
| `load_notifications.py` | Sync notification preferences into `app_settings`. |
| `load_reference_data.py` | Seed reference roles/app settings from fixtures. |
| `validate_counts.py` | Compare table counts between the legacy database and the FastAPI database. |
| `validate_fks.py` | Assert foreign keys resolve after migration. |

`load_catalog.py` accepts optional helpers like `--fallback-owner-email` when
legacy rows lack owners and `--store-currency-file` for per-store currency
overrides during price history migration.

Unit tests exercise these scripts against SQLite so behaviour is verified
without requiring live Postgres connections, but all real migrations should run
against PostgreSQL DSNs.

`manage.py` also exposes a `seed-sample-data` command that bootstraps the
shared catalog fixture for local development when Postgres is empty.

## Validation Checklist

Use the checklist below during every rehearsal run. Check off each item in your
working notes or issue tracker before moving to the next stage.

- [ ] Bring up the Python stack (`docker compose up`) with Postgres, Redis, and the scraper.
- [ ] Run `uv run python -m scripts.migrations.load_reference_data --postgres-dsn <dsn>`.
- [ ] Run `uv run python -m scripts.migrations.load_users --mysql-dsn <dsn> --postgres-dsn <dsn>`.
- [ ] Run `uv run python -m scripts.migrations.load_catalog --mysql-dsn <dsn> --postgres-dsn <dsn>`.
- [ ] Run `uv run python -m scripts.migrations.load_notifications --mysql-dsn <dsn> --postgres-dsn <dsn>`.
- [ ] Run `uv run python -m scripts.migrations.validate_counts --mysql-dsn <dsn> --postgres-dsn <dsn>`.
- [ ] Run `uv run python -m scripts.migrations.validate_fks --postgres-dsn <dsn>`.
- [ ] Optionally seed fixtures via `uv run python scripts/manage.py seed-sample-data --owner-email you@example.com` for UI smoke tests.
- [ ] Execute `uv run pytest --cov` to confirm migration helpers remain covered.

## Troubleshooting Notes

- Pass `--echo-sql` to any script for verbose logging while diagnosing issues.
- The validation helpers exit with a non-zero status when a mismatch is found;
  capture the emitted summary in your working notes before retrying.
- If legacy snapshots contain orphaned rows, fix them in the export before
  re-running the scripts to keep Postgres clean.
