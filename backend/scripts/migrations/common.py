from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

logger = structlog.get_logger(__name__)


def build_engine(dsn: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine from a DSN string.

    The DSN may be any URL supported by SQLAlchemy, e.g.
    postgresql+psycopg://user:pass@host:5432/dbname
    mysql+pymysql://user:pass@host:3306/dbname
    """

    engine = create_engine(dsn, echo=echo, future=True)
    return engine


@contextmanager
def engine_scope(engine: Engine) -> Iterator[Engine]:
    try:
        yield engine
    finally:
        engine.dispose()


def info(msg: str, **kwargs: Any) -> None:
    logger.info(msg, **kwargs)
