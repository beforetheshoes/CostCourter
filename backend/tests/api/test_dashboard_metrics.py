from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from pydantic import HttpUrl
from pydantic.type_adapter import TypeAdapter
from sqlalchemy.engine import Engine
from sqlmodel import Session

import app.models as models
from app.schemas import (
    PriceHistoryCreate,
    ProductCreate,
    ProductURLCreate,
    StoreCreate,
    StoreDomain,
    TagCreate,
)
from app.services import catalog as catalog_service

_HTTP_URL = TypeAdapter(HttpUrl)


def _create_product_with_history(
    session: Session,
    *,
    owner: models.User,
    name: str,
    slug: str,
    store_slug: str,
    tag_slug: str | None = None,
    initial_price: float,
    updated_price: float,
    recorded_offset_hours: int = 0,
) -> models.Product:
    store_read = catalog_service.create_store(
        session,
        payload=StoreCreate(
            name=store_slug.replace("-", " ").title(),
            slug=store_slug,
            domains=[StoreDomain(domain=store_slug.replace("-", "."))],
            scrape_strategy={},
            settings={},
        ),
        owner=owner,
    )
    product_payload = ProductCreate(
        name=name,
        slug=slug,
        description=None,
        is_active=True,
    )
    if tag_slug:
        product_payload.tag_slugs = [tag_slug]
    product_read = catalog_service.create_product(
        session,
        payload=product_payload,
        owner=owner,
    )
    product = session.get(models.Product, product_read.id)
    store = session.get(models.Store, store_read.id)
    assert product is not None and store is not None
    assert product.id is not None and store.id is not None
    product.image_url = f"https://img.example.com/{slug}.png"
    session.add(product)
    product_url_read = catalog_service.create_product_url(
        session,
        payload=ProductURLCreate(
            product_id=product.id,
            store_id=store.id,
            url=_HTTP_URL.validate_python(
                f"https://{store_slug.replace('-', '.')}/items/{slug}"
            ),
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
            price=initial_price,
            currency="USD",
            recorded_at=datetime.now(UTC)
            - timedelta(days=1, hours=recorded_offset_hours),
        ),
        owner=owner,
    )
    catalog_service.create_price_history(
        session,
        payload=PriceHistoryCreate(
            product_id=product.id,
            product_url_id=product_url_read.id,
            price=updated_price,
            currency="USD",
        ),
        owner=owner,
    )
    session.refresh(product)
    return product


def test_dashboard_metrics_returns_grouped_summary(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
) -> None:
    with Session(engine) as session:
        owner = session.get(models.User, admin_user.id)
        assert owner is not None
        catalog_service.create_tag(
            session,
            payload=TagCreate(name="Audio", slug="audio"),
            owner=owner,
        )
        fav_product = _create_product_with_history(
            session,
            owner=owner,
            name="Noise Cancelling Headphones",
            slug="noise-cancelling-headphones",
            store_slug="example-com",
            tag_slug="audio",
            initial_price=249.0,
            updated_price=199.0,
        )
        other_product = _create_product_with_history(
            session,
            owner=owner,
            name="Ergonomic Chair",
            slug="ergonomic-chair",
            store_slug="chairs-example-com",
            tag_slug=None,
            initial_price=349.0,
            updated_price=329.0,
            recorded_offset_hours=5,
        )
        fav_product.favourite = True
        other_product.favourite = True
        session.add(fav_product)
        session.add(other_product)
        session.commit()
        fav_id = fav_product.id
        other_id = other_product.id

        response = client.get("/api/admin/dashboard", headers=admin_auth_headers)
        assert response.status_code == 200
        payload = response.json()

        totals = payload["totals"]
        assert totals["products"] == 2
        assert totals["favourites"] == 2
        assert totals["active_urls"] == 2

        spotlight = payload["spotlight"]
        assert len(spotlight) == 2
        spotlight_ids = {item["id"] for item in spotlight}
        assert {fav_id, other_id} == spotlight_ids
        assert all(item["history"] for item in spotlight)

        groups = {group["label"]: group["products"] for group in payload["tag_groups"]}
        assert "Audio" in groups
        assert "Uncategorized" in groups
        assert any(item["id"] == fav_id for item in groups["Audio"])
        assert any(item["id"] == other_id for item in groups["Uncategorized"])

        assert payload["last_updated_at"] is not None
