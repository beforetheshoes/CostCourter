from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.api.deps as api_deps
import app.models as models
from app.core.config import settings


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


def test_get_current_user_returns_synthetic_when_bypassed(engine: Engine) -> None:
    previous = settings.auth_bypass
    settings.auth_bypass = True
    try:
        with Session(engine) as session:
            user = api_deps.get_current_user(credentials=None, session=session)
            assert user.is_superuser is True
            assert user.email == "dev@example.com"
            persisted = session.get(models.User, user.id)
            assert persisted is not None
            assert persisted.is_superuser is True
    finally:
        settings.auth_bypass = previous


def test_get_current_user_handles_duplicate_creation_race(engine: Engine) -> None:
    previous = settings.auth_bypass
    settings.auth_bypass = True
    try:

        def resolve() -> models.User:
            with Session(engine) as session:
                return api_deps.get_current_user(credentials=None, session=session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: resolve(), range(2)))

        assert all(user.email == "dev@example.com" for user in results)

        with Session(engine) as session:
            users = session.exec(select(models.User)).all()
            assert len(users) == 1
    finally:
        settings.auth_bypass = previous


def test_get_current_user_raises_when_provisioning_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyResult:
        def first(self) -> Any:
            return None

    class _Session:
        def __init__(self) -> None:
            self.attempts = 0

        def exec(self, statement: Any) -> _EmptyResult:
            _ = statement
            self.attempts += 1
            return _EmptyResult()

        def add(self, obj: Any) -> None:
            self._last_added = obj

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    previous = settings.auth_bypass
    settings.auth_bypass = True
    session: Any = _Session()
    try:
        with pytest.raises(RuntimeError, match="Failed to provision bypass user"):
            api_deps.get_current_user(credentials=None, session=session)
        assert session.attempts == 10
    finally:
        settings.auth_bypass = previous


def test_get_current_user_retries_transient_commit_errors() -> None:
    class _User:
        def __init__(self, user_id: int) -> None:
            self.id = user_id

    class _Result:
        def __init__(self, value: Any) -> None:
            self._value = value

        def first(self) -> Any:
            return self._value

    class _Session:
        def __init__(self) -> None:
            self.exec_calls = 0
            self.commit_calls = 0
            self.rollback_calls = 0
            self._user = _User(1)
            self._persisted = False

        def exec(self, statement: Any) -> _Result:
            _ = statement
            self.exec_calls += 1
            if not self._persisted:
                return _Result(None)
            return _Result(self._user)

        def add(self, obj: Any) -> None:
            self._user = obj

        def commit(self) -> None:
            from sqlalchemy.exc import InterfaceError

            self.commit_calls += 1
            if self.commit_calls == 1:
                raise InterfaceError("stmt", "params", RuntimeError("boom"))
            self._persisted = True

        def rollback(self) -> None:
            self.rollback_calls += 1

    previous = settings.auth_bypass
    settings.auth_bypass = True
    session: Any = _Session()
    try:
        user = api_deps.get_current_user(credentials=None, session=session)
        assert user is session._user
        assert session.commit_calls == 2
        assert session.rollback_calls == 1
    finally:
        settings.auth_bypass = previous


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
