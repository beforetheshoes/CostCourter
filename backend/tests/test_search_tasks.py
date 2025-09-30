from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import SearchCache
from app.tasks.search import prune_search_cache_task, set_task_session_factory


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


@pytest.fixture(autouse=True)
def override_session_factory(engine: Engine) -> Iterator[None]:
    @contextmanager
    def session_scope() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    set_task_session_factory(session_scope)
    try:
        yield
    finally:
        set_task_session_factory(None)


def _seed_cache(session: Session) -> None:
    now = datetime.now(UTC)
    session.add_all(
        [
            SearchCache(
                query_hash="expired-1",
                query="one",
                response={},
                expires_at=now - timedelta(days=1),
            ),
            SearchCache(
                query_hash="expired-2",
                query="two",
                response={},
                expires_at=now - timedelta(hours=6),
            ),
            SearchCache(
                query_hash="future",
                query="three",
                response={},
                expires_at=now + timedelta(days=2),
            ),
        ]
    )
    session.commit()


def test_prune_search_cache_task_removes_expired(engine: Engine) -> None:
    with Session(engine) as session:
        _seed_cache(session)

    payload = prune_search_cache_task()

    assert payload["removed"] == 2
    assert "threshold" in payload

    with Session(engine) as session:
        remaining = session.exec(select(SearchCache)).all()
        assert len(remaining) == 1
        assert remaining[0].query_hash == "future"


def test_prune_search_cache_task_supports_custom_before(engine: Engine) -> None:
    with Session(engine) as session:
        _seed_cache(session)

    cutoff = (datetime.now(UTC) - timedelta(hours=12)).isoformat()
    payload = prune_search_cache_task(before=cutoff)

    assert payload["removed"] == 1

    with Session(engine) as session:
        hashes = {entry.query_hash for entry in session.exec(select(SearchCache)).all()}
        assert hashes == {"expired-2", "future"}


def test_prune_search_cache_task_invalid_before_raises() -> None:
    with pytest.raises(ValueError):
        prune_search_cache_task(before="not-a-timestamp")
