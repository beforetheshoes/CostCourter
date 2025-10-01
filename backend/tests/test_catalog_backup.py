"""Tests for catalog backup import/export helpers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.fixtures.sample_catalog import install_sample_catalog
from app.models import PriceHistory, Product, ProductURL, Store, User
from app.schemas.backup import CatalogBackup
from app.services.catalog_backup import export_catalog_backup, import_catalog_backup


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
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def _create_user(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _export_sample_backup(session: Session, owner: User) -> CatalogBackup:
    install_sample_catalog(session, owner=owner)
    return export_catalog_backup(session, owner=owner)


def test_export_catalog_backup_contains_related_records(engine: Engine) -> None:
    with Session(engine) as session:
        owner = _create_user(session, "owner@example.com")
        backup = _export_sample_backup(session, owner)

    assert backup.products, "expected at least one product in backup"
    product_entry = backup.products[0]
    assert product_entry.product.tag_slugs
    assert product_entry.urls
    assert product_entry.price_history


def test_import_catalog_backup_round_trip(engine: Engine) -> None:
    with Session(engine) as session:
        origin_owner = _create_user(session, "exporter@example.com")
        backup = _export_sample_backup(session, origin_owner)

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        owner = _create_user(session, "importer@example.com")
        response = import_catalog_backup(session, backup, owner=owner)

        assert response.products_created == len(backup.products)
        assert response.product_urls_created >= 1
        assert response.price_history_created >= 1
        assert response.stores_created == 1

        product_count = session.exec(
            select(Product).where(Product.user_id == owner.id)
        ).all()
        assert len(product_count) == response.products_created

        store_count = session.exec(select(Store).where(Store.user_id == owner.id)).all()
        assert len(store_count) == response.stores_created

        reexport = export_catalog_backup(session, owner=owner)
        assert reexport.products[0].product.name == backup.products[0].product.name

        backup.products[0].product.description = "Updated description"
        backup.products[0].urls[0].store.name = "Updated Store"
        response_second = import_catalog_backup(session, backup, owner=owner)

        assert response_second.products_updated >= 1
        assert response_second.stores_updated >= 1
        assert response_second.price_history_skipped >= 1

        updated_product = session.exec(
            select(Product).where(Product.user_id == owner.id)
        ).first()
        assert updated_product is not None
        assert updated_product.description == "Updated description"

        updated_store = session.exec(
            select(Store).where(Store.user_id == owner.id)
        ).first()
        assert updated_store is not None
        assert updated_store.name == "Updated Store"

        price_history = session.exec(
            select(PriceHistory).where(PriceHistory.product_id == updated_product.id)
        ).all()
        assert price_history

        urls = session.exec(
            select(ProductURL).where(ProductURL.product_id == updated_product.id)
        ).all()
        assert urls
