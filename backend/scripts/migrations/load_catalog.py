from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Annotated, Any

import structlog
import typer
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .common import build_engine, engine_scope, info

app = typer.Typer(add_completion=False)
log = structlog.get_logger(__name__)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\-\s]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value or "item"


def _fetch_rows(
    conn: Connection,
    sql: str,
    params: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = conn.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


def _coerce_json_field(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            log.warning("etl.catalog.json_decode_failed", sample=value[:64])
            return default
    if isinstance(value, (dict, list)):
        return value
    return default


def _normalise_domains(value: Any) -> list[dict[str, str]]:
    domains = _coerce_json_field(value, default=[])
    if isinstance(domains, dict):
        domains = [domains]
    normalised: list[dict[str, str]] = []
    if isinstance(domains, list):
        for entry in domains:
            if isinstance(entry, dict) and entry.get("domain"):
                domain = str(entry["domain"]).strip()
                if domain:
                    normalised.append({"domain": domain})
            elif isinstance(entry, str):
                domain = entry.strip()
                if domain:
                    normalised.append({"domain": domain})
    return normalised


def _normalise_mapping(value: Any) -> dict[str, Any]:
    data = _coerce_json_field(value, default={})
    return data if isinstance(data, dict) else {}


def _normalise_price_cache(value: Any) -> list[dict[str, Any]]:
    cache = _coerce_json_field(value, default=[])
    if isinstance(cache, dict):
        cache = [cache]
    if isinstance(cache, list):
        return [entry for entry in cache if isinstance(entry, dict)]
    return []


def _normalise_string_list(value: Any) -> list[str]:
    data = _coerce_json_field(value, default=[])
    if isinstance(data, list):
        result: list[str] = []
        for entry in data:
            if entry is None:
                continue
            if isinstance(entry, str):
                text_value = entry.strip()
            else:
                text_value = str(entry)
            if text_value:
                result.append(text_value)
        return result
    if isinstance(data, str):
        text_value = data.strip()
        return [text_value] if text_value else []
    return []


def _coerce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text_value = value.strip()
        return text_value or None
    text_value = str(value).strip()
    return text_value or None


def _extract_website_url(settings: Mapping[str, Any]) -> str | None:
    candidates = ("website_url", "website", "url", "test_url")
    for key in candidates:
        candidate = settings.get(key)
        text_value = _safe_str(candidate)
        if text_value:
            return text_value
    return None


def _resolve_owner(
    legacy_user_id: Any,
    *,
    user_map: Mapping[int, int],
    fallback_user_id: int | None,
    entity: str,
    identifier: Any,
) -> int:
    if legacy_user_id is not None:
        mapped = user_map.get(int(legacy_user_id))
        if mapped is not None:
            return mapped
    if fallback_user_id is not None:
        return fallback_user_id
    message = f"missing user mapping for {entity} (legacy_id={legacy_user_id})"
    raise RuntimeError(message)


def _build_user_map(
    src_conn: Connection, dst_conn: Connection, fallback_user_id: int | None
) -> dict[int, int]:
    src_rows = _fetch_rows(src_conn, "SELECT id, email FROM users", {})
    dst_rows = _fetch_rows(dst_conn, "SELECT id, email FROM users", {})

    dest_index: dict[str, int] = {}
    for row in dst_rows:
        email = row.get("email")
        if not email:
            continue
        dest_index[email.lower()] = int(row["id"])

    mapping: dict[int, int] = {}
    missing: list[int] = []
    for row in src_rows:
        email = row.get("email")
        legacy_id = int(row["id"])
        if not email:
            missing.append(legacy_id)
            continue
        mapped = dest_index.get(email.lower())
        if mapped is None:
            missing.append(legacy_id)
            continue
        mapping[legacy_id] = mapped

    if missing and fallback_user_id is None:
        log.warning("etl.catalog.user_map_missing", legacy_user_ids=missing[:25])

    info("etl.catalog.user_map", mapped=len(mapping))
    return mapping


def _migrate_stores(
    src_conn: Connection,
    dst_conn: Connection,
    batch_size: int,
    *,
    user_map: Mapping[int, int],
    fallback_user_id: int | None,
) -> dict[int, int]:
    info("etl.catalog.stores.start")
    src_count = src_conn.execute(text("SELECT COUNT(*) FROM stores")).scalar_one()
    mapping: dict[int, int] = {}
    offset = 0
    while offset < int(src_count):
        rows = _fetch_rows(
            src_conn,
            """
            SELECT id, name, slug, user_id, domains, scrape_strategy, settings, notes
            FROM stores
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """,
            {"limit": batch_size, "offset": offset},
        )
        for row in rows:
            owner_id = _resolve_owner(
                row.get("user_id"),
                user_map=user_map,
                fallback_user_id=fallback_user_id,
                entity="store",
                identifier=row["id"],
            )
            slug = row.get("slug") or _slugify(row["name"])
            settings = _normalise_mapping(row.get("settings"))
            locale_settings_raw = settings.get("locale_settings")
            locale_settings: dict[str, Any]
            locale_settings = (
                locale_settings_raw if isinstance(locale_settings_raw, dict) else {}
            )
            locale = _safe_str(locale_settings.get("locale"))
            currency = _safe_str(locale_settings.get("currency"))
            website_url = _extract_website_url(settings)
            domains = _normalise_domains(row.get("domains"))
            scrape_strategy = _normalise_mapping(row.get("scrape_strategy"))
            notes = _safe_str(row.get("notes"))

            rec = dst_conn.execute(
                text(
                    """
                    INSERT INTO stores (
                        user_id,
                        name,
                        slug,
                        website_url,
                        active,
                        domains,
                        scrape_strategy,
                        settings,
                        notes,
                        locale,
                        currency
                    ) VALUES (
                        :user_id,
                        :name,
                        :slug,
                        :website_url,
                        TRUE,
                        :domains,
                        :scrape_strategy,
                        :settings,
                        :notes,
                        :locale,
                        :currency
                    )
                    ON CONFLICT (user_id, slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        website_url = EXCLUDED.website_url,
                        active = EXCLUDED.active,
                        domains = EXCLUDED.domains,
                        scrape_strategy = EXCLUDED.scrape_strategy,
                        settings = EXCLUDED.settings,
                        notes = EXCLUDED.notes,
                        locale = EXCLUDED.locale,
                        currency = EXCLUDED.currency
                    RETURNING id
                    """
                ),
                {
                    "user_id": owner_id,
                    "name": row["name"],
                    "slug": slug,
                    "website_url": website_url,
                    "domains": json.dumps(domains),
                    "scrape_strategy": json.dumps(scrape_strategy),
                    "settings": json.dumps(settings),
                    "notes": notes,
                    "locale": locale,
                    "currency": currency,
                },
            ).scalar_one()
            mapping[int(row["id"])] = int(rec)
        offset += batch_size
    info("etl.catalog.stores.complete", migrated=len(mapping))
    return mapping


def _migrate_tags(
    src_conn: Connection,
    dst_conn: Connection,
    batch_size: int,
    *,
    user_map: Mapping[int, int],
    fallback_user_id: int | None,
) -> tuple[dict[int, int], dict[int, list[int]]]:
    info("etl.catalog.tags.start")
    src_count = src_conn.execute(text("SELECT COUNT(*) FROM tags")).scalar() or 0
    tag_map: dict[int, int] = {}
    offset = 0
    while offset < int(src_count):
        rows = _fetch_rows(
            src_conn,
            "SELECT id, name, user_id FROM tags ORDER BY id LIMIT :limit OFFSET :offset",
            {"limit": batch_size, "offset": offset},
        )
        for row in rows:
            owner_id = _resolve_owner(
                row.get("user_id"),
                user_map=user_map,
                fallback_user_id=fallback_user_id,
                entity="tag",
                identifier=row["id"],
            )
            slug = _slugify(row["name"]) + f"-{row['id']}"
            rec = dst_conn.execute(
                text(
                    """
                    INSERT INTO tags (user_id, name, slug)
                    VALUES (:user_id, :name, :slug)
                    ON CONFLICT (user_id, slug) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """
                ),
                {"user_id": owner_id, "name": row["name"], "slug": slug},
            ).scalar_one()
            tag_map[int(row["id"])] = int(rec)
        offset += batch_size

    tag_links: dict[int, list[int]] = {}
    rows = _fetch_rows(
        src_conn,
        "SELECT tag_id, taggable_id, taggable_type FROM taggables",
        {},
    )
    for row in rows:
        if "Product" in str(row["taggable_type"]):
            pid = int(row["taggable_id"])
            tag_id = int(row["tag_id"]) if row["tag_id"] is not None else None
            if tag_id and tag_id in tag_map:
                tag_links.setdefault(pid, []).append(tag_map[tag_id])

    info("etl.catalog.tags.complete", migrated=len(tag_map))
    return tag_map, tag_links


def _migrate_products(
    src_conn: Connection,
    dst_conn: Connection,
    tag_links: dict[int, list[int]],
    batch_size: int,
    *,
    user_map: Mapping[int, int],
    fallback_user_id: int | None,
) -> dict[int, int]:
    info("etl.catalog.products.start")
    count = src_conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
    mapping: dict[int, int] = {}
    offset = 0
    while offset < int(count):
        rows = _fetch_rows(
            src_conn,
            """
            SELECT
                id,
                title,
                status,
                user_id,
                favourite,
                only_official,
                notify_price,
                notify_percent,
                price_cache,
                ignored_urls,
                current_price,
                image
            FROM products
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """,
            {"limit": batch_size, "offset": offset},
        )
        for row in rows:
            owner_id = _resolve_owner(
                row.get("user_id"),
                user_map=user_map,
                fallback_user_id=fallback_user_id,
                entity="product",
                identifier=row["id"],
            )
            base_slug = _slugify(row["title"]) or "product"
            slug = f"{base_slug}-{row['id']}"
            status_code = str(row.get("status") or "p").lower()
            status = "archived" if status_code.startswith("a") else "published"
            is_active = status != "archived"
            favourite = bool(int(row.get("favourite", 1)))
            only_official = bool(int(row.get("only_official", 0)))
            notify_price = _coerce_numeric(row.get("notify_price"))
            notify_percent = _coerce_numeric(row.get("notify_percent"))
            current_price = _coerce_numeric(row.get("current_price"))
            price_cache = _normalise_price_cache(row.get("price_cache"))
            ignored_urls = _normalise_string_list(row.get("ignored_urls"))
            image_url = _safe_str(row.get("image"))
            rec = dst_conn.execute(
                text(
                    """
                    INSERT INTO products (
                        user_id,
                        name,
                        slug,
                        description,
                        is_active,
                        status,
                        favourite,
                        only_official,
                        notify_price,
                        notify_percent,
                        current_price,
                        price_cache,
                        ignored_urls,
                        image_url
                    ) VALUES (
                        :user_id,
                        :name,
                        :slug,
                        NULL,
                        :is_active,
                        :status,
                        :favourite,
                        :only_official,
                        :notify_price,
                        :notify_percent,
                        :current_price,
                        :price_cache,
                        :ignored_urls,
                        :image_url
                    )
                    ON CONFLICT (user_id, slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active,
                        status = EXCLUDED.status,
                        favourite = EXCLUDED.favourite,
                        only_official = EXCLUDED.only_official,
                        notify_price = EXCLUDED.notify_price,
                        notify_percent = EXCLUDED.notify_percent,
                        current_price = EXCLUDED.current_price,
                        price_cache = EXCLUDED.price_cache,
                        ignored_urls = EXCLUDED.ignored_urls,
                        image_url = EXCLUDED.image_url
                    RETURNING id
                    """
                ),
                {
                    "user_id": owner_id,
                    "name": row["title"],
                    "slug": slug,
                    "is_active": is_active,
                    "status": status,
                    "favourite": favourite,
                    "only_official": only_official,
                    "notify_price": notify_price,
                    "notify_percent": notify_percent,
                    "current_price": current_price,
                    "price_cache": json.dumps(price_cache),
                    "ignored_urls": json.dumps(ignored_urls),
                    "image_url": image_url,
                },
            ).scalar_one()
            new_id = int(rec)
            mapping[row["id"]] = new_id
            # Upsert tag links
            for tag_id in tag_links.get(int(row["id"]), []):
                dst_conn.execute(
                    text(
                        """
                        INSERT INTO product_tag_link (product_id, tag_id)
                        VALUES (:pid, :tid)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"pid": new_id, "tid": tag_id},
                )
        offset += batch_size
    info("etl.catalog.products.complete", migrated=len(mapping))
    return mapping


def _migrate_urls(
    src_conn: Connection,
    dst_conn: Connection,
    product_map: dict[int, int],
    store_map: dict[int, int],
    batch_size: int,
) -> dict[int, int]:
    info("etl.catalog.urls.start")
    count = src_conn.execute(text("SELECT COUNT(*) FROM urls")).scalar_one()
    mapping: dict[int, int] = {}
    offset = 0
    while offset < int(count):
        rows = _fetch_rows(
            src_conn,
            """
            SELECT id, url, product_id, store_id
            FROM urls ORDER BY id LIMIT :limit OFFSET :offset
            """,
            {"limit": batch_size, "offset": offset},
        )
        for row in rows:
            pid_old = int(row["product_id"]) if row["product_id"] else None
            sid_old = int(row["store_id"]) if row["store_id"] else None
            pid = product_map.get(pid_old or -1)
            sid = store_map.get(sid_old or -1)
            if pid is None or sid is None:
                continue
            rec = dst_conn.execute(
                text(
                    """
                    INSERT INTO product_urls (product_id, store_id, created_by_id, url, is_primary, active)
                    VALUES (:pid, :sid, NULL, :url, FALSE, TRUE)
                    RETURNING id
                    """
                ),
                {"pid": pid, "sid": sid, "url": row["url"]},
            ).scalar_one()
            mapping[row["id"]] = int(rec)
        offset += batch_size
    info("etl.catalog.urls.complete", migrated=len(mapping))
    return mapping


def _migrate_prices(
    src_conn: Connection,
    dst_conn: Connection,
    product_map: dict[int, int],
    url_map: dict[int, int],
    batch_size: int,
    default_currency: str,
    store_currency: dict[str, str] | None = None,
) -> int:
    info("etl.catalog.prices.start")
    count_val = src_conn.execute(text("SELECT COUNT(*) FROM prices")).scalar()
    count = int(count_val or 0)
    migrated = 0
    offset = 0
    while offset < count:
        rows = _fetch_rows(
            src_conn,
            """
            SELECT p.id, p.price, p.url_id, p.created_at, p.notified, u.product_id, s.slug AS store_slug
            FROM prices p
            JOIN urls u ON u.id = p.url_id
            JOIN stores s ON s.id = u.store_id
            ORDER BY p.id
            LIMIT :limit OFFSET :offset
            """,
            {"limit": batch_size, "offset": offset},
        )
        for row in rows:
            old_pid = int(row["product_id"]) if row["product_id"] else None
            old_url_id = int(row["url_id"]) if row["url_id"] else None
            pid = product_map.get(old_pid or -1)
            urlid = url_map.get(old_url_id or -1)
            if pid is None or urlid is None:
                continue
            currency = default_currency
            if store_currency and row.get("store_slug"):
                currency = store_currency.get(
                    str(row["store_slug"]).lower(), default_currency
                )
            price_value = _coerce_numeric(row.get("price"))
            if price_value is None:
                continue
            dst_conn.execute(
                text(
                    """
                    INSERT INTO price_history (
                        product_id,
                        product_url_id,
                        price,
                        currency,
                        recorded_at,
                        notified
                    ) VALUES (
                        :pid,
                        :purl,
                        :price,
                        :currency,
                        :recorded_at,
                        :notified
                    )
                    """
                ),
                {
                    "pid": pid,
                    "purl": urlid,
                    "price": price_value,
                    "currency": currency,
                    "recorded_at": row["created_at"],
                    "notified": bool(row.get("notified", False)),
                },
            )
            migrated += 1
        offset += batch_size
    info("etl.catalog.prices.complete", migrated=migrated)
    return migrated


@app.command()
def main(
    legacy_dsn: Annotated[
        str,
        typer.Option(
            "postgresql+psycopg://legacy:legacy@127.0.0.1:5433/costcourter_legacy",
            help="Source legacy database DSN",
        ),
    ],
    postgres_dsn: Annotated[
        str,
        typer.Option(
            "postgresql+psycopg://costcourter:change-me@127.0.0.1:5432/costcourter",
            help="Target Postgres DSN",
        ),
    ],
    batch_size: Annotated[int, typer.Option(min=100, max=50000)] = 5000,
    default_currency: Annotated[
        str, typer.Option(help="Fallback currency code (3-char)")
    ] = "USD",
    store_currency_file: Annotated[
        str | None, typer.Option(help="JSON mapping: { 'store-slug': 'EUR' }")
    ] = None,
    fallback_owner_email: Annotated[
        str | None,
        typer.Option(
            help="Assign legacy rows without a user_id to this FastAPI user (email)"
        ),
    ] = None,
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Migrate catalog entities (stores, products, tags, URLs, price history) in batches."""

    info("etl.load_catalog.start", batch_size=batch_size)
    src = build_engine(legacy_dsn, echo=echo_sql)
    dst = build_engine(postgres_dsn, echo=echo_sql)

    store_currency: dict[str, str] | None = None
    if store_currency_file:
        try:
            with open(store_currency_file, encoding="utf-8") as fh:
                mapping = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning(
                "etl.catalog.currency_mapping_failed",
                path=store_currency_file,
                error=str(exc),
            )
            store_currency = None
        else:
            store_currency = {
                str(k).lower(): str(v).upper() for k, v in mapping.items()
            }

    with engine_scope(src) as src_eng, engine_scope(dst) as dst_eng:
        with src_eng.begin() as sconn, dst_eng.begin() as dconn:
            fallback_user_id: int | None = None
            if fallback_owner_email:
                row = dconn.execute(
                    text("SELECT id FROM users WHERE lower(email) = :email LIMIT 1"),
                    {"email": fallback_owner_email.lower()},
                ).first()
                if row is None:
                    raise typer.BadParameter(
                        "fallback-owner-email must match an existing Postgres user",
                        param_hint="fallback-owner-email",
                    )
                fallback_user_id = int(row[0])

            user_map = _build_user_map(sconn, dconn, fallback_user_id)

            store_map = _migrate_stores(
                sconn,
                dconn,
                batch_size,
                user_map=user_map,
                fallback_user_id=fallback_user_id,
            )
            tag_map, tag_links = _migrate_tags(
                sconn,
                dconn,
                batch_size,
                user_map=user_map,
                fallback_user_id=fallback_user_id,
            )
            product_map = _migrate_products(
                sconn,
                dconn,
                tag_links,
                batch_size,
                user_map=user_map,
                fallback_user_id=fallback_user_id,
            )
            url_map = _migrate_urls(
                sconn,
                dconn,
                product_map=product_map,
                store_map=store_map,
                batch_size=batch_size,
            )
            _migrate_prices(
                sconn,
                dconn,
                product_map,
                url_map,
                batch_size,
                default_currency,
                store_currency,
            )

    info("etl.load_catalog.complete")


if __name__ == "__main__":
    typer.run(main)
