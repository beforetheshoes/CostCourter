from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import SearchCache
from app.services.search_cache import prune_search_cache


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_cache(
    session: Session,
    *,
    query_hash: str,
    expires_at: datetime,
) -> None:
    entry = SearchCache(
        query_hash=query_hash,
        query="test",
        response={},
        expires_at=expires_at,
    )
    session.add(entry)


def test_prune_search_cache_removes_expired_rows(engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(engine) as session:
        _insert_cache(
            session, query_hash="expired-1", expires_at=now - timedelta(hours=2)
        )
        _insert_cache(
            session, query_hash="expired-2", expires_at=now - timedelta(days=1)
        )
        _insert_cache(session, query_hash="future", expires_at=now + timedelta(days=1))
        session.commit()

        removed, cutoff = prune_search_cache(session)
        assert removed == 2
        assert cutoff.tzinfo is UTC

    with Session(engine) as session:
        remaining = session.exec(select(SearchCache)).all()
        assert len(remaining) == 1
        assert remaining[0].query_hash == "future"


def test_prune_search_cache_dry_run_keeps_rows(engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(engine) as session:
        _insert_cache(
            session, query_hash="expired", expires_at=now - timedelta(hours=6)
        )
        _insert_cache(session, query_hash="future", expires_at=now + timedelta(hours=6))
        session.commit()

        removed, _ = prune_search_cache(session, dry_run=True)
        assert removed == 1

    with Session(engine) as session:
        total = session.exec(select(SearchCache)).all()
        assert len(total) == 2


def test_prune_search_cache_honours_custom_cutoff(engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(engine) as session:
        _insert_cache(session, query_hash="old", expires_at=now - timedelta(days=5))
        _insert_cache(session, query_hash="recent", expires_at=now - timedelta(days=1))
        session.commit()

        cutoff = now - timedelta(days=3)
        removed, _ = prune_search_cache(session, before=cutoff)
        assert removed == 1

    with Session(engine) as session:
        hashes = {row.query_hash for row in session.exec(select(SearchCache)).all()}
        assert hashes == {"recent"}
