from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings
from app.models import ensure_core_model_mappings

engine = create_engine(settings.database_uri, echo=settings.debug)


def get_session() -> Generator[Session, None, None]:
    # Ensure mappers are configured before any DB interaction
    ensure_core_model_mappings()
    with Session(engine) as session:
        yield session
