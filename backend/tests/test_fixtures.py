from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.fixtures import install_reference_data, install_sample_catalog
from app.models import AppSetting, PriceHistory, Product, ProductURL, Role, Store, User


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


def _create_user(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    session.expunge(user)
    return user


def test_install_reference_data_seeds_roles_and_settings(engine: Engine) -> None:
    with Session(engine) as session:
        install_reference_data(session)

    with Session(engine) as session:
        roles = session.exec(select(Role.slug, Role.name).order_by(Role.slug)).all()
        settings = session.exec(
            select(AppSetting.key, AppSetting.value).order_by(AppSetting.key)
        ).all()

    assert roles, "expected reference roles to be seeded"
    assert settings, "expected reference app settings to be seeded"

    with Session(engine) as session:
        install_reference_data(session)
        role_count = session.exec(select(func.count()).select_from(Role)).one()
        settings_count = session.exec(
            select(func.count()).select_from(AppSetting)
        ).one()

    assert role_count == len(roles)
    assert settings_count == len(settings)


def test_install_sample_catalog_creates_entities(engine: Engine) -> None:
    with Session(engine) as session:
        _create_user(session, "owner@example.com")

    with Session(engine) as session:
        owner_db = session.exec(
            select(User).where(User.email == "owner@example.com")
        ).one()
        assert owner_db.id is not None
        owner_id = owner_db.id
        install_reference_data(session)
        result = install_sample_catalog(session, owner=owner_db)

        store = session.get(Store, result.store_id)
        product = session.get(Product, result.product_id)
        urls = session.exec(
            select(ProductURL).where(ProductURL.product_id == result.product_id)
        ).all()
        prices = session.exec(
            select(PriceHistory).where(PriceHistory.product_id == result.product_id)
        ).all()

    assert store is not None
    assert product is not None
    assert store.user_id == owner_id
    assert product.user_id == owner_id
    assert len(urls) >= 1
    assert len(prices) >= 1

    with Session(engine) as session:
        owner_db = session.exec(
            select(User).where(User.email == "owner@example.com")
        ).one()
        install_sample_catalog(session, owner=owner_db)
        product_total = session.exec(select(func.count()).select_from(Product)).one()
        url_total = session.exec(select(func.count()).select_from(ProductURL)).one()

    assert product_total == 1
    assert url_total == len(urls)
