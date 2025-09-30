from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic import HttpUrl
from sqlmodel import Session, select

from app.models import (
    PriceHistory,
    Product,
    ProductTagLink,
    ProductURL,
    Store,
    Tag,
    User,
)
from app.models.base import utcnow
from app.schemas.backup import (
    BackupPriceHistory,
    BackupProduct,
    BackupProductURL,
    BackupStore,
    BackupTag,
    CatalogBackup,
    CatalogImportResponse,
    ProductBackupEntry,
)
from app.services.catalog import _require_user_id
from app.services.price_cache import rebuild_product_price_cache


def export_catalog_backup(session: Session, *, owner: User) -> CatalogBackup:
    owner_id = _require_user_id(owner)

    product_rows = session.exec(
        select(Product).where(Product.user_id == owner_id).order_by(Product.slug)
    ).all()

    entries: list[ProductBackupEntry] = []
    for product in product_rows:
        tag_join_on = cast(Any, ProductTagLink.tag_id == Tag.id)
        tag_rows = session.exec(
            select(Tag)
            .join(ProductTagLink, tag_join_on)
            .where(ProductTagLink.product_id == product.id)
            .order_by(cast(Any, Tag.slug))
        ).all()
        tag_payloads = [BackupTag(slug=tag.slug, name=tag.name) for tag in tag_rows]

        url_join_on = cast(Any, ProductURL.store_id == Store.id)
        url_rows = session.exec(
            select(ProductURL, Store)
            .join(Store, url_join_on)
            .where(ProductURL.product_id == product.id)
            .order_by(cast(Any, ProductURL.id))
        ).all()

        url_by_id: dict[int, ProductURL] = {}
        url_payloads: list[BackupProductURL] = []
        for url, store in url_rows:
            store_payload = BackupStore(
                slug=store.slug,
                name=store.name,
                website_url=(
                    cast(HttpUrl, store.website_url)
                    if store.website_url is not None
                    else None
                ),
                active=store.active,
                locale=store.locale,
                currency=store.currency,
                domains=deepcopy(store.domains),
                scrape_strategy=deepcopy(store.scrape_strategy),
                settings=deepcopy(store.settings),
                notes=store.notes,
            )
            url_payloads.append(
                BackupProductURL(
                    url=cast(HttpUrl, url.url),
                    is_primary=url.is_primary,
                    active=url.active,
                    store=store_payload,
                )
            )
            if url.id is not None:
                url_by_id[url.id] = url

        price_rows = session.exec(
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .order_by(
                cast(Any, PriceHistory.recorded_at),
                cast(Any, PriceHistory.id),
            )
        ).all()
        price_payloads: list[BackupPriceHistory] = []
        for entry in price_rows:
            url_value = None
            if entry.product_url_id is not None:
                linked = url_by_id.get(entry.product_url_id)
                if linked is not None:
                    url_value = linked.url
            price_payloads.append(
                BackupPriceHistory(
                    price=entry.price,
                    currency=entry.currency,
                    recorded_at=entry.recorded_at,
                    url=(cast(HttpUrl, url_value) if url_value is not None else None),
                )
            )

        backup_product = BackupProduct(
            name=product.name,
            slug=product.slug,
            description=product.description,
            is_active=product.is_active,
            status=product.status,
            favourite=product.favourite,
            only_official=product.only_official,
            notify_price=product.notify_price,
            notify_percent=product.notify_percent,
            ignored_urls=list(product.ignored_urls or []),
            image_url=product.image_url,
            tag_slugs=[tag.slug for tag in tag_rows],
            tags=tag_payloads,
        )

        entries.append(
            ProductBackupEntry(
                product=backup_product,
                urls=url_payloads,
                price_history=price_payloads,
            )
        )

    return CatalogBackup(
        exported_at=utcnow(),
        products=entries,
    )


def import_catalog_backup(
    session: Session, backup: CatalogBackup, *, owner: User
) -> CatalogImportResponse:
    owner_id = _require_user_id(owner)

    products_created = 0
    products_updated = 0
    product_urls_created = 0
    product_urls_updated = 0
    price_history_created = 0
    price_history_skipped = 0
    created_store_slugs: set[str] = set()
    updated_store_slugs: set[str] = set()
    created_tag_slugs: set[str] = set()
    updated_tag_slugs: set[str] = set()

    tag_map: dict[str, Tag] = {
        tag.slug: tag
        for tag in session.exec(select(Tag).where(Tag.user_id == owner_id)).all()
    }
    store_map: dict[str, Store] = {
        store.slug: store
        for store in session.exec(select(Store).where(Store.user_id == owner_id)).all()
    }

    try:
        for entry in backup.products:
            product_data = entry.product
            product = session.exec(
                select(Product)
                .where(Product.user_id == owner_id)
                .where(Product.slug == product_data.slug)
            ).first()

            if product is None:
                product = Product(
                    user_id=owner_id,
                    name=product_data.name,
                    slug=product_data.slug,
                )
                session.add(product)
                session.flush()
                products_created += 1
            else:
                if product.name != product_data.name:
                    product.name = product_data.name
                products_updated += 1

            product.description = product_data.description
            product.is_active = product_data.is_active
            product.status = product_data.status
            product.favourite = product_data.favourite
            product.only_official = product_data.only_official
            product.notify_price = product_data.notify_price
            product.notify_percent = product_data.notify_percent
            product.ignored_urls = list(product_data.ignored_urls)
            product.image_url = product_data.image_url
            session.add(product)
            session.flush()

            desired_slugs = list(dict.fromkeys(product_data.tag_slugs))
            tag_details: dict[str, BackupTag] = {
                tag.slug: tag for tag in product_data.tags
            }

            for slug in desired_slugs:
                existing = tag_map.get(slug)
                detail = tag_details.get(slug)
                expected_name = (
                    detail.name
                    if detail is not None
                    else slug.replace("-", " ").title()
                )
                if existing is None:
                    tag = Tag(
                        user_id=owner_id,
                        slug=slug,
                        name=expected_name or slug,
                    )
                    session.add(tag)
                    session.flush()
                    tag_map[slug] = tag
                    created_tag_slugs.add(slug)
                else:
                    if expected_name and existing.name != expected_name:
                        existing.name = expected_name
                        if slug not in created_tag_slugs:
                            updated_tag_slugs.add(slug)

            existing_links = session.exec(
                select(ProductTagLink).where(ProductTagLink.product_id == product.id)
            ).all()
            existing_tag_ids = {link.tag_id for link in existing_links}
            desired_tag_ids = {
                tag_map[slug].id for slug in desired_slugs if slug in tag_map
            }

            for link in existing_links:
                if link.tag_id not in desired_tag_ids:
                    session.delete(link)

            for tag_id in desired_tag_ids - existing_tag_ids:
                session.add(ProductTagLink(product_id=product.id, tag_id=tag_id))

            url_map = {
                url.url: url
                for url in session.exec(
                    select(ProductURL).where(ProductURL.product_id == product.id)
                ).all()
            }

            for url_entry in entry.urls:
                store_payload = url_entry.store
                store_slug = store_payload.slug
                website_url = (
                    str(store_payload.website_url)
                    if store_payload.website_url is not None
                    else None
                )
                store = store_map.get(store_slug)
                store_values = {
                    "name": store_payload.name,
                    "website_url": website_url,
                    "active": store_payload.active,
                    "locale": store_payload.locale,
                    "currency": store_payload.currency,
                    "domains": [deepcopy(domain) for domain in store_payload.domains],
                    "scrape_strategy": deepcopy(store_payload.scrape_strategy),
                    "settings": deepcopy(store_payload.settings),
                    "notes": store_payload.notes,
                }
                if store is None:
                    store = Store(
                        user_id=owner_id,
                        slug=store_slug,
                        **store_values,
                    )
                    session.add(store)
                    session.flush()
                    session.refresh(store)
                    store_map[store_slug] = store
                    created_store_slugs.add(store_slug)
                else:
                    updated = False
                    for field, value in store_values.items():
                        if getattr(store, field) != value:
                            setattr(store, field, value)
                            updated = True
                    if updated and store_slug not in created_store_slugs:
                        updated_store_slugs.add(store_slug)

                if store.id is None:
                    session.refresh(store)
                assert store.id is not None

                url_key = str(url_entry.url)
                product_url = url_map.get(url_key)
                if product_url is None:
                    product_url = ProductURL(
                        product_id=product.id,
                        store_id=store.id,
                        url=url_key,
                        is_primary=url_entry.is_primary,
                        active=url_entry.active,
                    )
                    session.add(product_url)
                    session.flush()
                    session.refresh(product_url)
                    url_map[url_key] = product_url
                    product_urls_created += 1
                else:
                    if product_url.id is None:
                        session.refresh(product_url)
                    updated = False
                    if product_url.store_id != store.id:
                        product_url.store_id = store.id
                        updated = True
                    if product_url.is_primary != url_entry.is_primary:
                        product_url.is_primary = url_entry.is_primary
                        updated = True
                    if product_url.active != url_entry.active:
                        product_url.active = url_entry.active
                        updated = True
                    if updated:
                        product_urls_updated += 1

            existing_history = session.exec(
                select(PriceHistory).where(PriceHistory.product_id == product.id)
            ).all()
            history_keys = {
                (
                    entry.recorded_at,
                    entry.price,
                    entry.currency,
                    entry.product_url_id,
                )
                for entry in existing_history
            }

            for price_entry in entry.price_history:
                url_value = (
                    str(price_entry.url) if price_entry.url is not None else None
                )
                linked_url = url_map.get(url_value) if url_value is not None else None
                if linked_url is not None and linked_url.id is None:
                    session.refresh(linked_url)
                product_url_id: int | None = (
                    linked_url.id if linked_url and linked_url.id is not None else None
                )
                history_key = (
                    price_entry.recorded_at,
                    price_entry.price,
                    price_entry.currency,
                    product_url_id,
                )
                if history_key in history_keys:
                    price_history_skipped += 1
                    continue
                price_record = PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url_id,
                    price=price_entry.price,
                    currency=price_entry.currency,
                    recorded_at=price_entry.recorded_at,
                )
                session.add(price_record)
                session.flush()
                history_keys.add(history_key)
                price_history_created += 1

            rebuild_product_price_cache(session, product)

        session.commit()
    except Exception:
        session.rollback()
        raise

    return CatalogImportResponse(
        products_created=products_created,
        products_updated=products_updated,
        product_urls_created=product_urls_created,
        product_urls_updated=product_urls_updated,
        price_history_created=price_history_created,
        price_history_skipped=price_history_skipped,
        stores_created=len(created_store_slugs),
        stores_updated=len(updated_store_slugs),
        tags_created=len(created_tag_slugs),
        tags_updated=len(updated_tag_slugs),
    )
