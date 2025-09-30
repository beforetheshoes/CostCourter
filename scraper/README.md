# CostCourter Playwright Scraper

FastAPI service that wraps Playwright to fetch product metadata for the backend quick-add flow.

## Local Development

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 3000
```

Playwright browsers are managed by the upstream Docker image; locally run `playwright install chromium` once if needed.
