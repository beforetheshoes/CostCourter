from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from sqlmodel import Session

from app.core.database import engine
from app.services.search_cache import prune_search_cache

SessionFactory = Callable[[], AbstractContextManager[Session]]


@contextmanager
def _default_session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


_session_scope: SessionFactory = _default_session_scope


def set_task_session_factory(factory: SessionFactory | None) -> None:
    """Override the session factory used by search maintenance tasks (tests only)."""

    global _session_scope
    _session_scope = factory or _default_session_scope


def _run_with_session(func: Callable[[Session], dict[str, Any]]) -> dict[str, Any]:
    with _session_scope() as session:
        return func(session)


def _parse_cutoff(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid ISO timestamp for 'before'") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@shared_task(name="search.prune_cache")
def prune_search_cache_task(before: str | None = None) -> dict[str, Any]:
    """Remove expired search cache rows and return telemetry for logging."""

    def runner(session: Session) -> dict[str, Any]:
        cutoff = _parse_cutoff(before)
        removed, threshold = prune_search_cache(session, before=cutoff, dry_run=False)
        payload: dict[str, Any] = {
            "removed": removed,
            "threshold": threshold.isoformat(),
        }
        return payload

    return _run_with_session(runner)


__all__ = ["prune_search_cache_task", "set_task_session_factory"]
