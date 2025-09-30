from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlmodel import Session, select

from app.models import Product, ProductURL, User
from app.schemas import PriceHistoryCreate, ProductCreate, ProductURLCreate
from app.services import catalog
from app.services.audit import record_audit_log
from app.services.price_cache import rebuild_product_price_cache
from app.services.product_quick_add import (
    HTTP_URL_ADAPTER,
    PriceRefreshCallback,
    _build_scrape_strategy,
    _coerce_price,
    _slugify,
    ensure_store_for_owner,
    fetch_url_metadata,
)

HttpClientFactory = Callable[[], httpx.Client]


@dataclass(slots=True)
class ImportItemPayload:
    url: str
    set_primary: bool


@dataclass(slots=True)
class CreatedURLResult:
    product_url_id: int
    store_id: int
    url: str
    is_primary: bool
    price: float | None
    currency: str | None


@dataclass(slots=True)
class BulkImportResult:
    product: Product
    created_product: bool
    created_urls: list[CreatedURLResult]
    skipped: list[tuple[str, str]]


def _load_product_for_owner(session: Session, owner: User, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    if owner.is_superuser:
        return product
    if product.user_id != owner.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot import URLs for another user's product",
        )
    return product


def _find_product_by_slug(session: Session, owner_id: int, slug: str) -> Product | None:
    statement = (
        select(Product).where(Product.slug == slug).where(Product.user_id == owner_id)
    )
    return session.exec(statement).first()


def _clear_primary(session: Session, product_id: int) -> None:
    statement = (
        select(ProductURL)
        .where(ProductURL.product_id == product_id)
        .where(ProductURL.is_primary)
    )
    updated = False
    for existing in session.exec(statement):
        if existing.is_primary:
            existing.is_primary = False
            session.add(existing)
            updated = True
    if updated:
        session.commit()


def _has_primary(session: Session, product_id: int) -> bool:
    statement = (
        select(ProductURL.id)
        .where(ProductURL.product_id == product_id)
        .where(ProductURL.is_primary)
    )
    return session.exec(statement).first() is not None


def _url_exists(session: Session, product_id: int, url: str) -> bool:
    statement = (
        select(ProductURL.id)
        .where(ProductURL.product_id == product_id)
        .where(ProductURL.url == url)
    )
    return session.exec(statement).first() is not None


def _normalize_title(
    meta: dict[str, Any], *, host: str, search_query: str | None
) -> str:
    title = (meta.get("title") or "").strip()
    if title:
        return title
    if search_query and search_query.strip():
        return search_query.strip()
    return host


def _resolve_or_create_product(
    session: Session,
    owner: User,
    *,
    base_title: str,
    slug: str,
    image_url: str | None,
) -> tuple[Product, bool]:
    owner_id = owner.id
    assert owner_id is not None

    existing = _find_product_by_slug(session, owner_id, slug)
    if existing is not None:
        return existing, False

    candidate_slug = slug
    candidate_title = base_title
    suffix = 1
    while True:
        try:
            product_read = catalog.create_product(
                session,
                payload=ProductCreate(
                    name=candidate_title,
                    slug=candidate_slug,
                    description=None,
                    is_active=True,
                ),
                owner=owner,
            )
            product = session.get(Product, product_read.id)
            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to load created product",
                )
            if image_url:
                product.image_url = image_url
                session.add(product)
                session.commit()
                session.refresh(product)
            return product, True
        except HTTPException as exc:
            if exc.status_code != status.HTTP_409_CONFLICT:
                raise
            suffix += 1
            candidate_slug = f"{slug}-{suffix}"
            candidate_title = f"{base_title} ({suffix})"


def bulk_import_product_urls(
    session: Session,
    owner: User,
    *,
    items: Sequence[ImportItemPayload],
    search_query: str | None,
    product: Product | None,
    scraper_base_url: str | None,
    http_client_factory: HttpClientFactory | None,
    price_refresh: PriceRefreshCallback | None = None,
    audit_ip: str | None = None,
) -> BulkImportResult:
    if owner.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user is missing an identifier",
        )
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one URL must be provided for import",
        )

    resolved_product = product
    created_product = False
    results: list[CreatedURLResult] = []
    skipped: list[tuple[str, str]] = []

    primary_exists = False
    if resolved_product is not None:
        if not owner.is_superuser and resolved_product.user_id != owner.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot import URLs for another user's product",
            )
        if resolved_product.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Resolved product is missing an identifier",
            )
        primary_exists = _has_primary(session, resolved_product.id)

    for payload in items:
        meta = fetch_url_metadata(payload.url, scraper_base_url, http_client_factory)
        parsed = urlparse(payload.url)
        host = parsed.hostname or "store"
        store_slug = _slugify(host.replace(".", "-"))
        normalized_title = _normalize_title(meta, host=host, search_query=search_query)
        product_slug = _slugify(normalized_title)
        currency = (meta.get("currency") or "USD").upper()
        locale = (meta.get("locale") or "en_US").strip() or "en_US"
        scrape_strategy = _build_scrape_strategy(meta, fallback_title=normalized_title)

        image_url = meta.get("image") or meta.get("image_url")
        scheme = parsed.scheme or "https"
        website_candidate = f"{scheme}://{host}"
        try:
            website_url = HTTP_URL_ADAPTER.validate_python(website_candidate)
        except ValidationError:
            website_url = None
        store = ensure_store_for_owner(
            session,
            owner,
            host=host,
            store_slug=store_slug,
            product_url=payload.url,
            strategy=scrape_strategy,
            website_url=website_url,
            currency=currency,
            locale=locale,
        )
        if store.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Persisted store is missing an identifier",
            )

        if resolved_product is None:
            resolved_product, created = _resolve_or_create_product(
                session,
                owner,
                base_title=normalized_title,
                slug=product_slug,
                image_url=str(image_url) if image_url else None,
            )
            created_product = created
        elif image_url and not resolved_product.image_url:
            resolved_product.image_url = str(image_url)
            session.add(resolved_product)
            session.commit()
            session.refresh(resolved_product)

        if resolved_product is None or resolved_product.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Resolved product is missing an identifier",
            )
        product_id = resolved_product.id
        if created_product and not primary_exists:
            primary_exists = _has_primary(session, product_id)

        try:
            validated_url = HTTP_URL_ADAPTER.validate_python(payload.url)
            normalized_url = str(validated_url)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        if _url_exists(session, product_id, normalized_url):
            skipped.append((normalized_url, "duplicate"))
            continue

        is_primary = bool(payload.set_primary)
        if not is_primary and not primary_exists:
            is_primary = True
        if is_primary:
            _clear_primary(session, product_id)
            primary_exists = False

        product_url_read = catalog.create_product_url(
            session,
            payload=ProductURLCreate(
                product_id=product_id,
                store_id=store.id,
                url=validated_url,
                is_primary=is_primary,
                active=True,
            ),
            owner=owner,
        )
        if product_url_read.id is None:
            skipped.append((normalized_url, "creation_failed"))
            continue

        created_price: float | None = None
        try:
            price_value = meta.get("price")
            if price_value not in (None, ""):
                coerced = _coerce_price(price_value)
                catalog.create_price_history(
                    session,
                    payload=PriceHistoryCreate(
                        product_id=product_id,
                        product_url_id=product_url_read.id,
                        price=coerced,
                        currency=currency,
                    ),
                    owner=owner,
                )
                created_price = coerced
        except Exception:
            created_price = None

        results.append(
            CreatedURLResult(
                product_url_id=product_url_read.id,
                store_id=product_url_read.store_id,
                url=str(product_url_read.url),
                is_primary=is_primary,
                price=created_price,
                currency=currency if created_price is not None else None,
            )
        )
        primary_exists = primary_exists or is_primary

    if resolved_product is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk import did not resolve a product",
        )
    session.refresh(resolved_product)
    if resolved_product.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resolved product lost its identifier after refresh",
        )
    final_product_id = resolved_product.id
    rebuild_product_price_cache(session, resolved_product)
    session.commit()
    session.refresh(resolved_product)

    if price_refresh is not None and results:
        price_refresh(final_product_id)

    assert resolved_product is not None

    created_entries = [
        {
            "product_url_id": entry.product_url_id,
            "store_id": entry.store_id,
            "url": entry.url,
            "is_primary": entry.is_primary,
            "price": entry.price,
            "currency": entry.currency,
        }
        for entry in results
    ]
    skipped_entries = [
        {"url": skipped_url, "reason": reason} for skipped_url, reason in skipped
    ]

    record_audit_log(
        session,
        action="product.bulk_import",
        actor_id=owner.id,
        entity_type="product",
        entity_id=str(final_product_id),
        ip_address=audit_ip,
        context={
            "created_product": created_product,
            "created_count": len(results),
            "created_urls": created_entries,
            "skipped": skipped_entries,
        },
    )

    return BulkImportResult(
        product=resolved_product,
        created_product=created_product,
        created_urls=results,
        skipped=skipped,
    )


__all__ = [
    "BulkImportResult",
    "CreatedURLResult",
    "ImportItemPayload",
    "bulk_import_product_urls",
]
