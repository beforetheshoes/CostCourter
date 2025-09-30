from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models as models
from app.services.price_cache import rebuild_product_price_cache


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


def _create_product_graph(session: Session) -> tuple[models.Product, models.ProductURL]:
    user = models.User(email="price-cache@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    store = models.Store(user_id=user.id, name="Cache Store", slug="cache-store")
    product = models.Product(user_id=user.id, name="Tracked Item", slug="tracked-item")
    session.add(store)
    session.add(product)
    session.commit()
    session.refresh(store)
    session.refresh(product)

    url = models.ProductURL(
        product_id=product.id,
        store_id=store.id,
        url="https://cache.example.com/item",
        is_primary=True,
    )
    session.add(url)
    session.commit()
    session.refresh(url)
    return product, url


def test_rebuild_product_price_cache_sets_current_price(engine: Any) -> None:
    with Session(engine) as session:
        product, product_url = _create_product_graph(session)
        assert product.id is not None
        assert product_url.id is not None

        base_time = datetime(2025, 1, 1, 12, 0, 0)
        session.add_all(
            [
                models.PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=120.0,
                    currency="USD",
                    recorded_at=base_time,
                ),
                models.PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=90.0,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=3),
                ),
                models.PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=95.0,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=6),
                ),
            ]
        )
        session.commit()

        rebuild_product_price_cache(session, product)
        session.commit()
        session.refresh(product)

        assert product.current_price == pytest.approx(95.0)
        assert len(product.price_cache) == 1
        entry = product.price_cache[0]
        assert entry["trend"] == "down"
        assert entry["price"] == pytest.approx(95.0)
        history = entry["history"]
        assert list(history.keys())[-1] >= list(history.keys())[0]
        assert entry["currency"] == "USD"
        assert entry["locale"] == "en_US"
        assert entry["last_scrape"] is not None
        aggregates = entry["aggregates"]
        assert aggregates["min"] == pytest.approx(90.0)
        assert aggregates["max"] == pytest.approx(120.0)
        assert aggregates["avg"] == pytest.approx(101.67, rel=1e-3)
