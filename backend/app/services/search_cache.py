from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models import SearchCache
from app.models.base import utcnow


def _normalize_cutoff(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def prune_search_cache(
    session: Session,
    *,
    before: datetime | None = None,
    dry_run: bool = False,
) -> tuple[int, datetime]:
    """Remove cached search results that expire on or before ``before``.

    Returns a tuple containing the number of entries considered and the cutoff
    instant used for evaluation. When ``dry_run`` is True, the database is not
    modified and the count reflects how many rows would be deleted.
    """

    cutoff = _normalize_cutoff(before)
    statement = select(SearchCache).where(SearchCache.expires_at <= cutoff)
    entries = session.exec(statement).all()
    removed = len(entries)
    if dry_run or removed == 0:
        return removed, cutoff

    for entry in entries:
        session.delete(entry)
    session.commit()
    return removed, cutoff


__all__ = ["prune_search_cache"]
