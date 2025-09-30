# Backend Migration Status

This log tracks FastAPI feature parity milestones and ongoing verification notes for the PriceBuddy → CostCourter port. Update the checklist and log entries whenever a migration task lands.

## Feature Parity Checklist
- [x] Legacy PHP application removed from the repository
- [x] Product bulk publish/archive/favourite endpoints & Vue admin support
- [x] Tag merge flows across backend services and admin UI
- [x] Multi-store product URL management exposed in the Vue admin
- [ ] Price notification workflows migrated
- [ ] Auth/RBAC parity (deferred until post-migration)

## Verification Log
| Date (UTC) | Owner | Summary | Coverage / Follow-ups |
|------------|-------|---------|------------------------|
| 2025-09-28 | Codex | Added idempotent handling for synthetic auth-bypass user creation, hardened product URL primary toggling, and exposed multi-URL management + slug cleanup in the admin UI. | `uv run pytest --cov` (95%), `uv run mypy .`, `uv run ruff check`, `npm run test -- tests/views/ProductsView.test.ts` & `tests/stores/useProductsStore.test.ts`. Confirm docker stack restart helper to be rehearsed separately. |
