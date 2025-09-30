from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as models
from app.core.config import Settings
from app.models import SearchCache
from app.models.base import utcnow
from app.services.search import (
    HttpClient,
    SearxSearchService,
    _default_http_client_factory,
)


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Any]:
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


class FakeHttpClient:
    def __init__(
        self, responses: list[dict[str, Any]], calls: list[dict[str, Any]]
    ) -> None:
        self._responses = list(responses)
        self.calls = calls

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        timeout: httpx.Timeout,
        headers: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self.calls.append(
            {"url": url, "params": params, "timeout": timeout, "headers": headers}
        )
        if not self._responses:
            raise AssertionError("Unexpected HTTP call")
        payload = self._responses.pop(0)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code=200, json=payload, request=request)


class ErrorHttpClient:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        timeout: httpx.Timeout,
        headers: dict[str, Any] | None = None,
    ) -> httpx.Response:
        raise self._error


def _persist_user_with_store(session: Session) -> models.User:
    user = models.User(email=f"search-{uuid4().hex}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    store = models.Store(
        user_id=user.id,
        name="Example Store",
        slug=f"example-store-{uuid4().hex[:6]}",
        domains=[{"domain": "example.com"}],
    )
    session.add(store)
    session.commit()
    session.refresh(store)
    return user


def _create_product_with_url(
    session: Session,
    *,
    user: models.User,
    store: models.Store,
    name: str,
    url: str,
) -> models.Product:
    product = models.Product(
        user_id=user.id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        is_active=True,
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    product_url = models.ProductURL(
        product_id=product.id,
        store_id=store.id,
        url=url,
        is_primary=True,
        active=True,
    )
    session.add(product_url)
    session.commit()
    session.refresh(product_url)
    return product


def _build_service(
    *,
    settings: Settings,
    http_factory: Callable[[httpx.Timeout], HttpClient],
) -> SearxSearchService:
    return SearxSearchService(settings_obj=settings, http_client_factory=http_factory)


def test_service_fetches_and_caches_results(engine: Any) -> None:
    responses = [
        {
            "results": [
                {
                    "title": "Noise Cancelling Headphones",
                    "url": "https://www.example.com/headphones",
                    "content": "Premium ANC headphones",
                    "thumbnail": "https://example.com/image.jpg",
                    "engine": "google",
                    "score": "12.5",
                },
                {
                    "title": "Spec Sheet",
                    "url": "https://example.com/spec.pdf",
                    "content": "PDF spec sheet",
                    "engine": "google",
                },
            ]
        }
    ]
    calls: list[dict[str, Any]] = []

    def factory(timeout: httpx.Timeout) -> HttpClient:
        return FakeHttpClient(responses, calls)

    service_settings = Settings(
        searxng_url="https://searx.local/search",
        search_cache_ttl_seconds=300,
    )
    service = _build_service(settings=service_settings, http_factory=factory)

    with Session(engine) as session:
        user = _persist_user_with_store(session)
        response = service.search(session, query="noise cancelling", owner=user)

        assert response.cache_hit is False
        assert response.query.startswith("noise cancelling")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.url == "https://www.example.com/headphones"
        assert result.store_id is not None
        assert result.store_name == "Example Store"
        assert response.extra["engines"] == {"google": 1}
        assert len(calls) == 1

        cached_entries = session.exec(select(SearchCache)).all()
        assert len(cached_entries) == 1
        cache_entry = cached_entries[0]
        assert cache_entry.query == response.query
        payload = cast(dict[str, Any], cache_entry.response)
        raw_results = payload.get("results", [])
        assert isinstance(raw_results, list)
        first_raw = cast(dict[str, Any], raw_results[0])
        assert first_raw.get("url") == result.url


def test_service_uses_cache_without_http_call(engine: Any) -> None:
    responses = [
        {
            "results": [
                {
                    "title": "Mechanical Keyboard",
                    "url": "https://example.com/keyboards",
                    "content": "Hot-swappable keys",
                }
            ]
        }
    ]
    first_calls: list[dict[str, Any]] = []

    def first_factory(timeout: httpx.Timeout) -> HttpClient:
        return FakeHttpClient(responses, first_calls)

    service_settings = Settings(searxng_url="https://searx.local/search")
    service = _build_service(settings=service_settings, http_factory=first_factory)

    with Session(engine) as session:
        user = _persist_user_with_store(session)
        _ = service.search(session, query="mechanical keyboard", owner=user)
        assert len(first_calls) == 1

        called = False

        def failing_factory(timeout: httpx.Timeout) -> HttpClient:
            nonlocal called
            called = True
            raise AssertionError("HTTP client should not be invoked when cache is warm")

        cached_service = _build_service(
            settings=service_settings, http_factory=failing_factory
        )
        cached_response = cached_service.search(
            session,
            query="mechanical keyboard",
            owner=user,
        )
        assert cached_response.cache_hit is True
        assert called is False
        assert len(cached_response.results) == 1


def test_service_raises_on_http_error(engine: Any) -> None:
    service_settings = Settings(searxng_url="https://searx.local/search")

    def factory(timeout: httpx.Timeout) -> HttpClient:
        return ErrorHttpClient(httpx.HTTPError("boom"))

    service = _build_service(settings=service_settings, http_factory=factory)

    with Session(engine) as session:
        user = _persist_user_with_store(session)
        response = service.search(session, query="test", owner=user, force_refresh=True)
        assert response.cache_hit is False
        assert response.extra.get("fallback") == "local-cache"


def test_service_returns_local_results_when_disabled(engine: Any) -> None:
    service_settings = Settings(searxng_url=None)

    def factory(timeout: httpx.Timeout) -> HttpClient:
        raise AssertionError("SearXNG HTTP client should not be used when disabled")

    service = _build_service(settings=service_settings, http_factory=factory)

    with Session(engine) as session:
        user = _persist_user_with_store(session)
        store = session.exec(
            select(models.Store).where(models.Store.user_id == user.id)
        ).one()
        _create_product_with_url(
            session,
            user=user,
            store=store,
            name="Satechi Qi2 Trio Wireless Charging Pad",
            url="https://example.com/satechi-qi2",
        )

        response = service.search(session, query="satechi", owner=user)
        assert response.cache_hit is False
        assert response.extra.get("fallback") == "disabled"
        assert response.results
        first = response.results[0]
        assert first.url == "https://example.com/satechi-qi2"
        assert first.store_id == store.id


def test_default_http_client_factory_closes() -> None:
    timeout = httpx.Timeout(5.0)
    client = _default_http_client_factory(timeout)
    try:
        assert isinstance(client, httpx.Client)
        assert client.timeout == timeout
    finally:
        cast(httpx.Client, client).close()


def test_resolve_settings_coerces_string_values(engine: Any) -> None:
    settings_obj = Settings(
        searxng_url="https://searx",
        search_cache_ttl_seconds=200000,
    )
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        session.add(
            models.AppSetting(
                key="integrated_services",
                value='{"searxng": {"url": "https://override", "max_pages": "3", "prune_days": "1"}}',
            )
        )
        session.commit()
        integration = service._resolve_settings(session)
        assert integration.url == "https://override"
        assert integration.max_pages == 3
        assert integration.prune_days == 1
        assert integration.cache_ttl_seconds == 86400


def test_resolve_settings_clamps_invalid_pages(engine: Any) -> None:
    settings_obj = Settings(searxng_url="https://searx")
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        session.add(
            models.AppSetting(
                key="integrated_services",
                value='{"searxng": {"url": "https://override", "max_pages": -5}}',
            )
        )
        session.commit()
        integration = service._resolve_settings(session)
        assert integration.max_pages == 1
        assert service._resolve_page_count(integration, override=5) == 1


def test_load_integration_settings_handles_invalid_payload(engine: Any) -> None:
    service = _build_service(
        settings=Settings(searxng_url="https://searx"),
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        session.add(
            models.AppSetting(
                key="integrated_services",
                value="not-json",
            )
        )
        session.commit()
        assert service._load_integration_settings(session) == {}


def test_load_cache_skips_invalid_payload(engine: Any) -> None:
    service = _build_service(
        settings=Settings(searxng_url="https://searx"),
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        future = utcnow() + timedelta(seconds=60)
        session.add(
            SearchCache(
                query_hash="hash",
                query="widgets",
                response={"results": "invalid"},
                expires_at=future,
            )
        )
        session.commit()
        assert service._load_cache(session, "hash") is None


def test_load_cache_filters_non_dict_items(engine: Any) -> None:
    service = _build_service(
        settings=Settings(searxng_url="https://searx"),
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        future = utcnow() + timedelta(seconds=60)
        session.add(
            SearchCache(
                query_hash="hash",
                query="widgets",
                response={
                    "results": [
                        "ignore",
                        {"url": "https://example.com", "title": "Item"},
                    ]
                },
                expires_at=future,
            )
        )
        session.commit()
        cached = service._load_cache(session, "hash")
        assert cached is not None
        results, expiry = cached
        assert len(results) == 1
        assert results[0].url == "https://example.com"
        assert expiry > utcnow()


def test_fetch_results_deduplicates_urls(engine: Any) -> None:
    responses = [
        {
            "results": [
                {"url": "https://example.com/a", "title": "One"},
                {"url": "https://example.com/a", "title": "Duplicate"},
            ]
        }
    ]

    def factory(timeout: httpx.Timeout) -> HttpClient:
        return FakeHttpClient(responses, calls=[])

    service = _build_service(
        settings=Settings(searxng_url="https://searx"), http_factory=factory
    )
    with Session(engine) as session:
        user = _persist_user_with_store(session)
        result = service.search(
            session, query="duplicate", owner=user, force_refresh=True
        )
        assert len(result.results) == 1


def test_normalize_result_rejects_invalid_entries() -> None:
    service = _build_service(
        settings=Settings(searxng_url="https://searx"),
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    assert service._normalize_result("not-a-dict") is None
    assert service._normalize_result({"url": ""}) is None
    assert service._normalize_result({"url": "https://example.com/file.pdf"}) is None


def test_build_store_lookup_handles_mixed_domains(engine: Any) -> None:
    service = _build_service(
        settings=Settings(searxng_url="https://searx"),
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        user = _persist_user_with_store(session)
        store = session.exec(
            select(models.Store).where(models.Store.user_id == user.id)
        ).one()
        domains: list[Any] = [
            {"domain": "example.org"},
            "www.example.org",
            {"domain": 123},
        ]
        store.domains = cast(list[dict[str, Any]], domains)
        session.add(store)
        session.commit()

        assert user.id is not None
        lookup = service._build_store_lookup(session, owner_id=user.id)
        assert lookup["example.org"][0] == store.id
        assert lookup["www.example.org"][0] == store.id


def test_search_rejects_blank_query(engine: Any) -> None:
    settings_obj = Settings(searxng_url="https://searx")
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        user = _persist_user_with_store(session)
        with pytest.raises(HTTPException) as exc:
            service.search(session, query="   ", owner=user)
        assert exc.value.status_code == 400


def test_search_requires_persisted_user(engine: Any) -> None:
    settings_obj = Settings(searxng_url="https://searx")
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        transient_user = models.User(email="ephemeral@example.com")
        with pytest.raises(HTTPException) as exc:
            service.search(session, query="widgets", owner=transient_user)
        assert exc.value.status_code == 500


def test_search_requires_configuration(engine: Any) -> None:
    settings_obj = Settings(searxng_url=None)
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        user = _persist_user_with_store(session)
        response = service.search(session, query="widgets", owner=user)
        assert response.cache_hit is False
        assert response.extra.get("fallback") == "disabled"
        assert response.results == []


def test_search_prune_days_limits_ttl(engine: Any) -> None:
    settings_obj = Settings(
        searxng_url="https://searx",
        search_cache_ttl_seconds=172800,
    )
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        session.add(
            models.AppSetting(
                key="integrated_services",
                value='{"searxng": {"url": "https://searx", "enabled": true, "prune_days": 1}}',
            )
        )
        session.commit()

        integration = service._resolve_settings(session)
        assert integration.cache_ttl_seconds == 86400


def test_search_load_cache_ignores_expired_entries(engine: Any) -> None:
    settings_obj = Settings(searxng_url="https://searx")
    service = _build_service(
        settings=settings_obj,
        http_factory=lambda t: ErrorHttpClient(RuntimeError("unused")),
    )
    with Session(engine) as session:
        expired = utcnow() - timedelta(seconds=5)
        session.add(
            SearchCache(
                query_hash="hash",
                query="widgets",
                response={"results": []},
                expires_at=expired,
            )
        )
        session.commit()

        assert service._load_cache(session, "hash") is None
