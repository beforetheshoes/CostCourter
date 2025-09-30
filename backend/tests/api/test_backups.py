from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypedDict, cast

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import app.models as models


class BackupStoreEntry(TypedDict):
    slug: str


class BackupURLEntry(TypedDict):
    url: str
    is_primary: bool
    store: BackupStoreEntry


class BackupPriceHistoryEntry(TypedDict):
    url: str
    price: float
    currency: str


class BackupProductEntry(TypedDict):
    product: dict[str, object]
    urls: list[BackupURLEntry]
    price_history: list[BackupPriceHistoryEntry]


class ProductsBackup(TypedDict):
    version: int
    products: list[BackupProductEntry]


def _create_sample_catalog(client: TestClient) -> ProductsBackup:
    store_response = client.post(
        "/api/stores",
        json={"name": "Shop One", "slug": "shop-one"},
    )
    assert store_response.status_code == 201
    store = store_response.json()

    second_store_response = client.post(
        "/api/stores",
        json={
            "name": "Shop Two",
            "slug": "shop-two",
            "website_url": "https://shop.two",
        },
    )
    assert second_store_response.status_code == 201
    second_store = second_store_response.json()

    tag_response = client.post(
        "/api/tags",
        json={"name": "Gadget", "slug": "gadget"},
    )
    assert tag_response.status_code == 201

    product_response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "slug": "widget",
            "description": "Portable widget",
            "notify_price": 42.5,
            "ignored_urls": ["https://ignored.example"],
            "tag_slugs": ["gadget"],
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()

    primary_url_response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": store["id"],
            "url": "https://shop.one/widget",
            "is_primary": True,
        },
    )
    assert primary_url_response.status_code == 201
    primary_url = primary_url_response.json()

    secondary_url_response = client.post(
        "/api/product-urls",
        json={
            "product_id": product["id"],
            "store_id": second_store["id"],
            "url": "https://shop.two/widget",
            "active": False,
        },
    )
    assert secondary_url_response.status_code == 201
    secondary_url = secondary_url_response.json()

    first_recorded_at = datetime(2024, 1, 1, 12, 0, 0).isoformat() + "Z"
    second_recorded_at = datetime(2024, 2, 1, 12, 0, 0).isoformat() + "Z"

    first_history_response = client.post(
        "/api/price-history",
        json={
            "product_id": product["id"],
            "product_url_id": primary_url["id"],
            "price": 39.99,
            "currency": "USD",
            "recorded_at": first_recorded_at,
        },
    )
    assert first_history_response.status_code == 201

    second_history_response = client.post(
        "/api/price-history",
        json={
            "product_id": product["id"],
            "product_url_id": secondary_url["id"],
            "price": 36.5,
            "currency": "USD",
            "recorded_at": second_recorded_at,
        },
    )
    assert second_history_response.status_code == 201

    export_response = client.get("/api/backups/products")
    assert export_response.status_code == 200
    return cast(ProductsBackup, export_response.json())


def test_export_products_backup_contains_expected_urls_and_history(
    authed_client: TestClient,
) -> None:
    backup = _create_sample_catalog(authed_client)

    assert backup["version"] == 1
    assert backup["products"]
    product_entry = backup["products"][0]
    product_payload = product_entry["product"]

    assert product_payload["slug"] == "widget"
    assert product_payload["tag_slugs"] == ["gadget"]

    url_entries = product_entry["urls"]
    assert len(url_entries) == 2
    urls = {entry["url"] for entry in url_entries}
    assert urls == {"https://shop.one/widget", "https://shop.two/widget"}
    primary_entry = next(entry for entry in url_entries if entry["is_primary"])
    assert primary_entry["store"]["slug"] == "shop-one"

    price_history_entries = product_entry["price_history"]
    assert len(price_history_entries) == 2
    assert {
        (entry["url"], entry["price"], entry["currency"])
        for entry in price_history_entries
    } == {
        ("https://shop.one/widget", 39.99, "USD"),
        ("https://shop.two/widget", 36.5, "USD"),
    }


def test_import_products_backup_creates_entities_for_new_user(
    authed_client: TestClient,
    client: TestClient,
    engine: Engine,
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
) -> None:
    backup = _create_sample_catalog(authed_client)

    new_user = create_user(email="importer@example.com")
    headers = make_auth_headers(new_user)
    client.headers.update(headers)

    import_response = client.post("/api/backups/products", json=backup)
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload["products_created"] == 1
    assert payload["product_urls_created"] == 2
    assert payload["price_history_created"] == 2
    assert payload["stores_created"] == 2
    assert payload["tags_created"] == 1

    with Session(engine) as session:
        products = session.exec(
            select(models.Product).where(models.Product.user_id == new_user.id)
        ).all()
        assert len(products) == 1
        product = products[0]
        assert product.slug == "widget"
        assert product.description == "Portable widget"
        assert product.notify_price == 42.5
        assert product.ignored_urls == ["https://ignored.example"]

        tags = session.exec(
            select(models.Tag).where(models.Tag.user_id == new_user.id)
        ).all()
        assert {tag.slug for tag in tags} == {"gadget"}

        urls = session.exec(
            select(models.ProductURL).where(models.ProductURL.product_id == product.id)
        ).all()
        assert len(urls) == 2
        url_map = {url.url: url for url in urls}
        assert url_map["https://shop.one/widget"].is_primary is True
        assert url_map["https://shop.two/widget"].active is False

        stores = session.exec(
            select(models.Store).where(models.Store.user_id == new_user.id)
        ).all()
        assert {store.slug for store in stores} == {"shop-one", "shop-two"}

        history = session.exec(
            select(models.PriceHistory).where(
                models.PriceHistory.product_id == product.id
            )
        ).all()
        assert len(history) == 2
        assert {
            (entry.product_url_id, entry.price, entry.currency) for entry in history
        } == {
            (url_map["https://shop.one/widget"].id, 39.99, "USD"),
            (url_map["https://shop.two/widget"].id, 36.5, "USD"),
        }
