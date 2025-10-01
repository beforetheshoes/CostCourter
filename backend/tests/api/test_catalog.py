from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import HttpUrl
from sqlalchemy import Table
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import app.models as models
from app.api import deps as api_deps
from app.core.config import settings
from app.main import app
from app.models.product import ProductStatus
from app.services import catalog
from app.services.price_cache import rebuild_product_price_cache


class _StoreQuickAddStubFactory:
    def __init__(self, payloads: dict[tuple[str, str, str | None], Any]) -> None:
        self._payloads = payloads

    def __call__(self) -> _StoreQuickAddStubClient:
        return _StoreQuickAddStubClient(self._payloads)


class _StoreQuickAddStubClient:
    def __init__(self, payloads: dict[tuple[str, str, str | None], Any]) -> None:
        self._payloads = payloads
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _StoreQuickAddStubClient:
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
        params: dict[str, Any] | None = None,
        timeout: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        _ = timeout, headers  # parameters unused by stub
        target = params.get("url") if params else None
        payload = self._payloads.get(("GET", url, target))
        if payload is None:
            payload = self._payloads.get(("GET", url, None))
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, httpx.Response):
            return payload
        if isinstance(payload, dict):
            return httpx.Response(
                status_code=200,
                json=payload,
                request=httpx.Request("GET", url),
            )
        if isinstance(payload, str):
            return httpx.Response(
                status_code=200,
                text=payload,
                request=httpx.Request("GET", url),
            )
        return httpx.Response(status_code=200, request=httpx.Request("GET", url))


def test_list_products_with_authenticated_request(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
) -> None:
    """Ensure product listing works with real JWT auth and mapped relationships."""

    store_payload = {
        "name": "Example Store",
        "slug": "example-store",
        "website_url": "https://store.example.com",
    }
    store_response = client.post(
        "/api/stores", json=store_payload, headers=admin_auth_headers
    )
    assert store_response.status_code == 201
    store = store_response.json()

    product_payload = {
        "name": "Widget",
        "slug": "widget",
        "description": "Test widget",
    }
    product_response = client.post(
        "/api/products", json=product_payload, headers=admin_auth_headers
    )
    assert product_response.status_code == 201
    product = product_response.json()

    product_url_response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://store.example.com/widget",
            "is_primary": True,
            "active": True,
            "created_by_id": admin_user.id,
        },
        headers=admin_auth_headers,
    )
    assert product_url_response.status_code == 201

    listing = client.get("/api/products", headers=admin_auth_headers)
    assert listing.status_code == 200
    products = listing.json()
    assert len(products) == 1
    payload = products[0]
    assert payload["slug"] == "widget"
    assert payload["urls"][0]["created_by_id"] == admin_user.id
    assert payload["status"] == "published"
    assert payload["favourite"] is True
    assert payload["price_cache"] == []
    assert payload["ignored_urls"] == []


def test_list_products_handles_legacy_lowercase_status(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
) -> None:
    _ = admin_user
    product_payload = {
        "name": "Legacy Widget",
        "slug": "legacy-widget",
        "description": "Migrated from legacy stack",
    }

    response = client.post(
        "/api/products", json=product_payload, headers=admin_auth_headers
    )
    assert response.status_code == 201
    product = response.json()

    with Session(engine) as session:
        stored = session.get(models.Product, product["id"])
        assert stored is not None
        stored.status = ProductStatus.PUBLISHED
        session.add(stored)
        session.commit()

    listing = client.get(
        "/api/products",
        params={"limit": 10, "offset": 0},
        headers=admin_auth_headers,
    )
    assert listing.status_code == 200
    payloads = listing.json()
    assert any(item["id"] == product["id"] for item in payloads)
    assert (
        next(item for item in payloads if item["id"] == product["id"])["status"]
        == "published"
    )


def test_create_store_and_list(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    payload = {
        "name": "Test Store",
        "slug": "test-store",
        "website_url": "https://example.com",
    }

    response = client.post("/api/stores", json=payload, headers=user_auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["slug"] == payload["slug"]
    assert data["website_url"] == str(HttpUrl(payload["website_url"]))

    listing = client.get("/api/stores", headers=user_auth_headers)
    assert listing.status_code == 200
    stores = listing.json()
    assert len(stores) == 1
    assert stores[0]["slug"] == "test-store"

    with Session(engine) as session:
        store = session.get(models.Store, data["id"])
        assert store is not None
        assert store.slug == payload["slug"]


def test_store_create_and_update_capture_locale_currency_and_strategy(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
) -> None:
    payload = {
        "name": "Selector Store",
        "slug": "selector-store",
        "website_url": "https://selectors.example.com",
        "domains": [
            {"domain": "selectors.example.com"},
            {"domain": "selectors-cdn.example.com"},
        ],
        "scrape_strategy": {
            "title": {"type": "css", "value": ".title", "data": None},
            "price": {"type": "json", "value": "price", "data": None},
        },
        "settings": {
            "scraper_service": "http",
            "locale_settings": {"locale": "en_GB", "currency": "GBP"},
        },
        "locale": "en_GB",
        "currency": "GBP",
        "notes": "Initial import",
    }

    response = client.post("/api/stores", json=payload, headers=admin_auth_headers)

    assert response.status_code == 201
    created = response.json()
    assert created["locale"] == "en_GB"
    assert created["currency"] == "GBP"
    assert created["notes"] == "Initial import"
    assert {entry["domain"] for entry in created["domains"]} == {
        "selectors.example.com",
        "selectors-cdn.example.com",
    }
    assert created["scrape_strategy"]["title"]["type"] == "css"
    assert created["scrape_strategy"]["price"]["value"] == "price"

    update_payload = {
        "locale": "fr_FR",
        "currency": "EUR",
        "notes": "Supports EU selectors",
        "scrape_strategy": {
            "title": {"type": "css", "value": "h1", "data": None},
            "image": {"type": "attr", "value": "img::src", "data": None},
        },
    }

    patch = client.patch(
        f"/api/stores/{created['id']}",
        json=update_payload,
        headers=admin_auth_headers,
    )
    assert patch.status_code == 200
    updated = patch.json()
    assert updated["locale"] == "fr_FR"
    assert updated["currency"] == "EUR"
    assert updated["notes"] == "Supports EU selectors"
    assert set(updated["scrape_strategy"].keys()) == {"title", "image"}
    assert updated["scrape_strategy"]["image"]["type"] == "attr"

    with Session(engine) as session:
        store = session.get(models.Store, created["id"])
        assert store is not None
        assert store.locale == "fr_FR"
        assert store.currency == "EUR"
        assert store.notes == "Supports EU selectors"
        assert store.scrape_strategy["title"]["value"] == "h1"
        assert store.scrape_strategy["image"]["type"] == "attr"


def test_store_quick_add_handles_metadata_failures(
    client: TestClient,
    engine: Engine,
    admin_auth_headers: dict[str, str],
) -> None:
    target_url = "https://www.chewy.com"
    scraper_request = httpx.Request(
        "GET",
        "https://scraper.test/api/article",
        params={"url": target_url, "full-content": "true", "cache": "false"},
    )
    scraper_response = httpx.Response(500, request=scraper_request)
    direct_request = httpx.Request("GET", target_url)
    direct_response = httpx.Response(429, request=direct_request)

    responses = {
        ("GET", "https://scraper.test/api/article", target_url): scraper_response,
        ("GET", target_url, None): direct_response,
    }
    scraper_factory = _StoreQuickAddStubFactory(responses)

    app.dependency_overrides[api_deps.get_scraper_client_factory] = (
        lambda: scraper_factory
    )
    scraper_base_original = settings.scraper_base_url
    settings.scraper_base_url = "https://scraper.test"
    try:
        response = client.post(
            "/api/stores/quick-add",
            json={"website": "www.chewy.com", "currency": "USD"},
            headers=admin_auth_headers,
        )
    finally:
        app.dependency_overrides.pop(api_deps.get_scraper_client_factory, None)
        settings.scraper_base_url = scraper_base_original

    assert response.status_code == 201
    payload = response.json()
    assert payload["store"]["slug"] == "chewy-com"
    assert payload["store"]["currency"] == "USD"
    assert payload["store"]["name"] == "Chewy"
    assert payload["warnings"]
    assert any(
        "Scraper responded with HTTP 500" in warning for warning in payload["warnings"]
    )
    assert any(
        "Direct fetch returned HTTP 429" in warning for warning in payload["warnings"]
    )

    with Session(engine) as session:
        stores = session.exec(select(models.Store)).all()
    assert len(stores) == 1
    stored = stores[0]
    assert stored.slug == "chewy-com"
    assert stored.currency == "USD"
    assert {entry.get("domain") for entry in stored.domains} == {
        "chewy.com",
        "www.chewy.com",
    }


def test_create_tag_and_list(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    payload = {"name": "Electronics", "slug": "electronics"}

    response = client.post("/api/tags", json=payload, headers=user_auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "electronics"

    listing = client.get("/api/tags", headers=user_auth_headers)
    assert listing.status_code == 200
    tags = listing.json()
    assert tags == [data]

    with Session(engine) as session:
        tag = session.get(models.Tag, data["id"])
        assert tag is not None
        assert tag.slug == payload["slug"]


def test_create_product_with_tags(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    tag_response = client.post(
        "/api/tags",
        json={"name": "Electronics", "slug": "electronics"},
        headers=user_auth_headers,
    )
    assert tag_response.status_code == 201
    payload = {
        "name": "Noise Cancelling Headphones",
        "slug": "noise-cancelling-headphones",
        "description": "High quality wireless headphones",
        "tag_slugs": ["electronics"],
    }

    response = client.post("/api/products", json=payload, headers=user_auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == payload["slug"]
    assert len(data["tags"]) == 1
    tag_payload = data["tags"][0]
    assert tag_payload["name"] == "Electronics"
    assert tag_payload["slug"] == "electronics"
    assert data["status"] == "published"
    assert data["favourite"] is True

    listing = client.get("/api/products", headers=user_auth_headers)
    assert listing.status_code == 200
    products = listing.json()
    assert len(products) == 1
    assert products[0]["tags"][0]["slug"] == "electronics"


def test_create_product_requires_existing_tags(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    payload = {
        "name": "Smart Watch",
        "slug": "smart-watch",
        "tag_slugs": ["wearables"],
    }

    response = client.post("/api/products", json=payload, headers=user_auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Tag 'wearables' not found"


def test_product_listing_scoped_to_current_user(
    client: TestClient,
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
) -> None:
    # Default client header belongs to user A
    client.post(
        "/api/products",
        json={"name": "Owner A Product", "slug": "owner-a"},
    )

    other_user = create_user(email="other@example.com")
    other_headers = make_auth_headers(other_user)

    client.post(
        "/api/products",
        json={"name": "Owner B Product", "slug": "owner-b"},
        headers=other_headers,
    )

    mine = client.get("/api/products")
    assert [item["slug"] for item in mine.json()] == ["owner-a"]

    theirs = client.get("/api/products", headers=other_headers)
    assert [item["slug"] for item in theirs.json()] == ["owner-b"]


def test_product_listing_includes_multi_store_metadata(
    client: TestClient,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
) -> None:
    store_a = client.post(
        "/api/stores",
        json={
            "name": "Main Store",
            "slug": "main-store",
            "website_url": "https://main.example.com",
            "locale": "en_US",
            "currency": "USD",
        },
        headers=admin_auth_headers,
    ).json()
    store_b = client.post(
        "/api/stores",
        json={
            "name": "EU Store",
            "slug": "eu-store",
            "website_url": "https://eu.example.com",
            "locale": "fr_FR",
            "currency": "EUR",
        },
        headers=admin_auth_headers,
    ).json()

    product = client.post(
        "/api/products",
        json={"name": "Mixer", "slug": "mixer"},
        headers=admin_auth_headers,
    ).json()

    for store, url in (
        (store_a, "https://main.example.com/mixer"),
        (store_b, "https://eu.example.com/mixer"),
    ):
        response = client.post(
            "/api/product-urls",
            json={
                "product_id": product["id"],
                "store_id": store["id"],
                "url": url,
                "is_primary": store["id"] == store_a["id"],
                "active": True,
                "created_by_id": admin_user.id,
            },
            headers=admin_auth_headers,
        )
        assert response.status_code == 201

    listing = client.get("/api/products", headers=admin_auth_headers)
    assert listing.status_code == 200
    [payload] = listing.json()
    assert payload["slug"] == "mixer"
    assert len(payload["urls"]) == 2
    locales = {url["store"]["slug"]: url["store"]["locale"] for url in payload["urls"]}
    currencies = {
        url["store"]["slug"]: url["store"]["currency"] for url in payload["urls"]
    }
    assert locales == {"main-store": "en_US", "eu-store": "fr_FR"}
    assert currencies == {"main-store": "USD", "eu-store": "EUR"}


def test_product_listing_exposes_price_summary_fields(
    client: TestClient,
    engine: Engine,
    admin_auth_headers: dict[str, str],
) -> None:
    store_payload = {
        "name": "Summary Store",
        "slug": "summary-store",
        "website_url": "https://summary.example.com",
    }
    store = client.post(
        "/api/stores",
        json=store_payload,
        headers=admin_auth_headers,
    ).json()

    product = client.post(
        "/api/products",
        json={"name": "Insight Widget", "slug": "insight-widget"},
        headers=admin_auth_headers,
    ).json()

    url = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://summary.example.com/widget",
            "is_primary": True,
            "active": True,
        },
        headers=admin_auth_headers,
    ).json()

    base_time = datetime.now(tz=UTC) - timedelta(days=2)
    with Session(engine) as session:
        persisted_product = session.get(models.Product, product["id"])
        assert persisted_product is not None
        session.add_all(
            [
                models.PriceHistory(
                    product_id=persisted_product.id,
                    product_url_id=url["id"],
                    price=199.99,
                    currency="USD",
                    recorded_at=base_time,
                ),
                models.PriceHistory(
                    product_id=persisted_product.id,
                    product_url_id=url["id"],
                    price=179.50,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=1),
                ),
                models.PriceHistory(
                    product_id=persisted_product.id,
                    product_url_id=url["id"],
                    price=189.00,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=2),
                ),
            ]
        )
        session.commit()
        rebuild_product_price_cache(session, persisted_product)
        session.commit()

    listing = client.get("/api/products", headers=admin_auth_headers)
    listing.raise_for_status()
    [payload] = listing.json()

    assert payload["price_trend"] == "down"
    assert payload["last_refreshed_at"] is not None
    history_points = payload["history_points"]
    assert len(history_points) >= 3
    assert history_points[-1]["price"] == pytest.approx(189.0)

    aggregates = payload["price_aggregates"]
    assert aggregates["min"] == pytest.approx(179.50)
    assert aggregates["max"] == pytest.approx(199.99)
    assert aggregates["avg"] == pytest.approx(189.5)
    assert aggregates["currency"] == "USD"

    [cache_entry] = payload["price_cache"]
    cache_aggregates = cache_entry["aggregates"]
    assert cache_aggregates["min"] == pytest.approx(179.50)
    assert cache_aggregates["max"] == pytest.approx(199.99)
    assert cache_aggregates["avg"] == pytest.approx(189.5)


def test_create_store_conflict(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    payload = {"name": "Store", "slug": "store"}
    first = client.post("/api/stores", json=payload, headers=user_auth_headers)
    assert first.status_code == 201

    conflict = client.post("/api/stores", json=payload, headers=user_auth_headers)

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Store slug already exists"


def test_update_store(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/stores",
        json={
            "name": "Original Store",
            "slug": "original-store",
            "website_url": "https://original.example.com",
        },
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    store = create_response.json()

    patch_response = client.patch(
        f"/api/stores/{store['id']}",
        json={
            "name": "Updated Store",
            "slug": "updated-store",
            "website_url": "https://updated.example.com",
            "active": False,
        },
        headers=user_auth_headers,
    )

    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["name"] == "Updated Store"
    assert payload["slug"] == "updated-store"
    assert payload["website_url"] == str(HttpUrl("https://updated.example.com"))
    assert payload["active"] is False

    with Session(engine) as session:
        persisted = session.get(models.Store, store["id"])
        assert persisted is not None
        assert persisted.slug == "updated-store"
        assert persisted.active is False


def test_delete_store(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/stores",
        json={"name": "Disposable Store", "slug": "disposable-store"},
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    store = create_response.json()

    delete_response = client.delete(
        f"/api/stores/{store['id']}", headers=user_auth_headers
    )

    assert delete_response.status_code == 204

    with Session(engine) as session:
        assert session.get(models.Store, store["id"]) is None


def test_create_tag_conflict(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    payload = {"name": "Home", "slug": "home"}
    first = client.post("/api/tags", json=payload, headers=user_auth_headers)
    assert first.status_code == 201

    conflict = client.post("/api/tags", json=payload, headers=user_auth_headers)

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Tag slug already exists"


def test_update_tag(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/tags",
        json={"name": "Original", "slug": "original"},
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    tag = create_response.json()

    patch_response = client.patch(
        f"/api/tags/{tag['id']}",
        json={"name": "Renamed", "slug": "renamed"},
        headers=user_auth_headers,
    )

    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["name"] == "Renamed"
    assert payload["slug"] == "renamed"

    with Session(engine) as session:
        persisted = session.get(models.Tag, tag["id"])
        assert persisted is not None
        assert persisted.slug == "renamed"


def test_delete_tag(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/tags",
        json={"name": "Ephemeral", "slug": "ephemeral"},
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    tag = create_response.json()

    delete_response = client.delete(f"/api/tags/{tag['id']}", headers=user_auth_headers)

    assert delete_response.status_code == 204

    with Session(engine) as session:
        assert session.get(models.Tag, tag["id"]) is None


def test_merge_tags_moves_links(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    source_response = client.post(
        "/api/tags",
        json={"name": "Clearance", "slug": "clearance"},
        headers=user_auth_headers,
    )
    target_response = client.post(
        "/api/tags",
        json={"name": "Sale", "slug": "sale"},
        headers=user_auth_headers,
    )
    assert source_response.status_code == target_response.status_code == 201
    source_id = source_response.json()["id"]
    target_id = target_response.json()["id"]

    product_response = client.post(
        "/api/products",
        json={
            "name": "Discounted Headphones",
            "slug": "discounted-headphones",
            "tag_slugs": ["clearance"],
        },
        headers=user_auth_headers,
    )
    assert product_response.status_code == 201

    merge_response = client.post(
        "/api/tags/merge",
        json={
            "source_tag_id": source_id,
            "target_tag_id": target_id,
            "delete_source": True,
        },
        headers=user_auth_headers,
    )

    assert merge_response.status_code == 200
    body = merge_response.json()
    assert body == {
        "source_tag_id": source_id,
        "target_tag_id": target_id,
        "moved_links": 1,
        "removed_duplicate_links": 0,
        "deleted_source": True,
    }

    listing = client.get("/api/products", headers=user_auth_headers)
    assert listing.status_code == 200
    product_payload = listing.json()[0]
    assert [tag["slug"] for tag in product_payload["tags"]] == ["sale"]

    with Session(engine) as session:
        assert session.get(models.Tag, source_id) is None
        target = session.get(models.Tag, target_id)
        assert target is not None
        logs = session.exec(
            select(models.AuditLog).where(models.AuditLog.action == "tag.merge")
        ).all()
        assert len(logs) == 1
        context = cast(dict[str, Any], logs[0].context or {})
        assert context.get("source_tag_id") == source_id
        assert context.get("target_tag_id") == target_id
        assert context.get("moved_links") == 1


def test_merge_tags_requires_distinct_ids(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    tag_response = client.post(
        "/api/tags",
        json={"name": "Unique", "slug": "unique"},
        headers=user_auth_headers,
    )
    assert tag_response.status_code == 201
    tag_id = tag_response.json()["id"]

    response = client.post(
        "/api/tags/merge",
        json={
            "source_tag_id": tag_id,
            "target_tag_id": tag_id,
        },
        headers=user_auth_headers,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any("differ" in error.get("msg", "") for error in detail)


def test_create_product_conflict(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.post(
        "/api/tags",
        json={"name": "Kitchen", "slug": "kitchen"},
        headers=user_auth_headers,
    )
    payload = {
        "name": "Blender",
        "slug": "blender",
        "tag_slugs": ["kitchen"],
    }
    first = client.post("/api/products", json=payload, headers=user_auth_headers)
    assert first.status_code == 201

    conflict = client.post("/api/products", json=payload, headers=user_auth_headers)

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Product slug already exists"


def test_update_product(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    client.post(
        "/api/tags",
        json={"name": "Kitchen", "slug": "kitchen"},
        headers=user_auth_headers,
    )
    client.post(
        "/api/tags",
        json={"name": "Appliances", "slug": "appliances"},
        headers=user_auth_headers,
    )
    create_response = client.post(
        "/api/products",
        json={
            "name": "Mixer",
            "slug": "mixer",
            "description": "Original description",
            "tag_slugs": ["kitchen"],
        },
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    product = create_response.json()

    patch_response = client.patch(
        f"/api/products/{product['id']}",
        json={
            "name": "Stand Mixer",
            "slug": "stand-mixer",
            "description": "Updated description",
            "is_active": False,
            "status": "archived",
            "favourite": False,
            "only_official": True,
            "notify_price": 110.0,
            "notify_percent": 5.0,
            "ignored_urls": ["https://example.com/ignore"],
            "image_url": "https://images.example.com/stand-mixer.png",
            "tag_slugs": ["appliances"],
        },
        headers=user_auth_headers,
    )

    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["name"] == "Stand Mixer"
    assert payload["slug"] == "stand-mixer"
    assert payload["description"] == "Updated description"
    assert payload["is_active"] is False
    assert payload["status"] == "archived"
    assert payload["favourite"] is False
    assert payload["only_official"] is True
    assert payload["notify_price"] == 110.0
    assert payload["notify_percent"] == 5.0
    assert payload["ignored_urls"] == ["https://example.com/ignore"]
    assert payload["image_url"] == "https://images.example.com/stand-mixer.png"
    assert [tag["slug"] for tag in payload["tags"]] == ["appliances"]

    with Session(engine) as session:
        persisted = session.get(models.Product, product["id"])
        assert persisted is not None
        assert persisted.slug == "stand-mixer"
        assert persisted.is_active is False
        assert persisted.status == ProductStatus.ARCHIVED
        assert persisted.favourite is False
        assert persisted.only_official is True
        assert persisted.notify_price == pytest.approx(110.0)
        assert persisted.notify_percent == pytest.approx(5.0)
        assert persisted.ignored_urls == ["https://example.com/ignore"]
        assert persisted.image_url == "https://images.example.com/stand-mixer.png"


def test_update_product_validates_tags(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/products",
        json={"name": "Widget", "slug": "widget"},
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    product = create_response.json()

    patch_response = client.patch(
        f"/api/products/{product['id']}",
        json={"tag_slugs": ["missing"]},
        headers=user_auth_headers,
    )

    assert patch_response.status_code == 404
    assert patch_response.json()["detail"] == "Tag 'missing' not found"


def test_bulk_update_products_updates_status(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    product_ids: list[int] = []
    for index in range(2):
        response = client.post(
            "/api/products",
            json={
                "name": f"Bulk Item {index}",
                "slug": f"bulk-item-{index}",
            },
            headers=user_auth_headers,
        )
        assert response.status_code == 201
        product_ids.append(response.json()["id"])

    response = client.post(
        "/api/products/bulk-update",
        json={
            "product_ids": product_ids,
            "updates": {"status": "archived", "is_active": False},
        },
        headers=user_auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert sorted(payload["updated_ids"]) == sorted(product_ids)
    assert payload["skipped_ids"] == []
    assert payload["missing_ids"] == []

    with Session(engine) as session:
        stored = [session.get(models.Product, pid) for pid in product_ids]
        actual_products = [product for product in stored if product is not None]
        assert len(actual_products) == len(product_ids)
        for product in actual_products:
            assert product.status == ProductStatus.ARCHIVED
            assert product.is_active is False

        logs = session.exec(
            select(models.AuditLog).where(
                models.AuditLog.action == "product.bulk_update"
            )
        ).all()
        assert len(logs) == 1
        context = cast(dict[str, Any], logs[0].context or {})
        updated_ids = cast(list[int], context.get("updated_ids", []))
        assert sorted(updated_ids) == sorted(product_ids)
        updates_context = cast(dict[str, Any], context.get("updates", {}))
        assert updates_context.get("status") == "archived"


def test_bulk_update_products_handles_large_payload(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    product_ids: list[int] = []
    for index in range(60):
        response = client.post(
            "/api/products",
            json={
                "name": f"Bulk Volume Item {index}",
                "slug": f"bulk-volume-item-{index}",
                "description": "Load test",
            },
            headers=user_auth_headers,
        )
        assert response.status_code == 201
        product_ids.append(response.json()["id"])

    with Session(engine) as session:
        product_table = cast(Table, cast(Any, models.Product).__table__)
        statement = select(models.Product).where(product_table.c.id.in_(product_ids))
        stored_products = session.exec(statement).all()
        for product in stored_products:
            product.status = ProductStatus.ARCHIVED
            product.is_active = False
            product.favourite = False
            session.add(product)
        session.commit()

    response = client.post(
        "/api/products/bulk-update",
        json={
            "product_ids": product_ids,
            "updates": {"status": "published", "is_active": True, "favourite": True},
        },
        headers=user_auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert sorted(payload["updated_ids"]) == sorted(product_ids)
    assert payload["skipped_ids"] == []
    assert payload["missing_ids"] == []

    with Session(engine) as session:
        product_table = cast(Table, cast(Any, models.Product).__table__)
        statement = select(models.Product).where(product_table.c.id.in_(product_ids))
        stored_products = session.exec(statement).all()
        assert len(stored_products) == len(product_ids)
        for product in stored_products:
            assert product.status == ProductStatus.PUBLISHED
            assert product.is_active is True
            assert product.favourite is True

        logs = session.exec(
            select(models.AuditLog).where(
                models.AuditLog.action == "product.bulk_update"
            )
        ).all()
        assert len(logs) == 1
        context = cast(dict[str, Any], logs[0].context or {})
        updated_ids = cast(list[int], context.get("updated_ids", []))
        assert sorted(updated_ids) == sorted(product_ids)


def test_bulk_update_products_enforces_scope(
    client: TestClient,
    user_auth_headers: dict[str, str],
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
) -> None:
    other_user = create_user(email="bulk-scope@example.com")
    other_headers = make_auth_headers(other_user)

    other_product = client.post(
        "/api/products",
        json={"name": "Other Product", "slug": "other-product"},
        headers=other_headers,
    )
    assert other_product.status_code == 201
    other_id = other_product.json()["id"]

    response = client.post(
        "/api/products/bulk-update",
        json={"product_ids": [other_id], "updates": {"status": "archived"}},
        headers=user_auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Resource not found"


def test_delete_product(
    client: TestClient, engine: Engine, user_auth_headers: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/products",
        json={"name": "Disposable", "slug": "disposable"},
        headers=user_auth_headers,
    )
    assert create_response.status_code == 201
    product = create_response.json()

    delete_response = client.delete(
        f"/api/products/{product['id']}", headers=user_auth_headers
    )

    assert delete_response.status_code == 204

    with Session(engine) as session:
        assert session.get(models.Product, product["id"]) is None


def test_delete_product_cascades_urls_and_prices(
    client: TestClient,
    engine: Engine,
    user_auth_headers: dict[str, str],
) -> None:
    product_id, product_url_id = _create_price_history_fixtures(
        client, user_auth_headers
    )

    history_response = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": product_url_id,
            "price": 42.5,
            "currency": "USD",
        },
        headers=user_auth_headers,
    )
    assert history_response.status_code == 201

    delete_response = client.delete(
        f"/api/products/{product_id}", headers=user_auth_headers
    )

    assert delete_response.status_code == 204

    with Session(engine) as session:
        assert session.get(models.Product, product_id) is None
        assert session.get(models.ProductURL, product_url_id) is None
        price_exists = session.exec(
            select(models.PriceHistory.id).where(
                models.PriceHistory.product_id == product_id
            )
        ).first()
        assert price_exists is None


def test_product_read_includes_latest_price(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    product_id, product_url_id = _create_price_history_fixtures(
        client, user_auth_headers
    )
    earlier = datetime(2024, 1, 1, 12, tzinfo=UTC)
    later = datetime(2024, 1, 2, 12, tzinfo=UTC)

    first_entry = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": product_url_id,
            "price": 20.0,
            "currency": "USD",
            "recorded_at": earlier.isoformat(),
        },
        headers=user_auth_headers,
    )
    assert first_entry.status_code == 201

    second_entry = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": product_url_id,
            "price": 18.5,
            "currency": "USD",
            "recorded_at": later.isoformat(),
        },
        headers=user_auth_headers,
    )
    assert second_entry.status_code == 201

    products = client.get("/api/products", headers=user_auth_headers).json()
    assert len(products) == 1
    latest_price = products[0]["latest_price"]
    assert latest_price is not None
    assert latest_price["price"] == 18.5
    assert latest_price["currency"] == "USD"
    assert latest_price["recorded_at"] == later.replace(tzinfo=None).isoformat()
    assert latest_price["product_url"]["id"] == product_url_id


def test_product_read_latest_price_is_none_without_history(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    product_response = client.post(
        "/api/products",
        json={"name": "Bare Product", "slug": "bare-product"},
        headers=user_auth_headers,
    )
    assert product_response.status_code == 201

    listing = client.get("/api/products", headers=user_auth_headers)
    assert listing.status_code == 200
    products = listing.json()
    assert len(products) == 1
    assert products[0]["latest_price"] is None


def test_create_product_url_attaches_to_product(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    store_response = client.post(
        "/api/stores",
        json={"name": "Example Store", "slug": "example-store"},
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = client.post("/api/tags", json={"name": "Books", "slug": "books"})
    assert tag_response.status_code == 201
    product_response = client.post(
        "/api/products",
        json={
            "name": "Sci-Fi Novel",
            "slug": "sci-fi-novel",
            "tag_slugs": ["books"],
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()

    response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/scifi",
            "is_primary": True,
        },
    )

    assert response.status_code == 201
    url_payload = response.json()
    assert url_payload["product_id"] == product["id"]
    assert url_payload["store_id"] == store["id"]

    product_detail = client.get("/api/products").json()[0]
    assert product_detail["urls"][0]["url"] == "https://example.com/scifi"
    assert product_detail["urls"][0]["store"]["slug"] == store["slug"]


def test_create_product_url_validates_foreign_keys(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    response = client.post(
        "/api/product-urls",
        json={
            "product_id": 999,
            "store_id": 999,
            "url": "https://example.com/missing",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_create_product_url_missing_store(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    tag_response = client.post("/api/tags", json={"name": "Music", "slug": "music"})
    assert tag_response.status_code == 201
    product_response = client.post(
        "/api/products",
        json={"name": "Guitar", "slug": "guitar", "tag_slugs": ["music"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": 404,
            "url": "https://example.com/guitar",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Store not found"


def test_create_product_url_missing_user(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    store_response = client.post(
        "/api/stores", json={"name": "Outlet", "slug": "outlet"}
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = client.post("/api/tags", json={"name": "Tech", "slug": "tech"})
    assert tag_response.status_code == 201
    product_response = client.post(
        "/api/products",
        json={"name": "Laptop", "slug": "laptop", "tag_slugs": ["tech"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/laptop",
            "created_by_id": 777,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_list_product_urls(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    store_response = client.post("/api/stores", json={"name": "Depot", "slug": "depot"})
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = client.post("/api/tags", json={"name": "Garden", "slug": "garden"})
    assert tag_response.status_code == 201
    product_response = client.post(
        "/api/products",
        json={"name": "Hose", "slug": "hose", "tag_slugs": ["garden"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    create_response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/hose",
        },
    )
    assert create_response.status_code == 201

    listing = client.get("/api/product-urls")

    assert listing.status_code == 200
    payloads = listing.json()
    assert len(payloads) == 1
    assert payloads[0]["store"]["slug"] == store["slug"]


def test_list_stores_supports_filters(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    client.headers.update(user_auth_headers)
    client.post("/api/stores", json={"name": "Alpha", "slug": "alpha"})
    beta = client.post("/api/stores", json={"name": "Beta", "slug": "beta"})
    assert beta.status_code == 201

    client.patch(
        f"/api/stores/{beta.json()['id']}",
        json={"active": False},
    )

    filtered = client.get("/api/stores", params={"search": "bet"})
    assert filtered.status_code == 200
    assert [store["slug"] for store in filtered.json()] == ["beta"]

    inactive = client.get("/api/stores", params={"active": False})
    assert inactive.status_code == 200
    assert [store["slug"] for store in inactive.json()] == ["beta"]

    paginated = client.get("/api/stores", params={"limit": 1, "offset": 1})
    assert paginated.status_code == 200
    assert len(paginated.json()) == 1


def test_list_tags_supports_search_and_pagination(
    authed_client: TestClient,
) -> None:
    for slug in ("alpha", "beta", "gamma"):
        response = authed_client.post(
            "/api/tags", json={"name": slug.title(), "slug": slug}
        )
        assert response.status_code == 201

    filtered = authed_client.get("/api/tags", params={"search": "ma"})
    assert filtered.status_code == 200
    assert [tag["slug"] for tag in filtered.json()] == ["gamma"]

    paginated = authed_client.get("/api/tags", params={"limit": 2, "offset": 1})
    assert paginated.status_code == 200
    assert len(paginated.json()) == 2


def test_list_products_supports_filters(authed_client: TestClient) -> None:
    authed_client.post("/api/tags", json={"name": "Electronics", "slug": "electronics"})
    authed_client.post("/api/tags", json={"name": "Accessories", "slug": "accessories"})

    first = authed_client.post(
        "/api/products",
        json={
            "name": "Noise Cancelling Headphones",
            "slug": "noise-cancelling-headphones",
            "tag_slugs": ["electronics"],
        },
    )
    assert first.status_code == 201

    second = authed_client.post(
        "/api/products",
        json={
            "name": "Accessory Pack",
            "slug": "accessory-pack",
            "is_active": False,
            "tag_slugs": ["accessories"],
        },
    )
    assert second.status_code == 201

    inactive = authed_client.get("/api/products", params={"is_active": False})
    assert inactive.status_code == 200
    assert [product["slug"] for product in inactive.json()] == ["accessory-pack"]

    tagged = authed_client.get("/api/products", params={"tag": "ELECTRONICS"})
    assert tagged.status_code == 200
    assert [product["slug"] for product in tagged.json()] == [
        "noise-cancelling-headphones"
    ]

    searched = authed_client.get("/api/products", params={"search": "pack"})
    assert searched.status_code == 200
    assert [product["slug"] for product in searched.json()] == ["accessory-pack"]


def test_product_url_list_supports_filters(authed_client: TestClient) -> None:
    store = authed_client.post(
        "/api/stores", json={"name": "Store", "slug": "store"}
    ).json()
    product = authed_client.post(
        "/api/products",
        json={"name": "Widget", "slug": "widget"},
    ).json()

    authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/widget",
            "active": True,
        },
    )

    inactive = authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/widget-inactive",
            "active": False,
        },
    )
    assert inactive.status_code == 201

    filtered = authed_client.get(
        "/api/product-urls",
        params={"product_id": product["id"], "active": False},
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["active"] is False

    paginated = authed_client.get(
        "/api/product-urls",
        params={"limit": 1, "offset": 1, "product_id": product["id"]},
    )
    assert paginated.status_code == 200
    assert len(paginated.json()) == 1


def test_refresh_product_url_metadata(
    authed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = authed_client.post(
        "/api/stores", json={"name": "Shop", "slug": "shop"}
    ).json()
    product = authed_client.post(
        "/api/products",
        json={"name": "Original Gadget", "slug": "original-gadget"},
    ).json()

    url_payload = {
        "product_id": product["id"],
        "store_id": store["id"],
        "url": "https://example.com/gadget",
        "is_primary": True,
    }
    created = authed_client.post("/api/product-urls", json=url_payload)
    assert created.status_code == 201
    product_url = created.json()

    refreshed_metadata = {
        "title": "Updated Gadget Name",
        "image": "https://cdn.example.com/gadget.jpg",
        "description": "A refreshed gadget description.",
        "currency": "USD",
    }

    def _fake_fetch(
        url: str,
        scraper_base_url: str | None,
        http_client_factory: Any,
        *,
        diagnostics: list[str] | None = None,
    ) -> dict[str, Any]:
        if diagnostics is not None:
            diagnostics.append("Fetched metadata in test harness")
        return refreshed_metadata.copy()

    monkeypatch.setattr("app.services.catalog.fetch_url_metadata", _fake_fetch)

    response = authed_client.post(f"/api/product-urls/{product_url['id']}/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["title"] == "Updated Gadget Name"
    assert payload["name_updated"] is True
    assert payload["image_updated"] is True
    assert any("Fetched metadata" in warning for warning in payload["warnings"])

    refreshed_product = authed_client.get(f"/api/products/{product['id']}").json()
    assert refreshed_product["name"] == "Updated Gadget Name"
    assert refreshed_product["image_url"] == "https://cdn.example.com/gadget.jpg"


def test_create_product_url_with_existing_user(authed_client: TestClient) -> None:
    user_response = authed_client.post(
        "/api/users",
        json={
            "email": "owner@example.com",
            "full_name": "Owner",
            "provider": "oidc",
            "provider_subject": "owner-123",
        },
    )
    assert user_response.status_code == 201
    user = user_response.json()

    store_response = authed_client.post(
        "/api/stores", json={"name": "Hub", "slug": "hub"}
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = authed_client.post(
        "/api/tags", json={"name": "Office", "slug": "office"}
    )
    assert tag_response.status_code == 201
    product_response = authed_client.post(
        "/api/products",
        json={"name": "Chair", "slug": "chair", "tag_slugs": ["office"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    create_response = authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/chair",
            "created_by_id": user["id"],
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["created_by_id"] == user["id"]


def test_build_product_read_missing_product(engine: Engine) -> None:
    with Session(engine) as session:
        user = models.User(email="missing@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)
        with pytest.raises(HTTPException) as exc_info:
            catalog._build_product_read(session, user, 999)

    assert exc_info.value.status_code == 404


def test_update_product_url(authed_client: TestClient, engine: Engine) -> None:
    store_response = authed_client.post(
        "/api/stores", json={"name": "Primary", "slug": "primary"}
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = authed_client.post(
        "/api/tags", json={"name": "Label", "slug": "label"}
    )
    assert tag_response.status_code == 201
    product_response = authed_client.post(
        "/api/products",
        json={"name": "Item", "slug": "item", "tag_slugs": ["label"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()
    create_response = authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/item",
        },
    )
    assert create_response.status_code == 201
    product_url = create_response.json()

    patch_response = authed_client.patch(
        f"/api/product-urls/{product_url['id']}",
        json={
            "url": "https://example.com/item-updated",
            "is_primary": True,
            "active": False,
        },
    )

    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["url"] == "https://example.com/item-updated"
    assert payload["is_primary"] is True
    assert payload["active"] is False

    with Session(engine) as session:
        persisted = session.get(models.ProductURL, product_url["id"])
        assert persisted is not None
        assert persisted.url.endswith("item-updated")
        assert persisted.is_primary is True
        assert persisted.active is False


def test_delete_product_url(authed_client: TestClient, engine: Engine) -> None:
    store_response = authed_client.post(
        "/api/stores", json={"name": "Short", "slug": "short"}
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = authed_client.post(
        "/api/tags", json={"name": "Temp", "slug": "temp"}
    )
    assert tag_response.status_code == 201
    product_response = authed_client.post(
        "/api/products",
        json={"name": "Temp Item", "slug": "temp-item", "tag_slugs": ["temp"]},
    )
    assert product_response.status_code == 201
    product = product_response.json()
    create_response = authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/temp",
        },
    )
    assert create_response.status_code == 201
    product_url = create_response.json()

    delete_response = authed_client.delete(f"/api/product-urls/{product_url['id']}")

    assert delete_response.status_code == 204

    with Session(engine) as session:
        assert session.get(models.ProductURL, product_url["id"]) is None


def test_delete_product_url_removes_price_history(
    authed_client: TestClient, engine: Engine
) -> None:
    store_response = authed_client.post(
        "/api/stores", json={"name": "Cache", "slug": "cache"}
    )
    assert store_response.status_code == 201
    store = store_response.json()

    product_response = authed_client.post(
        "/api/products",
        json={"name": "Cache Item", "slug": "cache-item"},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    create_response = authed_client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/cache-item",
        },
    )
    assert create_response.status_code == 201
    product_url = create_response.json()

    history_response = authed_client.post(
        "/api/price-history",
        json={
            "product_id": product["id"],
            "product_url_id": product_url["id"],
            "price": 199.99,
        },
    )
    assert history_response.status_code == 201
    history_id = history_response.json()["id"]

    with Session(engine) as session:
        persisted_product = session.get(models.Product, product["id"])
        assert persisted_product is not None
        assert persisted_product.price_cache

    delete_response = authed_client.delete(f"/api/product-urls/{product_url['id']}")
    assert delete_response.status_code == 204

    history_listing = authed_client.get(
        "/api/price-history", params={"product_id": product["id"]}
    )
    assert history_listing.status_code == 200
    assert history_listing.json() == []

    with Session(engine) as session:
        assert session.get(models.PriceHistory, history_id) is None
        persisted_product = session.get(models.Product, product["id"])
        assert persisted_product is not None
        assert persisted_product.price_cache == []


def _create_price_history_fixtures(
    client: TestClient, headers: Mapping[str, str]
) -> tuple[int, int]:
    store_response = client.post(
        "/api/stores",
        json={"name": "Catalog Store", "slug": "catalog-store"},
        headers=headers,
    )
    assert store_response.status_code == 201
    store = store_response.json()
    tag_response = client.post(
        "/api/tags", json={"name": "Audio", "slug": "audio"}, headers=headers
    )
    assert tag_response.status_code == 201
    product_response = client.post(
        "/api/products",
        json={"name": "Speaker", "slug": "speaker", "tag_slugs": ["audio"]},
        headers=headers,
    )
    assert product_response.status_code == 201
    product = product_response.json()
    product_url_response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://example.com/speaker",
        },
        headers=headers,
    )
    assert product_url_response.status_code == 201
    product_url = product_url_response.json()
    return product["id"], product_url["id"]


def test_create_price_history_entry(client: TestClient) -> None:
    product_id, product_url_id = _create_price_history_fixtures(client, client.headers)

    response = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": product_url_id,
            "price": 199.99,
            "currency": "USD",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["product_id"] == product_id
    assert payload["product_url_id"] == product_url_id
    assert payload["price"] == 199.99
    assert payload["currency"] == "USD"

    listing = client.get("/api/price-history", params={"product_id": product_id})
    assert listing.status_code == 200
    entries = listing.json()
    assert len(entries) == 1
    assert entries[0]["product_url"]["url"] == "https://example.com/speaker"

    product_listing = client.get("/api/products")
    assert product_listing.status_code == 200
    product_payload = product_listing.json()[0]
    assert product_payload["current_price"] == 199.99
    assert product_payload["price_cache"][0]["price"] == 199.99


def test_create_price_history_requires_existing_product(client: TestClient) -> None:
    response = client.post(
        "/api/price-history",
        json={"product_id": 999, "price": 29.99},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_create_price_history_validates_product_url(client: TestClient) -> None:
    product_id, _ = _create_price_history_fixtures(client, client.headers)

    response = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": 777,
            "price": 14.99,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Product URL not found"


def test_create_price_history_detects_product_url_mismatch(
    client: TestClient,
) -> None:
    product_a, url_a = _create_price_history_fixtures(client, client.headers)
    client.post("/api/stores", json={"name": "Alt Store", "slug": "alt-store"})
    client.post("/api/tags", json={"name": "Office Alt", "slug": "office-alt"})
    product_b = client.post(
        "/api/products",
        json={"name": "Desk", "slug": "desk", "tag_slugs": ["office-alt"]},
    ).json()

    mismatch = client.post(
        "/api/price-history",
        json={
            "product_id": product_b["id"],
            "product_url_id": url_a,
            "price": 89.50,
        },
    )

    assert mismatch.status_code == 400
    assert mismatch.json()["detail"] == "Product URL does not belong to product"


def test_create_price_history_with_custom_timestamp(client: TestClient) -> None:
    product_id, product_url_id = _create_price_history_fixtures(client, client.headers)
    recorded_at = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0)

    response = client.post(
        "/api/price-history",
        json={
            "product_id": product_id,
            "product_url_id": product_url_id,
            "price": 149.5,
            "currency": "USD",
            "recorded_at": recorded_at.isoformat(),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    expected_iso = recorded_at.replace(tzinfo=None).isoformat()
    assert payload["recorded_at"] == expected_iso

    listing = client.get(
        "/api/price-history",
        params={"product_url_id": product_url_id},
    )

    assert listing.status_code == 200
    entries = listing.json()
    assert len(entries) == 1
    assert entries[0]["recorded_at"] == expected_iso

    product_listing = client.get("/api/products")
    assert product_listing.status_code == 200
    cache_entry = product_listing.json()[0]["price_cache"][0]
    last_scrape = cache_entry["last_scrape"]
    assert last_scrape is not None
    normalized = last_scrape.replace("Z", "+00:00")
    assert datetime.fromisoformat(normalized) == recorded_at
