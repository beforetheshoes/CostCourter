from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as models
from app.core.config import Settings
from app.services.notifications import (
    NotificationService,
    set_notification_service_factory,
)
from app.services.price_fetcher import (
    HttpClient,
    PriceFetcherConfigurationError,
    PriceFetcherService,
    PriceFetchSummary,
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


def _build_catalog(session: Session) -> models.ProductURL:
    user = models.User(email=f"catalog-{uuid4().hex}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    store = models.Store(
        user_id=user.id, name="Example Store", slug=f"example-store-{uuid4().hex[:8]}"
    )
    product = models.Product(
        user_id=user.id, name="Widget", slug=f"widget-{uuid4().hex[:8]}"
    )
    session.add(store)
    session.add(product)
    session.commit()
    assert store.id is not None
    assert product.id is not None

    product_url = models.ProductURL(
        product_id=product.id,
        store_id=store.id,
        url="https://example.com/widget",
        is_primary=True,
    )
    session.add(product_url)
    session.commit()
    session.refresh(product_url)
    return product_url


class RecorderClient:
    def __init__(
        self,
        *,
        payload: dict[str, Any],
        calls: list[dict[str, Any]],
        response_sequence: list[dict[str, Any]] | None = None,
    ) -> None:
        self._payload = payload
        self._calls = calls
        self._sequence = response_sequence or []

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        self._calls.append({"url": url, "json": json, "timeout": timeout})
        if self._sequence:
            payload = self._sequence.pop(0)
        else:
            payload = self._payload
        request = httpx.Request("POST", url, json=json)
        return httpx.Response(status_code=200, json=payload, request=request)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: Any,
    ) -> httpx.Response:
        self._calls.append({"url": url, "params": params or {}, "timeout": timeout})
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code=200, json=self._payload, request=request)


class FallbackClient:
    def __init__(
        self,
        *,
        scrape_calls: list[dict[str, Any]],
        article_calls: list[dict[str, Any]],
        article_payload: dict[str, Any],
    ) -> None:
        self._scrape_calls = scrape_calls
        self._article_calls = article_calls
        self._article_payload = article_payload

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        self._scrape_calls.append({"url": url, "json": json, "timeout": timeout})
        request = httpx.Request("POST", url, json=json)
        response = httpx.Response(status_code=404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: Any,
    ) -> httpx.Response:
        payload = {"params": params or {}, "timeout": timeout}
        self._article_calls.append({"url": url, **payload})
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            status_code=200,
            json=self._article_payload,
            request=request,
        )


class HttpErrorClient:
    def __init__(self, *, error: Exception) -> None:
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

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        raise self._error

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: Any,
    ) -> httpx.Response:
        raise self._error


class SequenceClient:
    def __init__(self, outcomes: list[dict[str, Any] | Exception]) -> None:
        self._outcomes = outcomes

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        if not self._outcomes:
            raise RuntimeError("No more outcomes configured")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        request = httpx.Request("POST", url, json=json)
        return httpx.Response(status_code=200, json=outcome, request=request)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: Any,
    ) -> httpx.Response:
        raise RuntimeError("SequenceClient does not support GET requests")


class _NotificationStub(NotificationService):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.price_alerts: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    def send_price_alert(
        self,
        session: Session,
        *,
        product: models.Product,
        product_url: models.ProductURL,
        history: models.PriceHistory,
    ) -> None:
        self.price_alerts.append(
            {
                "product_id": product.id,
                "product_url_id": product_url.id,
                "history_id": history.id,
                "price": history.price,
            }
        )

    def notify_scrape_failure(
        self,
        session: Session,
        *,
        product: models.Product,
        summary: PriceFetchSummary,
    ) -> None:
        self.failures.append(
            {
                "product_id": product.id,
                "failed_urls": [
                    result.product_url_id
                    for result in summary.results
                    if not result.success
                ],
            }
        )


@pytest.fixture(name="notification_stub")
def notification_stub_fixture() -> Iterator[_NotificationStub]:
    stub = _NotificationStub()
    set_notification_service_factory(lambda: stub)
    try:
        yield stub
    finally:
        set_notification_service_factory(None)


def test_fetch_price_for_url_records_history(engine: Any) -> None:
    calls: list[dict[str, Any]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        return RecorderClient(
            payload={"price": "129.99", "currency": "AUD"}, calls=calls
        )

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        result = service.fetch_price_for_url(session, product_url.id)

        assert result.success is True
        assert result.product_url_id == product_url.id
        assert result.price == pytest.approx(129.99)
        assert result.currency == "AUD"
        assert len(calls) == 1
        request = calls[0]
        assert request["url"] == "https://scraper.local/scrape"
        assert request["json"] == {"url": "https://example.com/widget"}

        history = session.exec(select(models.PriceHistory)).all()
        assert len(history) == 1
        entry = history[0]
        assert entry.price == pytest.approx(129.99)
        assert entry.currency == "AUD"
        assert entry.product_url_id == product_url.id
        assert entry.recorded_at.tzinfo is None

        persisted_product = session.get(models.Product, product_url.product_id)
        assert persisted_product is not None
        assert persisted_product.current_price == pytest.approx(129.99)
        assert persisted_product.price_cache
        cache_entry = persisted_product.price_cache[0]
        assert cache_entry["price"] == pytest.approx(129.99)
        assert cache_entry["trend"] == "lowest"


def test_fetch_price_for_url_handles_missing_price(engine: Any) -> None:
    calls: list[dict[str, Any]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        return RecorderClient(payload={"price": None, "currency": "USD"}, calls=calls)

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        result = service.fetch_price_for_url(session, product_url.id)

        assert result.success is False
        assert result.reason == "missing_price"
        post_calls = [entry for entry in calls if "json" in entry]
        assert len(post_calls) == 1
        request = post_calls[0]
        assert request["url"] == "https://scraper.local/scrape"
        assert request["json"] == {"url": "https://example.com/widget"}
        history = session.exec(select(models.PriceHistory)).all()
        assert history == []
        product = session.get(models.Product, product_url.product_id)
        assert product is not None
        assert product.current_price is None
        assert product.price_cache == []


def test_fetch_price_for_url_handles_invalid_price(engine: Any) -> None:
    calls: list[dict[str, Any]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        return RecorderClient(
            payload={"price": "not-a-number", "currency": "USD"}, calls=calls
        )

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        result = service.fetch_price_for_url(session, product_url.id)

        assert result.success is False
        assert result.reason == "invalid_price"
        assert len(calls) == 1
        history = session.exec(select(models.PriceHistory)).all()
        assert history == []
        product = session.get(models.Product, product_url.product_id)
        assert product is not None
        assert product.current_price is None
        assert product.price_cache == []


def test_fetch_price_for_url_handles_http_error(engine: Any) -> None:
    def factory(timeout: tuple[float, float]) -> HttpClient:
        return HttpErrorClient(error=RuntimeError("boom"))

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        result = service.fetch_price_for_url(session, product_url.id)

        assert result.success is False
        assert result.reason == "http_error"
        history = session.exec(select(models.PriceHistory)).all()
        assert history == []


def test_fetch_price_for_url_falls_back_to_article_endpoint(engine: Any) -> None:
    scrape_calls: list[dict[str, Any]] = []
    article_calls: list[dict[str, Any]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        html = "<html><div class='price'>$19.50</div></html>"
        payload = {"fullContent": html, "currency": "USD"}
        return FallbackClient(
            scrape_calls=scrape_calls,
            article_calls=article_calls,
            article_payload=payload,
        )

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        store = session.get(models.Store, product_url.store_id)
        assert store is not None
        store.scrape_strategy = {
            "price": {"type": "css", "value": ".price"},
        }
        store.settings = {
            "scraper_service": "http",
            "scraper_service_settings": "",
            "locale_settings": {"currency": "USD", "locale": "en_US"},
        }
        session.add(store)
        session.commit()

        result = service.fetch_price_for_url(session, product_url.id)

    assert result.success is True
    assert result.price == pytest.approx(19.50)
    assert result.currency == "USD"
    assert scrape_calls, "expected scrape endpoint to be invoked"
    assert article_calls, "expected fallback article endpoint to be invoked"
    assert article_calls[0]["params"]["url"] == "https://example.com/widget"


def test_fetch_price_for_url_requires_scraper_base_url(engine: Any) -> None:
    settings = Settings(scraper_base_url=None)
    service = PriceFetcherService(settings=settings)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        with pytest.raises(PriceFetcherConfigurationError):
            service.fetch_price_for_url(session, product_url.id)


def test_update_product_prices_skips_inactive(engine: Any) -> None:
    def factory(timeout: tuple[float, float]) -> HttpClient:
        return RecorderClient(
            payload={"price": 10, "currency": "USD"},
            calls=[],
            response_sequence=[
                {"price": 10, "currency": "USD"},
                {"price": 12, "currency": "USD"},
            ],
        )

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        secondary = models.ProductURL(
            product_id=product_url.product_id,
            store_id=product_url.store_id,
            url="https://example.com/widget-2",
            active=True,
        )
        inactive = models.ProductURL(
            product_id=product_url.product_id,
            store_id=product_url.store_id,
            url="https://example.com/inactive",
            active=False,
        )
        session.add(secondary)
        session.add(inactive)
        session.commit()
        session.refresh(secondary)

        summary = service.update_product_prices(session, product_url.product_id)

        assert summary.total_urls == 2
        assert summary.successful_urls == 2
        assert summary.failed_urls == 0
        assert [result.product_url_id for result in summary.results] == [
            product_url.id,
            secondary.id,
        ]
        history = session.exec(select(models.PriceHistory)).all()
    assert len(history) == 2


def test_fetch_price_for_url_triggers_price_alert(
    engine: Any, notification_stub: _NotificationStub
) -> None:
    def factory(timeout: tuple[float, float]) -> HttpClient:
        return RecorderClient(payload={"price": 89.0, "currency": "USD"}, calls=[])

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        product = session.get(models.Product, product_url.product_id)
        assert product is not None
        assert product_url.id is not None
        product.notify_price = 100.0
        session.add(product)
        session.commit()
        session.refresh(product)

        result = service.fetch_price_for_url(session, product_url.id)

        assert result.success is True
        assert len(notification_stub.price_alerts) == 1
        event = notification_stub.price_alerts[0]
        assert event["product_id"] == product.id
        history = session.exec(select(models.PriceHistory)).one()
        assert history.notified is True


def test_fetch_price_for_url_skips_duplicate_alerts(
    engine: Any, notification_stub: _NotificationStub
) -> None:
    sequence: list[dict[str, Any] | Exception] = [
        {"price": 75.0, "currency": "USD"},
        {"price": 75.0, "currency": "USD"},
    ]

    def factory(timeout: tuple[float, float]) -> HttpClient:
        return SequenceClient(sequence.copy())

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        product = session.get(models.Product, product_url.product_id)
        assert product is not None
        assert product_url.id is not None
        product.notify_price = 80.0
        session.add(product)
        session.commit()
        session.refresh(product)

        first = service.fetch_price_for_url(session, product_url.id)
        assert first.success is True

        second = service.fetch_price_for_url(session, product_url.id)
        assert second.success is True

        assert len(notification_stub.price_alerts) == 1


def test_fetch_price_for_url_uses_store_scraper_overrides(engine: Any) -> None:
    calls: list[dict[str, Any]] = []
    timeouts: list[tuple[float, float]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        timeouts.append(timeout)
        return RecorderClient(
            payload={"price": "15.50", "currency": "USD"}, calls=calls
        )

    settings = Settings(scraper_base_url="https://default-scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        store = session.get(models.Store, product_url.store_id)
        assert store is not None
        store.settings = {
            "scraper_service": "api",
            "scraper_service_settings": (
                "base_url=https://store-scraper.test\n"
                "connect_timeout=7.5\n"
                "request_timeout=33.25\n"
                "header_x=X-Test\n"
            ),
            "locale_settings": {"locale": "en_AU", "currency": "AUD"},
        }
        store.scrape_strategy = {
            "price": {"type": "css", "value": ".price"},
            "title": {"type": "css", "value": "h1"},
        }
        session.add(store)
        session.commit()

        result = service.fetch_price_for_url(session, product_url.id)

    assert result.success is True
    assert timeouts == [(7.5, 33.25)]
    assert len(calls) == 1
    request = calls[0]
    assert request["url"] == "https://store-scraper.test/scrape"
    payload = request["json"]
    assert payload["url"] == "https://example.com/widget"
    assert payload["service"] == "api"
    assert payload["strategy"]["price"]["value"] == ".price"
    options = payload["options"]
    assert options["header_x"] == "X-Test"
    assert options["locale_settings"] == {"locale": "en_AU", "currency": "AUD"}
    timeout = request["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == pytest.approx(7.5)
    assert timeout.read == pytest.approx(33.25)


def test_fetch_price_for_url_requires_store_base_when_global_missing(
    engine: Any,
) -> None:
    service = PriceFetcherService(settings=Settings(scraper_base_url=None))

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        store = session.get(models.Store, product_url.store_id)
        assert store is not None
        store.settings = {
            "scraper_service": "api",
            "scraper_service_settings": "",
        }
        session.add(store)
        session.commit()

        with pytest.raises(PriceFetcherConfigurationError) as excinfo:
            service.fetch_price_for_url(session, product_url.id)

    assert "store" in str(excinfo.value).lower()


def test_fetch_price_for_url_ignores_invalid_timeout_override(engine: Any) -> None:
    calls: list[dict[str, Any]] = []
    timeouts: list[tuple[float, float]] = []

    def factory(timeout: tuple[float, float]) -> HttpClient:
        timeouts.append(timeout)
        return RecorderClient(payload={"price": 12, "currency": "USD"}, calls=calls)

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        product_url = _build_catalog(session)
        assert product_url.id is not None
        store = session.get(models.Store, product_url.store_id)
        assert store is not None
        store.settings = {
            "scraper_service_settings": "connect_timeout=abc\nrequest_timeout=15",
        }
        session.add(store)
        session.commit()

        service.fetch_price_for_url(session, product_url.id)

    expected_connect = service.settings.scraper_connect_timeout
    assert timeouts == [(expected_connect, 15.0)]
    assert isinstance(calls[0]["timeout"], httpx.Timeout)


def test_update_product_prices_notifies_on_failures(
    engine: Any, notification_stub: _NotificationStub
) -> None:
    outcomes: list[dict[str, Any] | Exception] = [
        {"price": 60.0, "currency": "USD"},
        RuntimeError("failed scrape"),
    ]

    def factory(timeout: tuple[float, float]) -> HttpClient:
        return SequenceClient(outcomes)

    settings = Settings(scraper_base_url="https://scraper.local")
    service = PriceFetcherService(settings=settings, http_client_factory=factory)

    with Session(engine) as session:
        primary = _build_catalog(session)
        secondary = models.ProductURL(
            product_id=primary.product_id,
            store_id=primary.store_id,
            url="https://example.com/secondary",
            is_primary=False,
            active=True,
        )
        session.add(secondary)
        session.commit()
        session.refresh(secondary)

        product = session.get(models.Product, primary.product_id)
        assert product is not None
        assert primary.id is not None
        assert secondary.id is not None

        summary = service.update_product_prices(session, primary.product_id)

        assert summary.failed_urls == 1
        assert notification_stub.failures
        failure_event = notification_stub.failures[0]
        assert failure_event["product_id"] == product.id
        assert secondary.id in failure_event["failed_urls"]


def test_update_all_products_uses_chunking(engine: Any) -> None:
    settings = Settings(
        scraper_base_url="https://scraper.local", price_fetch_chunk_size=2
    )

    class RecordingService(PriceFetcherService):
        def __init__(self) -> None:
            super().__init__(
                settings,
                http_client_factory=lambda _: RecorderClient(payload={}, calls=[]),
            )
            self.calls: list[int] = []

        def update_product_prices(
            self,
            session: Session,
            product_id: int,
            *,
            logging: bool = False,
            audit_actor_id: int | None = None,
            audit_ip: str | None = None,
            owner_id: int | None = None,
        ) -> PriceFetchSummary:
            self.calls.append(product_id)
            return PriceFetchSummary()

    service = RecordingService()

    with Session(engine) as session:
        for index in range(3):
            if index == 0:
                user = models.User(email="chunk-user@example.com")
                session.add(user)
                session.commit()
                session.refresh(user)
            product = models.Product(
                user_id=user.id,
                name=f"Product {index}",
                slug=f"product-{index}-{uuid4().hex[:6]}",
            )
            session.add(product)
        session.commit()

        summary = service.update_all_products(session)

    assert summary.total_urls == 0
    assert service.calls == [1, 2, 3]


def test_update_all_products_scopes_to_owner(engine: Any) -> None:
    settings = Settings(
        scraper_base_url="https://scraper.local",
        price_fetch_chunk_size=5,
    )

    class RecordingService(PriceFetcherService):
        def __init__(self) -> None:
            super().__init__(
                settings,
                http_client_factory=lambda _: RecorderClient(payload={}, calls=[]),
            )
            self.calls: list[int] = []

        def update_product_prices(
            self,
            session: Session,
            product_id: int,
            *,
            logging: bool = False,
            audit_actor_id: int | None = None,
            audit_ip: str | None = None,
            owner_id: int | None = None,
        ) -> PriceFetchSummary:
            self.calls.append(product_id)
            return PriceFetchSummary()

    service = RecordingService()

    with Session(engine) as session:
        owner_one = models.User(email="owner-one@example.com")
        owner_two = models.User(email="owner-two@example.com")
        session.add(owner_one)
        session.add(owner_two)
        session.commit()
        session.refresh(owner_one)
        session.refresh(owner_two)

        products: list[models.Product] = []
        for index in range(3):
            current_owner = owner_one if index < 2 else owner_two
            product = models.Product(
                user_id=current_owner.id,
                name=f"Scoped Product {index}",
                slug=f"scoped-{index}-{uuid4().hex[:6]}",
            )
            session.add(product)
            session.commit()
            session.refresh(product)
            products.append(product)

        summary = service.update_all_products(session, owner_id=owner_one.id)
        owner_one_id = owner_one.id
        owned_ids = {
            product.id for product in products if product.user_id == owner_one_id
        }

    assert summary.total_urls == 0
    assert set(service.calls) == owned_ids
