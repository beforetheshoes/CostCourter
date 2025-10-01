from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.api.deps as api_deps
import app.models as models


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


def test_require_roles_validates_input() -> None:
    with pytest.raises(ValueError):
        api_deps.require_roles()


def test_require_roles_allows_superuser(engine: Engine) -> None:
    dependency = api_deps.require_roles("admin")
    with Session(engine) as session:
        user = models.User(email="super@example.com", is_superuser=True)
        session.add(user)
        session.commit()
        session.refresh(user)

        assert dependency(user, session) is user


def test_require_roles_requires_membership(engine: Engine) -> None:
    dependency = api_deps.require_roles("admin")
    with Session(engine) as session:
        user = models.User(email="user@example.com", is_superuser=False)
        session.add(user)
        session.commit()
        session.refresh(user)

        with pytest.raises(HTTPException) as exc:
            dependency(user, session)
        assert exc.value.status_code == 403
        assert "Insufficient" in exc.value.detail


def test_require_roles_accepts_matching_role(engine: Engine) -> None:
    dependency = api_deps.require_roles("admin")
    with Session(engine) as session:
        user = models.User(email="admin@example.com")
        role = models.Role(slug="admin", name="Admin")
        session.add(user)
        session.add(role)
        session.commit()
        session.refresh(user)
        session.refresh(role)

        assignment = models.UserRoleAssignment(user_id=user.id, role_id=role.id)
        session.add(assignment)
        session.commit()

        resolved = dependency(user, session)
        assert resolved is user


def test_get_current_user_requires_credentials(engine: Engine) -> None:
    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            api_deps.get_current_user(credentials=None, session=session)

    assert exc.value.status_code == 401
    assert "Missing Authorization" in exc.value.detail


def test_get_scraper_client_factory_returns_http_client() -> None:
    factory = api_deps.get_scraper_client_factory()
    client = factory()
    try:
        assert isinstance(client, httpx.Client)
    finally:
        client.close()


def test_price_refresh_dispatcher_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, dict[str, int]] = {}

    class FakeTask:
        def delay(self, **kwargs: int) -> None:
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "app.tasks.pricing.update_product_prices_task",
        FakeTask(),
    )

    dispatcher = api_deps.get_price_refresh_dispatcher()
    dispatcher.enqueue(42)
    assert captured["kwargs"] == {"product_id": 42, "logging": False}
