from __future__ import annotations

import pytest
from sqlmodel import SQLModel, create_engine

from app.core import database


def test_get_session_uses_configured_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)

    session_gen = database.get_session()
    session = next(session_gen)
    assert session.bind is engine

    with pytest.raises(StopIteration):
        next(session_gen)

    session.close()
    engine.dispose()
