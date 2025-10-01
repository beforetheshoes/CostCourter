from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, TypeVar, cast

from fastapi import HTTPException, status
from pydantic import HttpUrl
from sqlalchemy import delete, func, update
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import BinaryExpression
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
from app.schemas import (
    PriceAggregates,
    PriceCacheEntry,
    PriceHistoryCreate,
    PriceHistoryPoint,
    PriceHistoryRead,
    PriceTrend,
    ProductBulkUpdateRequest,
    ProductBulkUpdateResponse,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ProductURLCreate,
    ProductURLMetadata,
    ProductURLRead,
    ProductURLRefreshResponse,
    ProductURLUpdate,
    StoreCreate,
    StoreRead,
    StoreStrategyField,
    StoreUpdate,
    TagCreate,
    TagMergeRequest,
    TagMergeResponse,
    TagRead,
    TagUpdate,
)
from app.services.audit import record_audit_log
from app.services.price_cache import rebuild_product_price_cache
from app.services.product_quick_add import (
    HttpClientFactory,
    fetch_url_metadata,
)


def _get_user_attr(user: User, attribute: str, default: Any = None) -> Any:
    namespace = getattr(user, "__dict__", None)
    if isinstance(namespace, dict) and attribute in namespace:
        return namespace[attribute]
    try:
        return getattr(user, attribute)
    except AttributeError:
        model_dump = getattr(user, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump(mode="python")
            except TypeError:
                dumped = model_dump()
            if isinstance(dumped, dict) and attribute in dumped:
                return dumped[attribute]
    return default


def _require_user_id(user: User) -> int:
    user_id = _get_user_attr(user, "id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user is missing an identifier",
        )
    return int(user_id)


def _resolve_scope_user_id(user: User, owner_id: int | None) -> int | None:
    if bool(_get_user_attr(user, "is_superuser", False)):
        return owner_id
    persisted_id = _require_user_id(user)
    if owner_id is not None and owner_id != persisted_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's catalog entries",
        )
    return persisted_id


SelectT = TypeVar("SelectT", bound=Select[Any])


def _apply_scope(
    statement: SelectT,
    *,
    user: User,
    owner_column: Any,
    owner_id: int | None = None,
) -> SelectT:
    scoped_id = _resolve_scope_user_id(user, owner_id)
    if scoped_id is None:
        return statement
    scoped_statement = statement.where(owner_column == scoped_id)
    return cast(SelectT, scoped_statement)


def _ensure_owned(entity_user_id: int, user: User) -> None:
    if bool(_get_user_attr(user, "is_superuser", False)):
        return
    if entity_user_id != _require_user_id(user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )


def _normalize_optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def create_store(session: Session, payload: StoreCreate, *, owner: User) -> StoreRead:
    owner_id = _require_user_id(owner)

    statement = select(Store).where(Store.slug == payload.slug)
    statement = statement.where(Store.user_id == owner_id)
    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Store slug already exists",
        )

    dump = payload.model_dump()
    domains = dump.pop("domains", [])
    strategy = dump.pop("scrape_strategy", {})
    settings_payload = dump.pop("settings", {})
    notes = dump.pop("notes", None)
    locale = _normalize_locale(dump.pop("locale", None))
    currency = _normalize_currency(dump.pop("currency", None))
    website_url = dump.get("website_url")
    if website_url is not None:
        dump["website_url"] = str(website_url)

    settings_payload = _merge_locale_settings(settings_payload, locale, currency)

    store = Store(
        user_id=owner_id,
        **dump,
        domains=domains,
        scrape_strategy=_normalise_strategy(strategy),
        settings=settings_payload,
        notes=notes,
        locale=locale,
        currency=currency,
    )
    session.add(store)
    session.commit()
    session.refresh(store)
    return StoreRead.model_validate(store)


def list_stores(
    session: Session,
    *,
    owner: User,
    limit: int,
    offset: int,
    search: str | None = None,
    active: bool | None = None,
    for_user_id: int | None = None,
) -> list[StoreRead]:
    statement = select(Store)
    statement = _apply_scope(
        statement,
        user=owner,
        owner_column=Store.user_id,
        owner_id=for_user_id,
    )
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(Store.name).like(pattern) | func.lower(Store.slug).like(pattern)
        )
    if active is not None:
        statement = statement.where(Store.active == active)

    statement = statement.order_by(Store.slug).offset(offset).limit(limit)
    stores = session.exec(statement).all()
    return [StoreRead.model_validate(store) for store in stores]


def update_store(
    session: Session, store_id: int, payload: StoreUpdate, *, owner: User
) -> StoreRead:
    store = _load_store(session, owner, store_id)
    updates = payload.model_dump(exclude_unset=True)

    if "slug" in updates:
        slug = updates["slug"]
        _ensure_present(slug, "Store slug cannot be null")
        slug_column = cast(Any, Store.slug)
        conflict_stmt = (
            select(Store)
            .where(slug_column == slug)
            .where(Store.id != store.id)
            .where(Store.user_id == store.user_id)
        )
        existing = session.exec(conflict_stmt).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Store slug already exists",
            )

    if "name" in updates:
        _ensure_present(updates["name"], "Store name cannot be null")
        store.name = updates["name"]
    if "slug" in updates:
        store.slug = updates["slug"]
    if "active" in updates:
        _ensure_present(updates["active"], "Store active flag cannot be null")
        store.active = updates["active"]
    if "website_url" in updates:
        website_url = updates["website_url"]
        store.website_url = str(website_url) if website_url is not None else None
    if "domains" in updates:
        domains = updates["domains"]
        _ensure_present(domains, "Store domains cannot be null")
        store.domains = domains
    if "scrape_strategy" in updates:
        strategy_updates = updates["scrape_strategy"]
        _ensure_present(strategy_updates, "Store strategy cannot be null")
        store.scrape_strategy = _normalise_strategy(strategy_updates)
    if "settings" in updates:
        settings_updates = updates["settings"]
        _ensure_present(settings_updates, "Store settings cannot be null")
        store.settings = settings_updates
    if "notes" in updates:
        store.notes = updates["notes"]
    if "locale" in updates:
        store.locale = _normalize_locale(updates["locale"])
    if "currency" in updates:
        store.currency = _normalize_currency(updates["currency"])

    store.settings = _merge_locale_settings(
        store.settings or {}, store.locale, store.currency
    )

    session.add(store)
    session.commit()
    session.refresh(store)
    return StoreRead.model_validate(store)


def delete_store(session: Session, store_id: int, *, owner: User) -> None:
    store = _load_store(session, owner, store_id)
    url_exists = session.exec(
        select(ProductURL.id).where(ProductURL.store_id == store.id)
    ).first()
    if url_exists is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Remove product URLs before deleting store",
        )

    session.delete(store)
    session.commit()


def _normalise_strategy(
    strategy: dict[str, StoreStrategyField | dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalised: dict[str, dict[str, Any]] = {}
    for key, value in strategy.items():
        if isinstance(value, StoreStrategyField):
            normalised[key] = value.model_dump()
        else:
            normalised[key] = value
    return normalised


def _normalize_locale(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized.upper() if normalized else None


def _merge_locale_settings(
    settings: dict[str, Any],
    locale: str | None,
    currency: str | None,
) -> dict[str, Any]:
    merged = dict(settings)
    locale_settings: dict[str, Any] = dict(merged.get("locale_settings") or {})

    if locale is not None:
        locale_settings["locale"] = locale
    elif "locale" not in locale_settings and locale_settings.get("locale") is None:
        locale_settings.pop("locale", None)

    if currency is not None:
        locale_settings["currency"] = currency
    elif "currency" not in locale_settings and locale_settings.get("currency") is None:
        locale_settings.pop("currency", None)

    if locale_settings:
        merged["locale_settings"] = locale_settings
    return merged


def create_tag(session: Session, payload: TagCreate, *, owner: User) -> TagRead:
    owner_id = _require_user_id(owner)

    slug_stmt = (
        select(Tag).where(Tag.slug == payload.slug).where(Tag.user_id == owner_id)
    )
    existing = session.exec(slug_stmt).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tag slug already exists",
        )

    name_stmt = (
        select(Tag).where(Tag.name == payload.name).where(Tag.user_id == owner_id)
    )
    name_conflict = session.exec(name_stmt).first()
    if name_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tag name already exists",
        )

    tag = Tag(user_id=owner_id, name=payload.name, slug=payload.slug)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return TagRead.model_validate(tag)


def list_tags(
    session: Session,
    *,
    owner: User,
    limit: int,
    offset: int,
    search: str | None = None,
    for_user_id: int | None = None,
) -> list[TagRead]:
    statement = select(Tag)
    statement = _apply_scope(
        statement,
        user=owner,
        owner_column=Tag.user_id,
        owner_id=for_user_id,
    )
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(Tag.name).like(pattern) | func.lower(Tag.slug).like(pattern)
        )

    statement = statement.order_by(Tag.slug).offset(offset).limit(limit)
    tags = session.exec(statement).all()
    return [TagRead.model_validate(tag) for tag in tags]


def update_tag(
    session: Session, tag_id: int, payload: TagUpdate, *, owner: User
) -> TagRead:
    tag = _load_tag(session, owner, tag_id)
    updates = payload.model_dump(exclude_unset=True)

    if "slug" in updates:
        slug = updates["slug"]
        _ensure_present(slug, "Tag slug cannot be null")
        slug_column = cast(Any, Tag.slug)
        conflict_stmt = select(Tag).where(slug_column == slug).where(Tag.id != tag.id)
        conflict_stmt = conflict_stmt.where(Tag.user_id == tag.user_id)
        existing = session.exec(conflict_stmt).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag slug already exists",
            )

    if "name" in updates:
        _ensure_present(updates["name"], "Tag name cannot be null")
        name_stmt = (
            select(Tag)
            .where(Tag.name == updates["name"])
            .where(Tag.id != tag.id)
            .where(Tag.user_id == tag.user_id)
        )
        name_conflict = session.exec(name_stmt).first()
        if name_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag name already exists",
            )
        tag.name = updates["name"]
    if "slug" in updates:
        tag.slug = updates["slug"]

    session.add(tag)
    session.commit()
    session.refresh(tag)
    return TagRead.model_validate(tag)


def delete_tag(session: Session, tag_id: int, *, owner: User) -> None:
    tag = _load_tag(session, owner, tag_id)
    link_exists = session.exec(
        select(ProductTagLink.product_id).where(ProductTagLink.tag_id == tag.id)
    ).first()
    if link_exists is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Remove product tag links before deleting tag",
        )

    session.delete(tag)
    session.commit()


def merge_tags(
    session: Session,
    payload: TagMergeRequest,
    *,
    owner: User,
) -> TagMergeResponse:
    source = _load_tag(session, owner, payload.source_tag_id)
    target = _load_tag(session, owner, payload.target_tag_id)

    source_id = source.id
    target_id = target.id
    assert source_id is not None
    assert target_id is not None

    link_stmt = select(ProductTagLink).where(ProductTagLink.tag_id == source_id)
    links = list(session.exec(link_stmt))

    moved = 0
    removed = 0
    for link in links:
        existing = session.get(ProductTagLink, (link.product_id, target_id))
        if existing is not None:
            session.delete(link)
            removed += 1
            continue
        link.tag_id = target_id
        session.add(link)
        moved += 1

    session.flush()

    deleted_source = False
    if payload.delete_source:
        remaining = session.exec(
            select(ProductTagLink.product_id).where(ProductTagLink.tag_id == source_id)
        ).first()
        if remaining is None:
            session.delete(source)
            deleted_source = True

    actor_id = _get_user_attr(owner, "id")
    record_audit_log(
        session,
        action="tag.merge",
        actor_id=int(actor_id) if actor_id is not None else None,
        entity_type="tag",
        entity_id=str(source_id),
        context={
            "source_tag_id": source_id,
            "target_tag_id": target_id,
            "moved_links": moved,
            "removed_duplicate_links": removed,
            "deleted_source": deleted_source,
        },
    )

    return TagMergeResponse(
        source_tag_id=source_id,
        target_tag_id=target_id,
        moved_links=moved,
        removed_duplicate_links=removed,
        deleted_source=deleted_source,
    )


def _ensure_present(value: Any, message: str) -> None:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


def _load_store(session: Session, owner: User, store_id: int) -> Store:
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        )
    assert store.user_id is not None
    _ensure_owned(store.user_id, owner)
    return store


def _load_tag(session: Session, owner: User, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
        )
    assert tag.user_id is not None
    _ensure_owned(tag.user_id, owner)
    return tag


def _load_product_url(session: Session, owner: User, product_url_id: int) -> ProductURL:
    product_url = session.get(ProductURL, product_url_id)
    if product_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product URL not found"
        )
    assert product_url.product_id is not None
    product = session.get(Product, product_url.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    assert product.user_id is not None
    _ensure_owned(product.user_id, owner)
    return product_url


def _load_product(session: Session, owner: User, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    assert product.user_id is not None
    _ensure_owned(product.user_id, owner)
    return product


def create_product(
    session: Session, payload: ProductCreate, *, owner: User
) -> ProductRead:
    owner_id = _require_user_id(owner)

    slug_stmt = (
        select(Product)
        .where(Product.slug == payload.slug)
        .where(Product.user_id == owner_id)
    )
    existing = session.exec(slug_stmt).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product slug already exists",
        )

    name_stmt = (
        select(Product)
        .where(Product.name == payload.name)
        .where(Product.user_id == owner_id)
    )
    name_conflict = session.exec(name_stmt).first()
    if name_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product name already exists",
        )

    tags: list[Tag] = []
    if payload.tag_slugs:
        tag_column = cast(Any, Tag.slug)
        tag_stmt = (
            select(Tag)
            .where(tag_column.in_(payload.tag_slugs))
            .where(Tag.user_id == owner_id)
        )
        tags = list(session.exec(tag_stmt))
        found_slugs = {tag.slug for tag in tags}
        missing = [slug for slug in payload.tag_slugs if slug not in found_slugs]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tag '{missing[0]}' not found",
            )

    product = Product(
        user_id=owner_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
        status=payload.status,
        favourite=payload.favourite,
        only_official=payload.only_official,
        notify_price=payload.notify_price,
        notify_percent=payload.notify_percent,
        ignored_urls=payload.ignored_urls,
        image_url=payload.image_url,
    )
    session.add(product)
    session.flush()
    assert product.id is not None
    if tags:
        for tag in tags:
            session.add(ProductTagLink(product_id=product.id, tag_id=tag.id))
    session.commit()
    return _build_product_read(session, owner, product.id)


def list_products(
    session: Session,
    *,
    owner: User,
    limit: int,
    offset: int,
    search: str | None = None,
    is_active: bool | None = None,
    tag: str | None = None,
    for_user_id: int | None = None,
) -> list[ProductRead]:
    slug_column = cast(Any, Product.slug)
    statement = select(Product)
    statement = _apply_scope(
        statement,
        user=owner,
        owner_column=Product.user_id,
        owner_id=for_user_id,
    )
    if search:
        pattern = f"%{search.lower()}%"
        lower_name = func.lower(Product.name)
        lower_slug = func.lower(Product.slug)
        statement = statement.where(lower_name.like(pattern) | lower_slug.like(pattern))
    if is_active is not None:
        statement = statement.where(Product.is_active == is_active)
    if tag:
        tag_column = cast(Any, Tag.slug)
        product_join = cast(
            BinaryExpression[bool], Product.id == ProductTagLink.product_id
        )
        tag_join = cast(BinaryExpression[bool], ProductTagLink.tag_id == Tag.id)
        statement = (
            statement.join(ProductTagLink, product_join)
            .join(Tag, tag_join)
            .where(func.lower(tag_column) == tag.lower())
        )
        statement = statement.distinct()

    statement = statement.order_by(slug_column).offset(offset).limit(limit)
    products = list(session.exec(statement))
    return [
        _build_product_read_from_instance(session, owner, product)
        for product in products
    ]


def get_product(session: Session, product_id: int, *, owner: User) -> ProductRead:
    return _build_product_read(session, owner, product_id)


def update_product(
    session: Session, product_id: int, payload: ProductUpdate, *, owner: User
) -> ProductRead:
    product = _load_product(session, owner, product_id)
    updates = payload.model_dump(exclude_unset=True)

    if "slug" in updates:
        slug = updates["slug"]
        _ensure_present(slug, "Product slug cannot be null")
        slug_column = cast(Any, Product.slug)
        conflict_stmt = (
            select(Product).where(slug_column == slug).where(Product.id != product.id)
        ).where(Product.user_id == product.user_id)
        existing = session.exec(conflict_stmt).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Product slug already exists",
            )

    if "name" in updates:
        _ensure_present(updates["name"], "Product name cannot be null")
        name_stmt = (
            select(Product)
            .where(Product.name == updates["name"])
            .where(Product.id != product.id)
            .where(Product.user_id == product.user_id)
        )
        name_conflict = session.exec(name_stmt).first()
        if name_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Product name already exists",
            )
        product.name = updates["name"]
    if "slug" in updates:
        product.slug = updates["slug"]
    if "description" in updates:
        product.description = updates["description"]
    if "is_active" in updates:
        _ensure_present(updates["is_active"], "Product active flag cannot be null")
        product.is_active = updates["is_active"]
    if "status" in updates:
        _ensure_present(updates["status"], "Product status cannot be null")
        product.status = updates["status"]
    if "favourite" in updates:
        _ensure_present(updates["favourite"], "Product favourite flag cannot be null")
        product.favourite = updates["favourite"]
    if "only_official" in updates:
        _ensure_present(
            updates["only_official"], "Product only_official flag cannot be null"
        )
        product.only_official = updates["only_official"]
    if "notify_price" in updates:
        product.notify_price = updates["notify_price"]
    if "notify_percent" in updates:
        product.notify_percent = updates["notify_percent"]
    if "ignored_urls" in updates:
        _ensure_present(updates["ignored_urls"], "Ignored URLs cannot be null")
        product.ignored_urls = updates["ignored_urls"]
    if "image_url" in updates:
        product.image_url = updates["image_url"]

    if "tag_slugs" in updates:
        tag_slugs = updates["tag_slugs"]
        _ensure_present(tag_slugs, "Tag slugs cannot be null")
        tags: list[Tag] = []
        if tag_slugs:
            tag_column = cast(Any, Tag.slug)
            tag_stmt = (
                select(Tag)
                .where(tag_column.in_(tag_slugs))
                .where(Tag.user_id == product.user_id)
            )
            tags = list(session.exec(tag_stmt))
            found_slugs = {tag.slug for tag in tags}
            missing = [slug for slug in tag_slugs if slug not in found_slugs]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tag '{missing[0]}' not found",
                )

        link_stmt = select(ProductTagLink).where(
            ProductTagLink.product_id == product.id
        )
        links = list(session.exec(link_stmt))
        for link in links:
            session.delete(link)
        session.flush()
        for tag in tags:
            session.add(ProductTagLink(product_id=product.id, tag_id=tag.id))

    session.add(product)
    session.commit()
    return _build_product_read_from_instance(session, owner, product)


def delete_product(session: Session, product_id: int, *, owner: User) -> None:
    product = _load_product(session, owner, product_id)

    price_history_stmt = select(PriceHistory).where(
        PriceHistory.product_id == product.id
    )
    for history in session.exec(price_history_stmt):
        session.delete(history)

    url_stmt = select(ProductURL).where(ProductURL.product_id == product.id)
    for url in session.exec(url_stmt):
        session.delete(url)

    tag_link_product = cast(Any, ProductTagLink.product_id)
    link_delete_stmt = delete(ProductTagLink).where(tag_link_product == product.id)
    session.exec(link_delete_stmt)

    session.delete(product)
    session.commit()


def bulk_update_products(
    session: Session,
    payload: ProductBulkUpdateRequest,
    *,
    owner: User,
) -> ProductBulkUpdateResponse:
    updates = payload.updates.model_dump(exclude_none=True)
    product_ids = payload.product_ids

    product_id_column = cast(Any, Product.id)
    statement = select(Product).where(product_id_column.in_(product_ids))
    products = list(session.exec(statement))
    found_ids = {product.id for product in products if product.id is not None}
    missing_ids = [pid for pid in product_ids if pid not in found_ids]

    updated_ids: list[int] = []
    skipped_ids: list[int] = []

    for product in products:
        assert product.id is not None
        assert product.user_id is not None
        _ensure_owned(product.user_id, owner)

        changed = False
        for field, value in updates.items():
            if getattr(product, field) != value:
                setattr(product, field, value)
                changed = True
        if changed:
            session.add(product)
            updated_ids.append(product.id)
        else:
            skipped_ids.append(product.id)

    if updated_ids:
        actor_id = _get_user_attr(owner, "id")
        record_audit_log(
            session,
            action="product.bulk_update",
            actor_id=int(actor_id) if actor_id is not None else None,
            entity_type="product",
            entity_id="bulk",
            context={
                "updated_ids": updated_ids,
                "skipped_ids": skipped_ids,
                "missing_ids": missing_ids,
                "updates": updates,
            },
        )
    else:
        session.commit()

    return ProductBulkUpdateResponse(
        updated_ids=updated_ids,
        skipped_ids=skipped_ids,
        missing_ids=missing_ids,
    )


def _build_product_read(session: Session, owner: User, product_id: int) -> ProductRead:
    product = _load_product(session, owner, product_id)
    return _build_product_read_from_instance(session, owner, product)


def _load_product_tags(session: Session, product_id: int) -> list[Tag]:
    tag_id_column = cast(Any, ProductTagLink.tag_id)
    product_id_column = cast(Any, ProductTagLink.product_id)
    tag_primary = cast(Any, Tag.id)
    tag_slug = cast(Any, Tag.slug)
    tag_stmt = (
        select(Tag)
        .join(ProductTagLink, tag_primary == tag_id_column)
        .where(product_id_column == product_id)
        .order_by(tag_slug)
    )
    return list(session.exec(tag_stmt))


def _load_product_urls(
    session: Session, product_id: int
) -> list[tuple[ProductURL, Store | None]]:
    store_id_column = cast(Any, Store.id)
    product_url_store = cast(Any, ProductURL.store_id)
    product_url_product = cast(Any, ProductURL.product_id)
    product_url_id = cast(Any, ProductURL.id)
    product_url_primary = cast(Any, ProductURL.is_primary)
    url_stmt = (
        select(ProductURL, Store)
        .join(
            Store,
            onclause=product_url_store == store_id_column,
            isouter=True,
        )
        .where(product_url_product == product_id)
        .order_by(product_url_primary.desc(), product_url_id)
    )
    rows = list(session.exec(url_stmt))
    return [(product_url, cast(Store | None, store)) for product_url, store in rows]


def _load_latest_price_read(
    session: Session, product_id: int
) -> PriceHistoryRead | None:
    recorded_at_column = cast(Any, PriceHistory.recorded_at)
    id_column = cast(Any, PriceHistory.id)
    statement = (
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id)
        .order_by(recorded_at_column.desc(), id_column.desc())
        .limit(1)
    )
    entry = session.exec(statement).first()
    if entry is None:
        return None

    product_url: ProductURL | None = None
    if entry.product_url_id is not None:
        product_url = session.get(ProductURL, entry.product_url_id)

    return _build_price_history_read_from_instance(session, entry, product_url)


def _build_product_read_from_instance(
    session: Session, _owner: User, product: Product
) -> ProductRead:
    assert product.id is not None
    tags = _load_product_tags(session, product.id)
    urls_with_store = _load_product_urls(session, product.id)
    latest_price = _load_latest_price_read(session, product.id)
    price_cache_entries = [
        PriceCacheEntry.model_validate(entry) for entry in (product.price_cache or [])
    ]
    price_entries_by_url_id = {
        int(entry.url_id): entry
        for entry in price_cache_entries
        if entry.url_id is not None
    }
    summary_entry = _select_price_summary_entry(price_cache_entries, urls_with_store)
    last_refreshed_at = _resolve_last_refreshed_at(summary_entry, latest_price)
    history_points = _build_history_points(summary_entry, latest_price)
    aggregates = _calculate_product_aggregates(price_cache_entries, summary_entry)
    tag_payloads = [TagRead.model_validate(tag) for tag in tags]
    url_payloads: list[ProductURLRead] = []
    for url, store in urls_with_store:
        price_entry = (
            price_entries_by_url_id.get(url.id) if url.id is not None else None
        )
        url_payloads.append(
            _build_product_url_read_from_instance(
                url,
                store,
                price_entry=price_entry,
            )
        )
    return ProductRead(
        id=product.id,
        name=product.name,
        slug=product.slug,
        description=product.description,
        is_active=product.is_active,
        status=product.status,
        favourite=product.favourite,
        only_official=product.only_official,
        notify_price=product.notify_price,
        notify_percent=product.notify_percent,
        current_price=product.current_price,
        price_cache=price_cache_entries,
        price_trend=summary_entry.trend if summary_entry else PriceTrend.NONE,
        last_refreshed_at=last_refreshed_at,
        history_points=history_points,
        price_aggregates=aggregates,
        ignored_urls=list(product.ignored_urls or []),
        image_url=product.image_url,
        tags=tag_payloads,
        urls=url_payloads,
        latest_price=latest_price,
    )


def _select_price_summary_entry(
    entries: Sequence[PriceCacheEntry],
    urls_with_store: Sequence[tuple[ProductURL, Store | None]],
) -> PriceCacheEntry | None:
    if not entries:
        return None

    primary_url_ids = {
        url.id for url, _ in urls_with_store if url.is_primary and url.id is not None
    }
    for entry in entries:
        if entry.url_id is not None and entry.url_id in primary_url_ids:
            return entry
    return entries[0]


def _resolve_last_refreshed_at(
    summary_entry: PriceCacheEntry | None,
    latest_price: PriceHistoryRead | None,
) -> datetime | None:
    if summary_entry and summary_entry.last_scrape is not None:
        return summary_entry.last_scrape
    if latest_price is not None:
        return latest_price.recorded_at
    return None


def _build_history_points(
    summary_entry: PriceCacheEntry | None,
    latest_price: PriceHistoryRead | None,
    *,
    limit: int = 30,
) -> list[PriceHistoryPoint]:
    if summary_entry is not None:
        sorted_history = sorted(summary_entry.history.items())
        trimmed = sorted_history[-limit:]
        points: list[PriceHistoryPoint] = []
        for day_str, price in trimmed:
            try:
                day = date.fromisoformat(day_str)
            except ValueError:
                continue
            points.append(PriceHistoryPoint(date=day, price=price))
        if points:
            return points

    if latest_price is not None:
        recorded = latest_price.recorded_at
        return [
            PriceHistoryPoint(
                date=recorded.date(),
                price=float(latest_price.price),
            )
        ]

    return []


def _calculate_product_aggregates(
    entries: Sequence[PriceCacheEntry],
    summary_entry: PriceCacheEntry | None,
) -> PriceAggregates | None:
    prices: list[float] = []
    currency: str | None = None
    locale: str | None = None

    for entry in entries:
        if currency is None and entry.currency:
            currency = entry.currency
        if locale is None and entry.locale:
            locale = entry.locale
        prices.extend(entry.history.values())

    if not prices:
        return None

    currency = currency or (summary_entry.currency if summary_entry else None)
    locale = locale or (summary_entry.locale if summary_entry else None)

    minimum = min(prices)
    maximum = max(prices)
    average = sum(prices) / len(prices)

    return PriceAggregates(
        min=round(minimum, 2),
        max=round(maximum, 2),
        avg=round(average, 2),
        currency=currency,
        locale=locale,
    )


def _clear_other_primary_product_urls(
    session: Session,
    *,
    product_id: int,
    exclude_id: int | None = None,
) -> None:
    product_fk = cast(Any, ProductURL.product_id)
    url_id = cast(Any, ProductURL.id)
    statement = update(ProductURL).where(product_fk == product_id)
    if exclude_id is not None:
        statement = statement.where(url_id != exclude_id)
    session.exec(statement.values(is_primary=False))


def create_product_url(
    session: Session, payload: ProductURLCreate, *, owner: User
) -> ProductURLRead:
    product = _load_product(session, owner, payload.product_id)
    store = _load_store(session, owner, payload.store_id)

    if product.user_id != store.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store does not belong to the product owner",
        )

    created_by_id: int | None = None
    if payload.created_by_id is not None:
        user = session.get(User, payload.created_by_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        created_by_id = user.id

    product_url = ProductURL(
        product_id=product.id,
        store_id=store.id,
        created_by_id=created_by_id,
        url=str(payload.url),
        is_primary=payload.is_primary,
        active=payload.active,
    )
    session.add(product_url)
    session.flush()
    if product_url.is_primary:
        assert product.id is not None
        assert product_url.id is not None
        _clear_other_primary_product_urls(
            session,
            product_id=product.id,
            exclude_id=product_url.id,
        )
    session.commit()
    session.refresh(product_url)
    return _build_product_url_read_from_instance(product_url, store)


def list_product_urls(
    session: Session,
    *,
    owner: User,
    limit: int,
    offset: int,
    product_id: int | None = None,
    store_id: int | None = None,
    active: bool | None = None,
    for_user_id: int | None = None,
) -> list[ProductURLRead]:
    store_id_column = cast(Any, Store.id)
    product_url_store = cast(Any, ProductURL.store_id)
    product_url_product = cast(Any, ProductURL.product_id)
    product_url_id = cast(Any, ProductURL.id)
    statement = (
        select(ProductURL, Store)
        .join(
            Store,
            onclause=product_url_store == store_id_column,
            isouter=True,
        )
        .join(Product, product_url_product == Product.id)
    )
    statement = _apply_scope(
        statement,
        user=owner,
        owner_column=Product.user_id,
        owner_id=for_user_id,
    )
    if product_id is not None:
        statement = statement.where(product_url_product == product_id)
    if store_id is not None:
        statement = statement.where(product_url_store == store_id)
    if active is not None:
        statement = statement.where(ProductURL.active == active)

    statement = statement.order_by(product_url_id).offset(offset).limit(limit)
    rows = list(session.exec(statement))
    typed_rows: list[tuple[ProductURL, Store | None]] = [
        (product_url, cast(Store | None, store)) for product_url, store in rows
    ]
    return [
        _build_product_url_read_from_instance(url, store) for url, store in typed_rows
    ]


def update_product_url(
    session: Session,
    product_url_id: int,
    payload: ProductURLUpdate,
    *,
    owner: User,
) -> ProductURLRead:
    product_url = _load_product_url(session, owner, product_url_id)
    updates = payload.model_dump(exclude_unset=True)

    resolved_store: Store | None = None
    product = session.get(Product, product_url.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if "store_id" in updates:
        store_id = updates["store_id"]
        _ensure_present(store_id, "Store id cannot be null")
        store_identifier = cast(int, store_id)
        resolved_store = _load_store(session, owner, store_identifier)
        if resolved_store.user_id != product.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Store does not belong to the product owner",
            )
        assert resolved_store.id is not None
        product_url.store_id = resolved_store.id

    if "url" in updates:
        url_value = updates["url"]
        _ensure_present(url_value, "Product URL cannot be null")
        product_url.url = str(url_value)
    if "is_primary" in updates:
        _ensure_present(updates["is_primary"], "Primary flag cannot be null")
        product_url.is_primary = updates["is_primary"]
    if "active" in updates:
        _ensure_present(updates["active"], "Active flag cannot be null")
        product_url.active = updates["active"]
    if "created_by_id" in updates:
        created_by_id = updates["created_by_id"]
        if created_by_id is not None:
            user = session.get(User, created_by_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )
            product_url.created_by_id = user.id
        else:
            product_url.created_by_id = None

    session.add(product_url)
    set_primary = updates.get("is_primary") is True
    session.flush()
    if set_primary:
        assert product.id is not None
        assert product_url.id is not None
        _clear_other_primary_product_urls(
            session,
            product_id=product.id,
            exclude_id=product_url.id,
        )
    session.commit()
    session.refresh(product_url)
    if resolved_store is None:
        resolved_store = product_url.store
    return _build_product_url_read_from_instance(product_url, resolved_store)


def refresh_product_url_metadata(
    session: Session,
    *,
    owner: User,
    product_url_id: int,
    scraper_base_url: str | None,
    http_client_factory: HttpClientFactory | None,
) -> ProductURLRefreshResponse:
    product_url = _load_product_url(session, owner, product_url_id)
    product = session.get(Product, product_url.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    diagnostics: list[str] = []
    raw_metadata = fetch_url_metadata(
        product_url.url,
        scraper_base_url,
        http_client_factory,
        diagnostics=diagnostics,
    )
    metadata_payload = dict(raw_metadata)
    metadata_payload.pop("raw_html", None)

    metadata_kwargs: dict[str, Any] = {}
    for key in ("title", "description", "image", "locale"):
        value = _normalize_optional_str(metadata_payload.get(key))
        if value is not None:
            metadata_kwargs[key] = value

    price_value = metadata_payload.get("price")
    if price_value is not None:
        normalized_price = _normalize_optional_str(str(price_value))
        if normalized_price is not None:
            metadata_kwargs["price"] = normalized_price

    currency_value = metadata_payload.get("currency")
    if currency_value is not None:
        normalized_currency = _normalize_optional_str(str(currency_value))
        if normalized_currency is not None:
            metadata_kwargs["currency"] = normalized_currency.upper()

    metadata_model = ProductURLMetadata(**metadata_kwargs)

    name_updated = False
    image_updated = False

    new_name = metadata_model.title
    if new_name and new_name != product.name:
        product.name = new_name
        name_updated = True

    new_image = metadata_model.image
    if new_image and new_image != (product.image_url or ""):
        product.image_url = new_image
        image_updated = True

    if name_updated or image_updated:
        session.add(product)
        session.commit()
        session.refresh(product)
    else:
        session.rollback()

    if product_url.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Product URL missing identifier",
        )

    return ProductURLRefreshResponse(
        product_id=product_url.product_id,
        product_url_id=product_url.id,
        metadata=metadata_model,
        applied_name=product.name,
        applied_image_url=product.image_url,
        name_updated=name_updated,
        image_updated=image_updated,
        warnings=diagnostics,
    )


def delete_product_url(session: Session, product_url_id: int, *, owner: User) -> None:
    product_url = _load_product_url(session, owner, product_url_id)
    assert product_url.id is not None
    product_id = product_url.product_id

    history_stmt = select(PriceHistory).where(
        PriceHistory.product_url_id == product_url.id
    )
    for price_history in session.exec(history_stmt):
        session.delete(price_history)

    session.delete(product_url)
    session.flush()

    if product_id is not None:
        product = session.get(Product, product_id)
        if product is not None:
            rebuild_product_price_cache(session, product)

    session.commit()


def _build_product_url_read_from_instance(
    url: ProductURL,
    store: Store | None = None,
    *,
    price_entry: PriceCacheEntry | None = None,
) -> ProductURLRead:
    store_model = None
    resolved_store = store if store is not None else url.store
    if resolved_store is not None:
        store_model = StoreRead.model_validate(resolved_store)

    assert url.id is not None

    return ProductURLRead(
        id=url.id,
        product_id=url.product_id,
        store_id=url.store_id,
        url=cast(HttpUrl, url.url),
        is_primary=url.is_primary,
        active=url.active,
        created_by_id=url.created_by_id,
        store=store_model,
        latest_price=price_entry.price if price_entry else None,
        latest_price_currency=price_entry.currency if price_entry else None,
        latest_price_at=price_entry.last_scrape if price_entry else None,
    )


def create_price_history(
    session: Session, payload: PriceHistoryCreate, *, owner: User
) -> PriceHistoryRead:
    product = _load_product(session, owner, payload.product_id)

    product_url: ProductURL | None = None
    if payload.product_url_id is not None:
        product_url = _load_product_url(session, owner, payload.product_url_id)
        if product_url.product_id != product.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product URL does not belong to product",
            )

    price_history_kwargs: dict[str, Any] = {
        "product_id": product.id,
        "product_url_id": payload.product_url_id,
        "price": payload.price,
        "currency": payload.currency,
    }
    if payload.recorded_at is not None:
        price_history_kwargs["recorded_at"] = payload.recorded_at

    price_history = PriceHistory(**price_history_kwargs)
    session.add(price_history)
    session.flush()
    rebuild_product_price_cache(session, product)
    session.commit()
    session.refresh(price_history)
    session.refresh(product)
    return _build_price_history_read_from_instance(session, price_history, product_url)


def list_price_history(
    session: Session,
    *,
    owner: User,
    product_id: int | None = None,
    product_url_id: int | None = None,
    for_user_id: int | None = None,
) -> list[PriceHistoryRead]:
    resolved_product_id = product_id
    resolved_product_url_id = product_url_id

    if product_id is not None:
        product = _load_product(session, owner, product_id)
        resolved_product_id = product.id
    if product_url_id is not None:
        product_url = _load_product_url(session, owner, product_url_id)
        resolved_product_url_id = product_url.id
        if resolved_product_id is None:
            resolved_product_id = product_url.product_id

    recorded_at_column = cast(Any, PriceHistory.recorded_at)
    id_column = cast(Any, PriceHistory.id)
    statement = select(PriceHistory).join(
        Product, onclause=cast(Any, PriceHistory.product_id == Product.id)
    )
    statement = _apply_scope(
        statement,
        user=owner,
        owner_column=Product.user_id,
        owner_id=for_user_id,
    )
    statement = statement.order_by(recorded_at_column.desc(), id_column.desc())
    if resolved_product_id is not None:
        statement = statement.where(PriceHistory.product_id == resolved_product_id)
    if resolved_product_url_id is not None:
        statement = statement.where(
            PriceHistory.product_url_id == resolved_product_url_id
        )
    entries = list(session.exec(statement))
    return [
        _build_price_history_read_from_instance(session, entry) for entry in entries
    ]


def _load_product_url_with_store(
    session: Session, product_url_id: int
) -> tuple[ProductURL, Store | None] | None:
    store_id_column = cast(Any, Store.id)
    product_url_store = cast(Any, ProductURL.store_id)
    statement = (
        select(ProductURL, Store)
        .join(
            Store,
            onclause=product_url_store == store_id_column,
            isouter=True,
        )
        .where(ProductURL.id == product_url_id)
    )
    return session.exec(statement).first()


def _build_price_history_read_from_instance(
    session: Session,
    entry: PriceHistory,
    product_url: ProductURL | None = None,
) -> PriceHistoryRead:
    product_url_payload = None
    if entry.product_url_id is not None:
        if product_url is None or product_url.id != entry.product_url_id:
            product_url_row = _load_product_url_with_store(
                session, entry.product_url_id
            )
            if product_url_row is not None:
                product_url, store = product_url_row
                product_url_payload = _build_product_url_read_from_instance(
                    product_url, store
                )
        elif product_url is not None:
            product_url_payload = _build_product_url_read_from_instance(product_url)

    assert entry.id is not None

    return PriceHistoryRead(
        id=entry.id,
        product_id=entry.product_id,
        product_url_id=entry.product_url_id,
        price=entry.price,
        currency=entry.currency,
        recorded_at=entry.recorded_at,
        product_url=product_url_payload,
    )
