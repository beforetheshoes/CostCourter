from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl, ValidationError
from pydantic.type_adapter import TypeAdapter
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import app.models as models
from app.api import deps as api_deps
from app.core.config import settings
from app.main import app
from app.schemas import (
    PriceHistoryCreate,
    ProductCreate,
    ProductURLCreate,
    ProductURLUpdate,
    StoreCreate,
    StoreDomain,
)
from app.services import catalog as catalog_service
from app.services import product_quick_add

_HTTP_URL = TypeAdapter(HttpUrl)


class _ScraperStubFactory:
    def __init__(self, payloads: dict[Any, Any | Exception]) -> None:
        self._payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def __call__(self) -> _ScraperStubClient:
        return _ScraperStubClient(self._payloads, self.calls)


class _ScraperStubClient:
    def __init__(
        self,
        payloads: dict[Any, Any | Exception],
        calls: list[dict[str, Any]],
    ) -> None:
        self._payloads = payloads
        self._calls = calls
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _ScraperStubClient:
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
        timeout: Any | None = None,
    ) -> httpx.Response:
        target = json.get("url")
        self._calls.append(
            {"method": "POST", "url": url, "json": json, "timeout": timeout}
        )
        payload = self._resolve_payload("POST", url, target)
        if isinstance(payload, Exception):
            raise payload
        request = httpx.Request("POST", url, json=json)
        if isinstance(payload, httpx.Response):
            return payload
        if isinstance(payload, dict):
            return httpx.Response(status_code=200, json=payload, request=request)
        if isinstance(payload, str):
            return httpx.Response(status_code=200, text=payload, request=request)
        raise TypeError("Unsupported payload type for POST")

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._calls.append(
            {
                "method": "GET",
                "url": url,
                "timeout": timeout,
                "headers": headers,
                "params": params,
                "stored_headers": dict(self.headers),
            }
        )
        target = params.get("url") if params else None
        payload = self._resolve_payload("GET", url, target)
        if isinstance(payload, Exception):
            raise payload
        request = httpx.Request("GET", url)
        if isinstance(payload, httpx.Response):
            return payload
        if isinstance(payload, dict):
            return httpx.Response(status_code=200, json=payload, request=request)
        if isinstance(payload, str):
            return httpx.Response(status_code=200, text=payload, request=request)
        if payload is None:
            return httpx.Response(status_code=200, request=request, text="")
        raise TypeError("Unsupported payload type for GET")

    def _resolve_payload(
        self, method: str, request_url: str, target: str | None
    ) -> Any | Exception | None:
        keys: list[Any] = []
        if target is not None:
            keys.extend(
                [
                    (method, request_url, target),
                    (method, target),
                    f"{method}:{target}",
                    target,
                ]
            )
        keys.extend(
            [
                (method, request_url),
                f"{method}:{request_url}",
                request_url,
            ]
        )
        for key in keys:
            if key in self._payloads:
                return self._payloads[key]
        raise KeyError(f"No stub payload registered for {target or request_url}")


class _RecorderDispatcher:
    def __init__(self) -> None:
        self.product_ids: list[int] = []

    def enqueue(self, product_id: int) -> None:
        self.product_ids.append(product_id)


@pytest.fixture
def capture_price_refresh() -> Iterator[_RecorderDispatcher]:
    dispatcher = _RecorderDispatcher()

    def dependency() -> _RecorderDispatcher:
        return dispatcher

    app.dependency_overrides[api_deps.get_price_refresh_dispatcher] = dependency
    try:
        yield dispatcher
    finally:
        app.dependency_overrides.pop(api_deps.get_price_refresh_dispatcher, None)


@pytest.fixture
def set_scraper_base() -> Iterator[None]:
    previous = settings.scraper_base_url
    settings.scraper_base_url = "https://scraper.test"
    try:
        yield
    finally:
        settings.scraper_base_url = previous


def test_quick_add_by_url_creates_resources(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    full_html = (
        '<div id="productTitle">Example Product</div>'
        '<span class="a-offscreen">$129.99</span>'
        '<script>var data = {"hiRes":"https://img.example.com/p.png"};</script>'
    )
    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://example.com/items/widget",
            ): {
                "title": "Example Product",
                "excerpt": "An example product",
                "lang": "en_US",
                "meta": {"product:price:currency": "EUR"},
                "fullContent": full_html,
            }
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Example Product"
    assert payload["price"] == "129.99"
    assert payload["currency"] == "EUR"
    assert payload["warnings"] == []
    assert scraper_factory.calls
    first_call = scraper_factory.calls[0]
    assert first_call["url"].endswith("/api/article")
    assert first_call["params"]["url"] == "https://example.com/items/widget"

    with Session(engine) as session:
        stores = session.exec(select(models.Store)).all()
        products = session.exec(select(models.Product)).all()
        urls = session.exec(select(models.ProductURL)).all()
        history = session.exec(select(models.PriceHistory)).all()
        audit_entries = session.exec(select(models.AuditLog)).all()

    assert len(stores) == 1
    assert stores[0].slug == "example-com"
    assert stores[0].domains == [
        {"domain": "example.com"},
        {"domain": "www.example.com"},
    ]
    title_strategy = stores[0].scrape_strategy["title"]
    price_strategy = stores[0].scrape_strategy["price"]
    image_strategy = stores[0].scrape_strategy["image"]
    assert title_strategy["type"] == "css"
    assert title_strategy["value"] == "#productTitle"
    assert title_strategy["data"] == "Example Product"
    assert price_strategy["type"] == "css"
    assert price_strategy["value"] == "span.a-offscreen"
    assert price_strategy["data"] == "129.99"
    assert image_strategy["type"] == "regex"
    assert "hiRes" in image_strategy["value"]
    assert image_strategy["data"] == "https://img.example.com/p.png"
    assert stores[0].settings["test_url"] == "https://example.com/items/widget"
    assert stores[0].settings["scraper_service"] == "http"
    assert stores[0].settings["locale_settings"]["currency"] == "EUR"
    assert len(products) == 1
    product = products[0]
    assert product.slug == "example-product"
    assert product.image_url == "https://img.example.com/p.png"
    assert product.current_price == pytest.approx(129.99)
    assert product.price_cache
    assert product.price_cache[0]["price"] == pytest.approx(129.99)
    assert product.price_cache[0]["trend"] == "lowest"
    assert len(urls) == 1
    assert urls[0].is_primary is True
    assert len(history) == 1
    assert history[0].price == pytest.approx(129.99)
    assert history[0].currency == "EUR"
    assert capture_price_refresh.product_ids == [products[0].id]

    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "product.quick_add"
    assert audit.actor_id == admin_user.id
    context = audit.context
    assert isinstance(context, dict)
    assert context["source_url"] == "https://example.com/items/widget"
    price_observed = context.get("price_observed")
    assert isinstance(price_observed, float)
    assert price_observed == pytest.approx(129.99)
    assert audit.ip_address == "testclient"


def test_quick_add_by_url_falls_back_without_scrape(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    request = httpx.Request(
        "GET",
        "https://scraper.test/api/article",
        params={"url": "https://example.com/items/widget"},
    )
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://example.com/items/widget",
            ): error,
            ("GET", "https://example.com/items/widget"): "",
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "example.com"
    assert payload["price"] is None
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    assert any("Scraper" in warning for warning in warnings)
    assert any("No metadata" in warning for warning in warnings)

    with Session(engine) as session:
        history = session.exec(select(models.PriceHistory)).all()
        store = session.exec(select(models.Store)).one()
        audit_entries = session.exec(select(models.AuditLog)).all()
    assert history == []
    assert store.domains == [
        {"domain": "example.com"},
        {"domain": "www.example.com"},
    ]
    assert store.scrape_strategy["title"]["type"] == "fallback"
    assert store.settings["locale_settings"]["currency"] == "USD"
    assert capture_price_refresh.product_ids == [payload["product_id"]]
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "product.quick_add"
    assert audit.actor_id == admin_user.id
    context = audit.context
    assert isinstance(context, dict)
    assert context.get("price_observed") is None
    assert isinstance(context.get("warnings"), list)
    assert any(
        "Scraper" in warning for warning in cast(list[str], context.get("warnings", []))
    )


def test_quick_add_updates_existing_store_domains(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://example.com/items/widget",
            ): {
                "title": "Existing Product",
                "excerpt": "Existing description",
                "lang": "en_US",
                "meta": {"product:price:currency": "USD"},
                "fullContent": (
                    '<div id="productTitle">Existing Product</div>'
                    '<span class="a-offscreen">$15.00</span>'
                ),
            }
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )

    with Session(engine) as session:
        store = models.Store(
            user_id=admin_user.id,
            name="Example",
            slug="example-com",
            domains=[],
            scrape_strategy={},
            settings={},
        )
        session.add(store)
        session.commit()
        session.refresh(store)
        store_id = store.id

    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
    assert response.status_code == 201
    payload = response.json()
    assert payload["store_id"] == store_id

    with Session(engine) as session:
        store = session.exec(select(models.Store)).one()
        assert store.id == store_id
        assert {entry["domain"] for entry in store.domains} == {
            "example.com",
            "www.example.com",
        }
        assert store.scrape_strategy
        assert store.settings["locale_settings"]["currency"] == "USD"

    assert capture_price_refresh.product_ids == [payload["product_id"]]


def test_quick_add_reactivates_existing_product(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
) -> None:
    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://example.com/items/widget",
            ): {
                "title": "Existing Product",
                "lang": "en_US",
                "meta": {"product:price:currency": "USD"},
                "fullContent": ('<div id="productTitle">Existing Product</div>'),
            }
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )

    with Session(engine) as session:
        product = models.Product(
            user_id=admin_user.id,
            name="Existing Product",
            slug="existing-product",
            favourite=False,
            is_active=False,
        )
        session.add(product)
        session.commit()
        session.refresh(product)

    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    warnings = payload["warnings"]
    assert any("favourite" in warning.lower() for warning in warnings)
    assert any("reactivated" in warning.lower() for warning in warnings)

    with Session(engine) as session:
        product = session.exec(select(models.Product)).one()
        assert product.favourite is True
        assert product.is_active is True
        audit = session.exec(select(models.AuditLog)).one()
    assert isinstance(audit.context, dict)
    context_warnings = cast(list[str], audit.context.get("warnings", []))
    assert any("favourite" in warning.lower() for warning in context_warnings)


def test_quick_add_handles_host_without_tld(
    client: TestClient,
    engine: Engine,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://store.local/product",
            ): {},
            ("GET", "https://store.local/product"): "",
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )

    adapter = product_quick_add.HTTP_URL_ADAPTER
    original_validate = adapter.validate_python

    validation_error = pytest.raises(
        ValidationError, original_validate, "invalid"
    ).value

    def fail_validation(
        value: Any,
        /,
        *,
        strict: bool | None = None,
        from_attributes: bool | None = None,
    ) -> HttpUrl:
        if value == "https://store.local":
            raise validation_error
        return original_validate(value, strict=strict, from_attributes=from_attributes)

    cast(Any, adapter).validate_python = fail_validation
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://store.local/product"},
            headers=admin_auth_headers,
        )
    finally:
        cast(Any, adapter).validate_python = original_validate
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "store.local"

    with Session(engine) as session:
        store = session.exec(select(models.Store)).one()
    assert store.website_url is None
    assert store.domains == [
        {"domain": "store.local"},
        {"domain": "www.store.local"},
    ]


def test_quick_add_handles_price_refresh_failure(
    client: TestClient,
    engine: Engine,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
) -> None:
    responses: dict[Any, Any | Exception] = {
        (
            "GET",
            "https://scraper.test/api/article",
            "https://example.com/items/widget",
        ): {
            "title": "Example Product",
            "excerpt": "Example description",
            "lang": "en_US",
            "meta": {"product:price:currency": "EUR"},
            "fullContent": (
                '<div id="productTitle">Example Product</div>'
                '<span class="a-offscreen">$129.99</span>'
                '<script>var data = {"hiRes":"https://img.example.com/p.png"};</script>'
            ),
        }
    }
    scraper_factory = _ScraperStubFactory(responses)

    class _FailingDispatcher:
        def enqueue(self, product_id: int) -> None:
            raise RuntimeError("unavailable")

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    app.dependency_overrides[api_deps.get_price_refresh_dispatcher] = (
        lambda: _FailingDispatcher()
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
        app.dependency_overrides.pop(api_deps.get_price_refresh_dispatcher, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Example Product"
    assert any("Failed to enqueue price refresh" in w for w in payload["warnings"])

    with Session(engine) as session:
        product = session.exec(select(models.Product)).one()
        assert product.id == payload["product_id"]


def test_quick_add_reuses_existing_image_when_metadata_missing(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    title = "Satechi Qi2 Trio Wireless Charging Pad ST-QTPM-EA"
    existing_image = "https://cdn.example.com/satechi-trio.png"
    responses: dict[Any, Any | Exception] = {
        (
            "GET",
            "https://scraper.test/api/article",
            "https://bhphotovideo.com/c/product/1763075-REG/satechi_st_qtpmp_eu_qi2_trio_wireless_charging.html",
        ): {
            "title": title,
            "excerpt": "Three-in-one Qi2 charger",
            "lang": "en_US",
            "meta": {"product:price:currency": "USD"},
            "fullContent": (
                '<div id="productTitle">Satechi Qi2 Trio Wireless Charging Pad ST-QTPM-EA</div>'
                '<span class="price">$149.99</span>'
            ),
        }
    }
    scraper_factory = _ScraperStubFactory(responses)
    slug = product_quick_add._slugify(title)

    with Session(engine) as session:
        product = models.Product(
            user_id=admin_user.id,
            name=title,
            slug=slug,
            description=None,
            image_url=existing_image,
            favourite=True,
            is_active=True,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.id

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={
                "url": "https://bhphotovideo.com/c/product/1763075-REG/satechi_st_qtpmp_eu_qi2_trio_wireless_charging.html"
            },
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["product_id"] == product_id
    assert payload["image"] == existing_image
    assert capture_price_refresh.product_ids == [product_id]

    with Session(engine) as session:
        product = session.exec(select(models.Product)).one()
        assert product.image_url == existing_image


def test_quick_add_detects_bhphotovideo_price(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    url = (
        "https://www.bhphotovideo.com/c/product/1763075-REG/"
        "satechi_st_qtpmp_eu_qi2_trio_wireless_charging.html"
    )
    html = (
        '<div class="pdp-price">'
        '<span data-selenium="pricingPrice" class="price__value">$149.99</span>'
        "</div>"
    )
    responses: dict[Any, Any | Exception] = {
        ("GET", "https://scraper.test/api/article", url): {
            "title": "Satechi Qi2 Trio Wireless Charging Pad ST-QTPM-EA",
            "excerpt": "Three-in-one Qi2 charger",
            "lang": "en_US",
            "meta": {"og:image": "https://img.example.com/satechi.png"},
            "fullContent": html,
        }
    }
    scraper_factory = _ScraperStubFactory(responses)

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": url},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["price"] == "149.99"
    assert payload["currency"] == "USD"
    assert capture_price_refresh.product_ids == [payload["product_id"]]

    with Session(engine) as session:
        product = session.exec(
            select(models.Product).where(models.Product.id == payload["product_id"])
        ).one()
        history = session.exec(select(models.PriceHistory)).all()
        store = session.exec(
            select(models.Store).where(models.Store.id == payload["store_id"])
        ).one()

    assert product.current_price == pytest.approx(149.99)
    assert history
    assert history[0].price == pytest.approx(149.99)
    assert history[0].currency == "USD"
    price_strategy = store.scrape_strategy["price"]
    assert price_strategy["data"] == "149.99"
    assert price_strategy["value"] in {
        'span[data-selenium="pricingPrice"]',
        'span[data-selenium="pricingCurrentPrice"]',
        'span[data-selenium="pricingSalePrice"]',
        "span.price__value",
    }


def test_quick_add_extracts_price_from_json_ld(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    url = "https://www.apple.com/shop/product/HRXC2ZM/B/nimble-podium-3-in-1-wireless-charger"
    ld_payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Nimble Podium 3-in-1 Wireless Charger",
        "offers": [
            {
                "@type": "Offer",
                "price": 139.95,
                "priceCurrency": "USD",
            }
        ],
    }
    html = (
        '<html><head><script type="application/ld+json">'
        f"{json.dumps(ld_payload)}"
        "</script></head><body><h1>Nimble Podium 3-in-1 Wireless Charger</h1></body></html>"
    )
    responses: dict[Any, Any | Exception] = {
        ("GET", "https://scraper.test/api/article", url): {
            "title": "Nimble Podium 3-in-1 Wireless Charger",
            "excerpt": "Charge multiple devices at once",
            "lang": "en_US",
            "meta": {"og:image": "https://img.example.com/nimble.png"},
            "fullContent": html,
        }
    }
    scraper_factory = _ScraperStubFactory(responses)

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": url},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["price"] == "139.95"
    assert payload["currency"] == "USD"
    assert capture_price_refresh.product_ids == [payload["product_id"]]

    with Session(engine) as session:
        product = session.exec(
            select(models.Product).where(models.Product.id == payload["product_id"])
        ).one()
        history = session.exec(select(models.PriceHistory)).all()

    assert product.current_price == pytest.approx(139.95)
    assert history
    assert history[0].price == pytest.approx(139.95)
    assert history[0].currency == "USD"


def test_product_detail_includes_url_prices(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    bh_url = (
        "https://www.bhphotovideo.com/c/product/1763075-REG/"
        "satechi_st_qtpmp_eu_qi2_trio_wireless_charging.html"
    )
    amazon_url = "https://www.amazon.com/dp/B0CZY2D5G3?tag=affiliate-20"
    responses: dict[Any, Any | Exception] = {
        ("GET", "https://scraper.test/api/article", bh_url): {
            "title": "Satechi Qi2 Trio Wireless Charging Pad ST-QTPM-EA",
            "excerpt": "Three-in-one Qi2 charger",
            "lang": "en_US",
            "meta": {"og:image": "https://img.example.com/satechi.png"},
            "fullContent": (
                '<div class="pdp-price">'
                '<span data-selenium="pricingPrice" class="price__value">$149.99</span>'
                "</div>"
            ),
        },
        ("GET", "https://scraper.test/api/article", amazon_url): {
            "title": "Satechi Qi2 Trio Wireless Charging Pad ST-QTPM-EA",
            "excerpt": "MagSafe compatible charger",
            "lang": "en_US",
            "meta": {"product:price:currency": "usd"},
            "fullContent": (
                '<span class="a-price">'
                '<span class="a-offscreen">$129.99</span>'
                "</span>"
            ),
        },
    }
    scraper_factory = _ScraperStubFactory(responses)

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response_primary = client.post(
            "/api/product-urls/quick-add",
            json={"url": bh_url},
            headers=admin_auth_headers,
        )
        assert response_primary.status_code == 201
        payload_primary = response_primary.json()

        response_amazon = client.post(
            "/api/product-urls/quick-add",
            json={"url": amazon_url},
            headers=admin_auth_headers,
        )
        assert response_amazon.status_code == 201
        payload_amazon = response_amazon.json()
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert capture_price_refresh.product_ids == [
        payload_primary["product_id"],
        payload_amazon["product_id"],
    ]

    detail_response = client.get(
        f"/api/products/{payload_primary['product_id']}",
        headers=admin_auth_headers,
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()

    urls = {entry["url"]: entry for entry in detail["urls"]}
    assert bh_url in urls and amazon_url in urls
    assert urls[bh_url]["latest_price"] == pytest.approx(149.99)
    assert urls[bh_url]["latest_price_currency"] == "USD"
    assert urls[amazon_url]["latest_price"] == pytest.approx(129.99)
    assert urls[amazon_url]["latest_price_currency"] == "USD"
    assert urls[bh_url]["latest_price_at"] is not None
    assert urls[amazon_url]["latest_price_at"] is not None

    price_cache = detail["price_cache"]
    assert isinstance(price_cache, list)
    assert {entry["url"] for entry in price_cache if entry["url"]} >= {
        bh_url,
        amazon_url,
    }


def test_quick_add_recovers_metadata_from_direct_fetch(
    client: TestClient,
    engine: Engine,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
) -> None:
    html = """
    <html>
      <head>
        <title>Example Widget</title>
        <meta property=\"og:image\" content=\"https://img.example.com/widget.png\" />
        <meta property=\"product:price:amount\" content=\"199.50\" />
        <meta property=\"product:price:currency\" content=\"usd\" />
      </head>
      <body></body>
    </html>
    """

    request = httpx.Request(
        "GET",
        "https://scraper.test/api/article",
        params={"url": "https://example.com/items/widget"},
    )
    error_response = httpx.Response(404, request=request)
    http_error = httpx.HTTPStatusError(
        "not found", request=request, response=error_response
    )

    scraper_factory = _ScraperStubFactory(
        {
            (
                "GET",
                "https://scraper.test/api/article",
                "https://example.com/items/widget",
            ): http_error,
            ("GET", "https://example.com/items/widget"): html,
        }
    )
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/quick-add",
            json={"url": "https://example.com/items/widget"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Example Widget"
    assert payload["price"] == "199.50"
    assert payload["image"] == "https://img.example.com/widget.png"

    with Session(engine) as session:
        product = session.exec(select(models.Product)).one()
        assert product.name == "Example Widget"
        assert product.current_price == pytest.approx(199.50)
        assert product.image_url == "https://img.example.com/widget.png"


def test_parse_scraper_payload_prefers_secure_image_url() -> None:
    payload = {
        "meta": {
            "og:image": "http://cdn.example.com/image.jpg",
            "og:image:secure_url": "https://cdn.example.com/image.jpg",
        }
    }

    result = product_quick_add._parse_scraper_payload(
        "https://example.com/product", payload
    )

    assert result["image"] == "https://cdn.example.com/image.jpg"


def test_parse_scraper_payload_normalizes_protocol_relative_image_url() -> None:
    payload = {
        "meta": {"og:image": "//cdn.example.com/asset.png"},
    }

    result = product_quick_add._parse_scraper_payload(
        "https://example.com/product", payload
    )

    assert result["image"] == "https://cdn.example.com/asset.png"


def test_bulk_import_creates_new_product_and_urls(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
    capture_price_refresh: _RecorderDispatcher,
) -> None:
    responses: dict[Any, Any | Exception] = {
        (
            "GET",
            "https://scraper.test/api/article",
            "https://example.com/products/headphones",
        ): {
            "title": "Noise Cancelling Headphones",
            "excerpt": "Primary listing",
            "lang": "en_US",
            "meta": {"product:price:currency": "USD"},
            "fullContent": (
                '<div id="productTitle">Noise Cancelling Headphones</div>'
                '<span class="a-offscreen">$199.99</span>'
                '<script>var data={"hiRes":"https://img.example.com/headphones.png"};</script>'
            ),
        },
        (
            "GET",
            "https://scraper.test/api/article",
            "https://alt.example.org/product/sku",
        ): {
            "title": "Noise Cancelling Headphones",
            "excerpt": "Alternate listing",
            "lang": "en_US",
            "meta": {"product:price:currency": "USD"},
            "fullContent": (
                '<div id="productTitle">Noise Cancelling Headphones</div>'
                '<span class="a-offscreen">$189.50</span>'
                '<script>var data={"hiRes":"https://img.example.com/headphones-alt.png"};</script>'
            ),
        },
    }
    scraper_factory = _ScraperStubFactory(responses)
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/bulk-import",
            json={
                "search_query": "Noise Cancelling Headphones",
                "enqueue_refresh": True,
                "items": [
                    {
                        "url": "https://example.com/products/headphones",
                        "set_primary": True,
                    },
                    {"url": "https://alt.example.org/product/sku"},
                ],
            },
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["created_product"] is True
    assert payload["product_name"] == "Noise Cancelling Headphones"
    assert len(payload["created_urls"]) == 2
    assert payload["created_urls"][0]["is_primary"] is True
    assert payload["created_urls"][1]["is_primary"] is False
    assert payload["skipped"] == []

    with Session(engine) as session:
        products = session.exec(select(models.Product)).all()
        stores = session.exec(select(models.Store)).all()
        urls = session.exec(select(models.ProductURL)).all()
        history = session.exec(select(models.PriceHistory)).all()
        audit_entries = session.exec(select(models.AuditLog)).all()

    assert len(products) == 1
    product = products[0]
    assert product.slug == "noise-cancelling-headphones"
    assert product.image_url == "https://img.example.com/headphones.png"
    assert len(product.price_cache) == 2
    assert product.price_cache[0]["price"] == pytest.approx(189.50)
    assert product.price_cache[1]["price"] == pytest.approx(199.99)
    assert len(stores) == 2
    assert {s.slug for s in stores} == {"example-com", "alt-example-org"}
    assert len(urls) == 2
    assert sum(1 for url in urls if url.is_primary) == 1
    assert len(history) == 2
    assert capture_price_refresh.product_ids == [payload["product_id"]]

    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "product.bulk_import"
    assert audit.actor_id == admin_user.id
    context = audit.context
    assert isinstance(context, dict)
    assert context.get("created_product") is True
    created_count = context.get("created_count")
    assert isinstance(created_count, int)
    assert created_count == 2
    created_urls = context.get("created_urls")
    assert isinstance(created_urls, list)
    assert len(created_urls) == 2


def test_bulk_import_appends_to_existing_product(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
) -> None:
    with Session(engine) as session:
        owner = session.get(models.User, admin_user.id)
        assert owner is not None
        store_read = catalog_service.create_store(
            session,
            payload=StoreCreate(
                name="Example",
                slug="example-com",
                domains=[StoreDomain(domain="example.com")],
                scrape_strategy={},
                settings={},
            ),
            owner=owner,
        )
        store = session.get(models.Store, store_read.id)
        assert store is not None
        assert store.id is not None
        product_read = catalog_service.create_product(
            session,
            payload=ProductCreate(
                name="Existing Product",
                slug="existing-product",
                description=None,
                is_active=True,
            ),
            owner=owner,
        )
        product = session.get(models.Product, product_read.id)
        assert product is not None
        assert product.id is not None
        product.image_url = None
        session.add(product)
        product_url_read = catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=store.id,
                url=_HTTP_URL.validate_python("https://example.com/items/widget"),
                is_primary=True,
                active=True,
            ),
            owner=owner,
        )
        catalog_service.create_price_history(
            session,
            payload=PriceHistoryCreate(
                product_id=product.id,
                product_url_id=product_url_read.id,
                price=210.0,
                currency="USD",
            ),
            owner=owner,
        )
        session.refresh(product)

    responses: dict[Any, Any | Exception] = {
        (
            "GET",
            "https://scraper.test/api/article",
            "https://alt.example.org/product/sku",
        ): {
            "title": "Existing Product",
            "excerpt": "Alternate listing",
            "lang": "en_US",
            "meta": {"product:price:currency": "USD"},
            "fullContent": (
                '<div id="productTitle">Existing Product</div>'
                '<span class="a-offscreen">$205.00</span>'
                '<script>var data={"hiRes":"https://img.example.com/new.png"};</script>'
            ),
        }
    }
    scraper_factory = _ScraperStubFactory(responses)
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/bulk-import",
            json={
                "product_id": product.id,
                "items": [
                    {
                        "url": "https://alt.example.org/product/sku",
                        "set_primary": True,
                    }
                ],
            },
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_product"] is False
    assert len(payload["created_urls"]) == 1
    created = payload["created_urls"][0]
    assert created["is_primary"] is True
    assert payload["skipped"] == []

    with Session(engine) as session:
        product = session.exec(select(models.Product)).one()
        urls = session.exec(select(models.ProductURL)).all()
        audit_entries = session.exec(select(models.AuditLog)).all()
        assert len(urls) == 2
        assert sum(1 for url in urls if url.is_primary) == 1
        assert product.image_url == "https://img.example.com/new.png"
    assert len(product.price_cache) == 2
    assert product.price_cache[0]["price"] == pytest.approx(205.0)
    assert product.price_cache[1]["price"] == pytest.approx(210.0)

    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "product.bulk_import"
    assert audit.actor_id == admin_user.id
    context = audit.context
    assert isinstance(context, dict)
    assert context.get("created_product") is False
    created_count = context.get("created_count")
    assert isinstance(created_count, int)
    assert created_count == 1


def test_bulk_import_skips_duplicate_urls(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    set_scraper_base: None,
) -> None:
    with Session(engine) as session:
        owner = session.get(models.User, admin_user.id)
        assert owner is not None
        store_read = catalog_service.create_store(
            session,
            payload=StoreCreate(
                name="Example",
                slug="example-com",
                domains=[StoreDomain(domain="example.com")],
                scrape_strategy={},
                settings={},
            ),
            owner=owner,
        )
        product_read = catalog_service.create_product(
            session,
            payload=ProductCreate(
                name="Existing Product",
                slug="existing-product",
                description=None,
                is_active=True,
            ),
            owner=owner,
        )
        product = session.get(models.Product, product_read.id)
        store = session.get(models.Store, store_read.id)
        assert product is not None and store is not None
        assert product.id is not None and store.id is not None
        catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=store.id,
                url=_HTTP_URL.validate_python("https://example.com/items/widget"),
                is_primary=True,
                active=True,
            ),
            owner=owner,
        )
        session.refresh(product)

    responses: dict[Any, Any | Exception] = {
        (
            "GET",
            "https://scraper.test/api/article",
            "https://example.com/items/widget",
        ): {
            "title": "Existing Product",
            "excerpt": "Duplicate listing",
            "lang": "en_US",
            "meta": {"product:price:currency": "USD"},
            "fullContent": (
                '<div id="productTitle">Existing Product</div>'
                '<span class="a-offscreen">$210.00</span>'
            ),
        }
    }
    scraper_factory = _ScraperStubFactory(responses)
    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    try:
        response = client.post(
            "/api/product-urls/bulk-import",
            json={
                "product_id": product.id,
                "items": [
                    {
                        "url": "https://example.com/items/widget",
                        "set_primary": True,
                    }
                ],
            },
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_product"] is False
    assert payload["created_urls"] == []
    assert payload["skipped"] == [
        {"url": "https://example.com/items/widget", "reason": "duplicate"}
    ]

    with Session(engine) as session:
        urls = session.exec(select(models.ProductURL)).all()
        audit_entries = session.exec(select(models.AuditLog)).all()
        assert len(urls) == 1
        assert urls[0].is_primary is True

    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "product.bulk_import"
    assert audit.actor_id == admin_user.id
    context = audit.context
    assert isinstance(context, dict)
    created_count = context.get("created_count")
    assert isinstance(created_count, int)
    assert created_count == 0
    skipped_entries = context.get("skipped")
    assert isinstance(skipped_entries, list)
    assert skipped_entries and isinstance(skipped_entries[0], dict)
    assert skipped_entries[0].get("reason") == "duplicate"


def test_create_product_url_promotes_single_primary(
    engine: Engine,
    admin_user: models.User,
) -> None:
    with Session(engine) as session:
        owner = session.get(models.User, admin_user.id)
        assert owner is not None

        first_store = catalog_service.create_store(
            session,
            payload=StoreCreate(
                name="Primary Store",
                slug="primary-store",
                domains=[StoreDomain(domain="primary.test")],
                scrape_strategy={},
                settings={},
            ),
            owner=owner,
        )
        second_store = catalog_service.create_store(
            session,
            payload=StoreCreate(
                name="Secondary Store",
                slug="secondary-store",
                domains=[StoreDomain(domain="secondary.test")],
                scrape_strategy={},
                settings={},
            ),
            owner=owner,
        )

        product = catalog_service.create_product(
            session,
            payload=ProductCreate(
                name="Tracked Product",
                slug="tracked-product",
                description=None,
                is_active=True,
            ),
            owner=owner,
        )

        first_url = catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=first_store.id,
                url=_HTTP_URL.validate_python("https://primary.test/item"),
                is_primary=True,
                active=True,
            ),
            owner=owner,
        )
        second_url = catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=second_store.id,
                url=_HTTP_URL.validate_python("https://secondary.test/item"),
                is_primary=True,
                active=True,
            ),
            owner=owner,
        )

        first_instance = session.get(models.ProductURL, first_url.id)
        second_instance = session.get(models.ProductURL, second_url.id)
        assert first_instance is not None
        assert second_instance is not None
        assert first_instance.is_primary is False
        assert second_instance.is_primary is True


def test_update_product_url_replaces_existing_primary(
    engine: Engine,
    admin_user: models.User,
) -> None:
    with Session(engine) as session:
        owner = session.get(models.User, admin_user.id)
        assert owner is not None

        store = catalog_service.create_store(
            session,
            payload=StoreCreate(
                name="Example Store",
                slug="example-store",
                domains=[StoreDomain(domain="example.test")],
                scrape_strategy={},
                settings={},
            ),
            owner=owner,
        )

        product = catalog_service.create_product(
            session,
            payload=ProductCreate(
                name="Another Product",
                slug="another-product",
                description=None,
                is_active=True,
            ),
            owner=owner,
        )

        primary_url = catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=store.id,
                url=_HTTP_URL.validate_python("https://example.test/primary"),
                is_primary=True,
                active=True,
            ),
            owner=owner,
        )
        secondary_url = catalog_service.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product.id,
                store_id=store.id,
                url=_HTTP_URL.validate_python("https://example.test/secondary"),
                is_primary=False,
                active=True,
            ),
            owner=owner,
        )

        updated = catalog_service.update_product_url(
            session,
            secondary_url.id,
            ProductURLUpdate(is_primary=True),
            owner=owner,
        )

        primary_instance = session.get(models.ProductURL, primary_url.id)
        secondary_instance = session.get(models.ProductURL, updated.id)
        assert primary_instance is not None
        assert secondary_instance is not None
        assert primary_instance.is_primary is False
        assert secondary_instance.is_primary is True
