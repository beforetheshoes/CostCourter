from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    PriceHistory,
    Product,
    ProductURL,
    Store,
    Tag,
    User,
)
from app.models.product import ProductStatus
from app.services.price_cache import rebuild_product_price_cache


@dataclass(frozen=True, slots=True)
class SampleStore:
    slug: str
    name: str
    website_url: str
    domains: tuple[str, ...]
    scrape_strategy: dict[str, dict[str, Any]]
    settings: dict[str, Any]
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SampleTag:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class SampleProduct:
    slug: str
    name: str
    description: str | None
    image_url: str | None
    favourite: bool
    notify_price: float | None
    tag_slugs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SampleProductURL:
    url: str
    is_primary: bool
    active: bool


@dataclass(frozen=True, slots=True)
class SamplePriceHistory:
    price: float
    currency: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class SampleCatalogResult:
    store_id: int
    product_id: int
    product_url_ids: tuple[int, ...]
    price_history_ids: tuple[int, ...]


SAMPLE_STORE = SampleStore(
    slug="acme-store",
    name="Acme Store",
    website_url="https://store.example.com",
    domains=("store.example.com",),
    scrape_strategy={
        "title": {"type": "css", "value": "h1.product-title"},
        "price": {"type": "css", "value": "span.price"},
        "image": {"type": "css", "value": "img.product-image::attr(src)"},
    },
    settings={
        "timezone": "UTC",
        "locale_settings": {
            "locale": "en_US",
            "currency": "USD",
        },
    },
    notes="Seed store for local development and automated tests.",
)

SAMPLE_TAGS: tuple[SampleTag, ...] = (
    SampleTag(slug="fixtures", name="Fixtures"),
    SampleTag(slug="acme", name="Acme"),
)

SAMPLE_PRODUCT = SampleProduct(
    slug="acme-widget",
    name="Acme Widget",
    description="Reference product used across tests and sample data.",
    image_url="https://cdn.example.com/images/acme-widget.jpg",
    favourite=True,
    notify_price=149.99,
    tag_slugs=tuple(tag.slug for tag in SAMPLE_TAGS),
)

SAMPLE_PRODUCT_URLS: tuple[SampleProductURL, ...] = (
    SampleProductURL(
        url="https://store.example.com/products/acme-widget",
        is_primary=True,
        active=True,
    ),
)

SAMPLE_PRICE_HISTORY: tuple[SamplePriceHistory, ...] = (
    SamplePriceHistory(
        price=189.99,
        currency="USD",
        recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
    ),
    SamplePriceHistory(
        price=179.99,
        currency="USD",
        recorded_at=datetime(2025, 1, 8, tzinfo=UTC),
    ),
    SamplePriceHistory(
        price=169.49,
        currency="USD",
        recorded_at=datetime(2025, 1, 16, tzinfo=UTC),
    ),
)


def install_sample_catalog(session: Session, *, owner: User) -> SampleCatalogResult:
    if owner.id is None:
        raise ValueError("Owner must be persisted before installing fixtures")

    store = _upsert_store(session, owner_id=owner.id, definition=SAMPLE_STORE)
    tags = _upsert_tags(session, owner_id=owner.id, definitions=SAMPLE_TAGS)
    product = _upsert_product(session, owner_id=owner.id, definition=SAMPLE_PRODUCT)
    _link_tags(session, product=product, tags=tags)
    product_urls = _upsert_product_urls(
        session,
        owner_id=owner.id,
        product=product,
        store=store,
        definitions=SAMPLE_PRODUCT_URLS,
    )
    prices = _ensure_price_history(
        session,
        product=product,
        product_urls=product_urls,
        definitions=SAMPLE_PRICE_HISTORY,
    )

    rebuild_product_price_cache(session, product)
    session.add(product)
    session.commit()
    session.refresh(product)

    url_ids = tuple(url.id for url in product_urls if url.id is not None)
    price_ids = tuple(price.id for price in prices if price.id is not None)
    assert store.id is not None
    assert product.id is not None

    return SampleCatalogResult(
        store_id=store.id,
        product_id=product.id,
        product_url_ids=url_ids,
        price_history_ids=price_ids,
    )


def _upsert_store(session: Session, *, owner_id: int, definition: SampleStore) -> Store:
    existing = session.exec(
        select(Store)
        .where(Store.user_id == owner_id)
        .where(Store.slug == definition.slug)
    ).first()
    if existing is not None:
        existing.name = definition.name
        existing.website_url = definition.website_url
        existing.domains = [{"domain": domain} for domain in definition.domains]
        existing.scrape_strategy = definition.scrape_strategy
        existing.settings = definition.settings
        existing.notes = definition.notes
        session.add(existing)
        session.flush()
        return existing

    store = Store(
        user_id=owner_id,
        name=definition.name,
        slug=definition.slug,
        website_url=definition.website_url,
        domains=[{"domain": domain} for domain in definition.domains],
        scrape_strategy=definition.scrape_strategy,
        settings=definition.settings,
        notes=definition.notes,
    )
    session.add(store)
    session.flush()
    return store


def _upsert_tags(
    session: Session,
    *,
    owner_id: int,
    definitions: Iterable[SampleTag],
) -> list[Tag]:
    tags: list[Tag] = []
    for definition in definitions:
        existing = session.exec(
            select(Tag)
            .where(Tag.user_id == owner_id)
            .where(Tag.slug == definition.slug)
        ).first()
        if existing is not None:
            existing.name = definition.name
            session.add(existing)
            tags.append(existing)
            continue
        tag = Tag(
            user_id=owner_id,
            slug=definition.slug,
            name=definition.name,
        )
        session.add(tag)
        session.flush()
        tags.append(tag)
    return tags


def _upsert_product(
    session: Session,
    *,
    owner_id: int,
    definition: SampleProduct,
) -> Product:
    existing = session.exec(
        select(Product)
        .where(Product.user_id == owner_id)
        .where(Product.slug == definition.slug)
    ).first()
    if existing is not None:
        existing.name = definition.name
        existing.description = definition.description
        existing.image_url = definition.image_url
        existing.favourite = definition.favourite
        existing.notify_price = definition.notify_price
        existing.is_active = True
        existing.status = ProductStatus.PUBLISHED
        session.add(existing)
        session.flush()
        return existing

    product = Product(
        user_id=owner_id,
        name=definition.name,
        slug=definition.slug,
        description=definition.description,
        image_url=definition.image_url,
        favourite=definition.favourite,
        notify_price=definition.notify_price,
        is_active=True,
        status=ProductStatus.PUBLISHED,
    )
    session.add(product)
    session.flush()
    return product


def _link_tags(session: Session, *, product: Product, tags: Iterable[Tag]) -> None:
    if product.id is None:
        session.flush()
    existing_slugs = {tag.slug for tag in product.tags}
    for tag in tags:
        if tag.slug in existing_slugs:
            continue
        product.tags.append(tag)
    session.flush()


def _upsert_product_urls(
    session: Session,
    *,
    owner_id: int,
    product: Product,
    store: Store,
    definitions: Iterable[SampleProductURL],
) -> list[ProductURL]:
    urls: list[ProductURL] = []
    for definition in definitions:
        existing = session.exec(
            select(ProductURL)
            .where(ProductURL.product_id == product.id)
            .where(ProductURL.url == definition.url)
        ).first()
        if existing is not None:
            existing.is_primary = definition.is_primary
            existing.active = definition.active
            urls.append(existing)
            continue
        url = ProductURL(
            product_id=product.id,
            store_id=store.id,
            url=definition.url,
            is_primary=definition.is_primary,
            active=definition.active,
        )
        session.add(url)
        session.flush()
        urls.append(url)
    return urls


def _ensure_price_history(
    session: Session,
    *,
    product: Product,
    product_urls: Iterable[ProductURL],
    definitions: Iterable[SamplePriceHistory],
) -> list[PriceHistory]:
    url_ids = [url.id for url in product_urls if url.is_primary]
    primary_url_id = url_ids[0] if url_ids else None
    entries: list[PriceHistory] = []

    for definition in definitions:
        existing = session.exec(
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .where(PriceHistory.recorded_at == definition.recorded_at)
        ).first()
        if existing is not None:
            existing.price = definition.price
            existing.currency = definition.currency
            session.add(existing)
            entries.append(existing)
            continue

        history = PriceHistory(
            product_id=product.id,
            product_url_id=primary_url_id,
            price=definition.price,
            currency=definition.currency,
            recorded_at=definition.recorded_at,
        )
        session.add(history)
        session.flush()
        entries.append(history)

    return entries
