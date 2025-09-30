from __future__ import annotations

from collections.abc import Generator

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_database_uri_uses_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "15432")
    monkeypatch.setenv("POSTGRES_DB", "costcourter_test")
    monkeypatch.setenv("POSTGRES_USER", "pb")
    monkeypatch.setenv("POSTGRES_PASSWORD", "supersecret")

    settings = get_settings()

    assert (
        settings.database_uri
        == "postgresql+psycopg://pb:supersecret@db.internal:15432/costcourter_test"
    )


def test_redis_uri_supports_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_USERNAME", raising=False)
    override = Settings(
        redis_host="cache", redis_port=6380, redis_password="token", redis_db=2
    )
    assert override.redis_uri == "redis://:token@cache:6380/2"


def test_redis_uri_supports_username_password() -> None:
    override = Settings(
        redis_host="cache",
        redis_port=6381,
        redis_username="worker",
        redis_password="token",
        redis_db=5,
    )
    assert override.redis_uri == "redis://worker:token@cache:6381/5"


def test_settings_defaults() -> None:
    defaults = Settings()
    assert defaults.app_name == "CostCourter"
    assert defaults.environment == "local"
    assert defaults.debug is True
    assert defaults.redis_uri == "redis://127.0.0.1:6379/0"
