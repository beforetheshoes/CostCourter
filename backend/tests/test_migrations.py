from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
import typer
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from typer import Exit

from scripts.migrations import (
    load_catalog,
    load_notifications,
    load_reference_data,
    load_users,
    validate_counts,
    validate_fks,
)


def _sqlite_dsn(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


@contextmanager
def _memory_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        yield engine
    finally:
        engine.dispose()


@contextmanager
def _sqlite_engine(path: Path) -> Iterator[Engine]:
    engine = create_engine(_sqlite_dsn(path))
    try:
        yield engine
    finally:
        engine.dispose()


def _create_tables(conn: Connection, statements: list[str]) -> None:
    for stmt in statements:
        conn.execute(text(stmt))


@pytest.fixture
def tmp_db_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_load_users_main_migrates_data(tmp_db_dir: Path) -> None:
    src_path = tmp_db_dir / "users_src.db"
    dst_path = tmp_db_dir / "users_dst.db"

    with _sqlite_engine(src_path) as src_engine, _sqlite_engine(dst_path) as dst_engine:
        with src_engine.begin() as conn:
            _create_tables(
                conn,
                [
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)",
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com')"
                )
            )

        with dst_engine.begin() as conn:
            _create_tables(
                conn,
                [
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE,
                        full_name TEXT,
                        is_active BOOLEAN,
                        is_superuser BOOLEAN
                    )
                    """
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO users (email, full_name, is_active, is_superuser) VALUES ('bob@example.com', 'Placeholder', 1, 0)"
                )
            )

        load_users.main(
            legacy_dsn=_sqlite_dsn(src_path),
            postgres_dsn=_sqlite_dsn(dst_path),
            batch_size=1,
            echo_sql=False,
        )

        with dst_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT email, full_name, is_active, is_superuser FROM users ORDER BY email"
                )
            ).fetchall()

        assert rows == [
            ("alice@example.com", "Alice", 1, 0),
            ("bob@example.com", "Bob", 1, 0),
        ]


def test_load_notifications_main_writes_app_settings(tmp_db_dir: Path) -> None:
    src_path = tmp_db_dir / "notifications_src.db"
    dst_path = tmp_db_dir / "notifications_dst.db"

    with _sqlite_engine(src_path) as src_engine, _sqlite_engine(dst_path) as dst_engine:
        with src_engine.begin() as conn:
            _create_tables(
                conn,
                [
                    "CREATE TABLE settings (id INTEGER PRIMARY KEY, `group` TEXT, name TEXT, payload TEXT)",
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO settings (`group`, name, payload) VALUES ('notify', 'email', :payload)"
                ),
                {"payload": json.dumps({"enabled": True})},
            )
            conn.execute(
                text(
                    "INSERT INTO settings (`group`, name, payload) VALUES ('notify', 'pushover', 'token')"
                )
            )

        with dst_engine.begin() as conn:
            _create_tables(
                conn,
                [
                    "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT, description TEXT)",
                ],
            )

        load_notifications.main(
            legacy_dsn=_sqlite_dsn(src_path),
            postgres_dsn=_sqlite_dsn(dst_path),
            echo_sql=False,
        )

        with dst_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT key, value FROM app_settings ORDER BY key")
            ).fetchall()

        assert rows == [
            ("notify.email", json.dumps({"enabled": True})),
            ("notify.pushover", "token"),
        ]


def _setup_catalog_source(engine: Engine) -> None:
    with engine.begin() as conn:
        _create_tables(
            conn,
            [
                "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)",
                "CREATE TABLE stores (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, user_id INTEGER, domains TEXT, scrape_strategy TEXT, settings TEXT, notes TEXT)",
                "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT, user_id INTEGER)",
                "CREATE TABLE taggables (tag_id INTEGER, taggable_id INTEGER, taggable_type TEXT)",
                "CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT, status TEXT, user_id INTEGER, favourite INTEGER, only_official INTEGER, notify_price REAL, notify_percent REAL, price_cache TEXT, ignored_urls TEXT, current_price REAL, image TEXT)",
                "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, product_id INTEGER, store_id INTEGER)",
                "CREATE TABLE prices (id INTEGER PRIMARY KEY, price REAL, url_id INTEGER, store_id INTEGER, notified INTEGER, created_at TEXT)",
            ],
        )
        conn.execute(
            text(
                "INSERT INTO users (id, name, email) VALUES (1, 'Alice Legacy', 'alice@example.com')"
            )
        )

        domains = json.dumps([{"domain": "store-a.example"}])
        scrape_strategy = json.dumps(
            {
                "title": {"type": "css", "value": "h1"},
                "price": {"type": "css", "value": ".price"},
            }
        )
        settings = json.dumps(
            {
                "locale_settings": {"locale": "en_GB", "currency": "GBP"},
                "website_url": "https://store.example.com",
            }
        )

        conn.execute(
            text(
                """
                INSERT INTO stores (id, name, slug, user_id, domains, scrape_strategy, settings, notes)
                VALUES (1, 'Store A', 'store-a', 1, :domains, :strategy, :settings, 'Primary store')
                """
            ),
            {"domains": domains, "strategy": scrape_strategy, "settings": settings},
        )

        conn.execute(
            text(
                """
                INSERT INTO stores (id, name, slug, user_id, domains, scrape_strategy, settings, notes)
                VALUES (2, 'Store B', NULL, 1, '[]', NULL, '{}', 'Secondary store')
                """
            )
        )

        conn.execute(
            text("INSERT INTO tags (id, name, user_id) VALUES (10, 'Electronics', 1)")
        )
        conn.execute(
            text(
                r"INSERT INTO taggables (tag_id, taggable_id, taggable_type) VALUES (10, 100, 'App\\Models\\Product')"
            )
        )

        price_cache = json.dumps([{"store_id": 1, "price": 19.99}])
        ignored_urls = json.dumps(["https://ignore.example.com"])

        conn.execute(
            text(
                """
                INSERT INTO products (
                    id, title, status, user_id, favourite, only_official,
                    notify_price, notify_percent, price_cache, ignored_urls,
                    current_price, image
                ) VALUES (
                    100, 'Widget Deluxe', 'P', 1, 1, 0,
                    99.99, 15.5, :cache, :ignored,
                    19.99, 'https://images.example.com/widget.jpg'
                )
                """
            ),
            {"cache": price_cache, "ignored": ignored_urls},
        )

        conn.execute(
            text(
                "INSERT INTO urls (id, url, product_id, store_id) VALUES (200, 'https://example.com/widget', 100, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO urls (id, url, product_id, store_id) VALUES (201, 'https://example.com/unmapped', NULL, NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO urls (id, url, product_id, store_id) VALUES (202, 'https://example.com/orphan', 999, 1)"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (id, price, url_id, store_id, notified, created_at)
                VALUES (300, 19.99, 200, 1, 1, :created_at)
                """
            ),
            {"created_at": datetime(2024, 1, 1).isoformat()},
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (id, price, url_id, store_id, notified, created_at)
                VALUES (301, 'invalid', 200, 1, 0, :created_at)
                """
            ),
            {"created_at": datetime(2024, 1, 2).isoformat()},
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (id, price, url_id, store_id, notified, created_at)
                VALUES (302, 5.0, 202, 1, 0, :created_at)
                """
            ),
            {"created_at": datetime(2024, 1, 3).isoformat()},
        )


def _setup_catalog_destination(engine: Engine) -> None:
    with engine.begin() as conn:
        _create_tables(
            conn,
            [
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, full_name TEXT, is_active BOOLEAN, is_superuser BOOLEAN)",
                "CREATE TABLE stores (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, slug TEXT, website_url TEXT, active BOOLEAN, domains TEXT, scrape_strategy TEXT, settings TEXT, notes TEXT, locale TEXT, currency TEXT, UNIQUE(user_id, slug))",
                "CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, slug TEXT, UNIQUE(user_id, slug))",
                "CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, slug TEXT, description TEXT, is_active BOOLEAN, status TEXT, favourite BOOLEAN, only_official BOOLEAN, notify_price REAL, notify_percent REAL, current_price REAL, price_cache TEXT, ignored_urls TEXT, image_url TEXT, UNIQUE(user_id, slug))",
                "CREATE TABLE product_tag_link (product_id INTEGER, tag_id INTEGER, PRIMARY KEY (product_id, tag_id))",
                "CREATE TABLE product_urls (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, store_id INTEGER, created_by_id INTEGER, url TEXT, is_primary BOOLEAN, active BOOLEAN)",
                "CREATE TABLE price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, product_url_id INTEGER, price REAL, currency TEXT, recorded_at TEXT, notified BOOLEAN)",
            ],
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, full_name, is_active, is_superuser) VALUES (1, 'alice@example.com', 'Alice Dest', 1, 0)"
            )
        )


def test_load_catalog_helpers_migrate_entities() -> None:
    with _memory_engine() as src_engine, _memory_engine() as dst_engine:
        _setup_catalog_source(src_engine)
        _setup_catalog_destination(dst_engine)

        with src_engine.begin() as sconn, dst_engine.begin() as dconn:
            user_map = load_catalog._build_user_map(sconn, dconn, fallback_user_id=None)
            store_map = load_catalog._migrate_stores(
                sconn,
                dconn,
                batch_size=10,
                user_map=user_map,
                fallback_user_id=None,
            )
            tag_map, tag_links = load_catalog._migrate_tags(
                sconn,
                dconn,
                batch_size=10,
                user_map=user_map,
                fallback_user_id=None,
            )
            product_map = load_catalog._migrate_products(
                sconn,
                dconn,
                tag_links=tag_links,
                batch_size=10,
                user_map=user_map,
                fallback_user_id=None,
            )
            url_map = load_catalog._migrate_urls(
                sconn,
                dconn,
                product_map=product_map,
                store_map=store_map,
                batch_size=10,
            )
            migrated = load_catalog._migrate_prices(
                sconn,
                dconn,
                product_map=product_map,
                url_map=url_map,
                batch_size=10,
                default_currency="USD",
                store_currency={"store-a": "EUR"},
            )

        assert len(store_map) == 2
        assert len(tag_map) == 1
        assert len(product_map) == 1
        assert len(url_map) == 1
        assert migrated == 1

        with dst_engine.connect() as conn:
            store_rows = (
                conn.execute(
                    text(
                        """
                    SELECT user_id, slug, website_url, domains, scrape_strategy, settings, notes, locale, currency
                    FROM stores ORDER BY slug
                    """
                    )
                )
                .mappings()
                .all()
            )
            product_rows = (
                conn.execute(
                    text(
                        """
                    SELECT user_id, slug, status, is_active, favourite, only_official, notify_price, notify_percent,
                           current_price, price_cache, ignored_urls, image_url
                    FROM products
                    """
                    )
                )
                .mappings()
                .all()
            )
            tag_rows = (
                conn.execute(text("SELECT user_id, slug FROM tags")).mappings().all()
            )
            link_rows = conn.execute(
                text("SELECT product_id, tag_id FROM product_tag_link")
            ).fetchall()
            price_rows = (
                conn.execute(
                    text("SELECT price, currency, notified FROM price_history")
                )
                .mappings()
                .all()
            )

        assert [row["slug"] for row in store_rows] == ["store-a", "store-b"]
        assert store_rows[0]["user_id"] == 1
        assert store_rows[0]["website_url"] == "https://store.example.com"
        assert json.loads(store_rows[0]["domains"]) == [{"domain": "store-a.example"}]
        assert json.loads(store_rows[0]["scrape_strategy"]) == {
            "title": {"type": "css", "value": "h1"},
            "price": {"type": "css", "value": ".price"},
        }
        assert json.loads(store_rows[0]["settings"]) == {
            "locale_settings": {"locale": "en_GB", "currency": "GBP"},
            "website_url": "https://store.example.com",
        }
        assert store_rows[0]["notes"] == "Primary store"
        assert store_rows[0]["locale"] == "en_GB"
        assert store_rows[0]["currency"] == "GBP"
        assert store_rows[1]["website_url"] is None
        assert json.loads(store_rows[1]["domains"]) == []

        assert len(product_rows) == 1
        product = product_rows[0]
        assert product["user_id"] == 1
        assert product["slug"] == "widget-deluxe-100"
        assert product["status"] == "published"
        assert product["is_active"] == 1
        assert product["favourite"] == 1
        assert product["only_official"] == 0
        assert product["notify_price"] == 99.99
        assert product["notify_percent"] == 15.5
        assert product["current_price"] == 19.99
        assert json.loads(product["price_cache"]) == [{"store_id": 1, "price": 19.99}]
        assert json.loads(product["ignored_urls"]) == ["https://ignore.example.com"]
        assert product["image_url"] == "https://images.example.com/widget.jpg"

        assert link_rows

        assert len(tag_rows) == 1
        tag = tag_rows[0]
        assert tag["user_id"] == 1
        assert tag["slug"] == "electronics-10"

        assert len(price_rows) == 1
        price_row = price_rows[0]
        assert price_row["price"] == 19.99
    assert price_row["currency"] == "EUR"
    assert bool(price_row["notified"]) is True


def test_load_catalog_helper_normalisation(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")

    assert load_catalog._coerce_json_field(b'{"foo": 1}', default={}) == {"foo": 1}
    assert load_catalog._coerce_json_field("   ", default={"sentinel": True}) == {
        "sentinel": True
    }
    load_catalog._coerce_json_field(
        "{", default={}
    )  # triggers warning but returns default
    assert load_catalog._coerce_json_field({"bar": 2}, default={}) == {"bar": 2}
    assert load_catalog._coerce_json_field(123, default={"fallback": True}) == {
        "fallback": True
    }

    assert load_catalog._normalise_domains('[{"domain": "example.com"}]') == [
        {"domain": "example.com"}
    ]
    assert load_catalog._normalise_domains('["store.example.com"]') == [
        {"domain": "store.example.com"}
    ]
    assert load_catalog._normalise_domains({"domain": "dict.example"}) == [
        {"domain": "dict.example"}
    ]

    assert load_catalog._normalise_mapping('{"alpha": "beta"}') == {"alpha": "beta"}
    assert load_catalog._normalise_price_cache('{"store": 1}') == [{"store": 1}]
    assert load_catalog._normalise_price_cache('"invalid"') == []
    assert load_catalog._normalise_string_list('[" https://foo "]') == ["https://foo"]
    assert load_catalog._normalise_string_list("[null, 42]") == ["42"]
    assert load_catalog._normalise_string_list('"solo"') == ["solo"]

    assert load_catalog._coerce_numeric("12.5") == pytest.approx(12.5)
    assert load_catalog._coerce_numeric("not-a-number") is None
    assert load_catalog._coerce_numeric(None) is None

    assert load_catalog._safe_str(" value ") == "value"
    assert load_catalog._safe_str("   ") is None
    assert load_catalog._safe_str(123) == "123"

    settings = {"website_url": "https://example.com"}
    assert load_catalog._extract_website_url(settings) == "https://example.com"


def test_load_catalog_resolve_owner_and_user_map(tmp_path: Path) -> None:
    with _memory_engine() as src_engine, _memory_engine() as dst_engine:
        with src_engine.begin() as sconn, dst_engine.begin() as dconn:
            _create_tables(
                sconn,
                ["CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)"],
            )
            _create_tables(
                dconn,
                ["CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)"],
            )
            sconn.execute(
                text("INSERT INTO users (id, email) VALUES (1, 'mapped@example.com')")
            )
            sconn.execute(text("INSERT INTO users (id, email) VALUES (2, NULL)"))
            sconn.execute(
                text("INSERT INTO users (id, email) VALUES (3, 'unmapped@example.com')")
            )
            dconn.execute(
                text("INSERT INTO users (id, email) VALUES (10, 'mapped@example.com')")
            )
            dconn.execute(text("INSERT INTO users (id, email) VALUES (11, NULL)"))

            mapping = load_catalog._build_user_map(sconn, dconn, fallback_user_id=None)
            assert mapping == {1: 10}

            mapping_with_fallback = load_catalog._build_user_map(
                sconn, dconn, fallback_user_id=99
            )
            assert mapping_with_fallback == mapping

            assert (
                load_catalog._resolve_owner(
                    1,
                    user_map=mapping,
                    fallback_user_id=None,
                    entity="store",
                    identifier=1,
                )
                == 10
            )
            assert (
                load_catalog._resolve_owner(
                    None,
                    user_map=mapping,
                    fallback_user_id=42,
                    entity="store",
                    identifier=2,
                )
                == 42
            )
            with pytest.raises(RuntimeError):
                load_catalog._resolve_owner(
                    None,
                    user_map=mapping,
                    fallback_user_id=None,
                    entity="store",
                    identifier=3,
                )


def test_load_catalog_main_end_to_end(tmp_path: Path) -> None:
    src_path = tmp_path / "src.db"
    dst_path = tmp_path / "dst.db"

    src_engine = create_engine(_sqlite_dsn(src_path))
    dst_engine = create_engine(_sqlite_dsn(dst_path))

    _setup_catalog_source(src_engine)
    _setup_catalog_destination(dst_engine)

    currency_mapping = tmp_path / "currency.json"
    currency_mapping.write_text(json.dumps({"store-a": "EUR"}), encoding="utf-8")

    load_catalog.main(
        legacy_dsn=_sqlite_dsn(src_path),
        postgres_dsn=_sqlite_dsn(dst_path),
        batch_size=50,
        default_currency="USD",
        store_currency_file=str(currency_mapping),
        fallback_owner_email="alice@example.com",
        echo_sql=False,
    )

    invalid_mapping = tmp_path / "invalid.json"
    invalid_mapping.write_text("{not-json", encoding="utf-8")

    load_catalog.main(
        legacy_dsn=_sqlite_dsn(src_path),
        postgres_dsn=_sqlite_dsn(dst_path),
        batch_size=50,
        default_currency="USD",
        store_currency_file=str(invalid_mapping),
        fallback_owner_email="alice@example.com",
        echo_sql=False,
    )

    with dst_engine.connect() as conn:
        price_count = conn.execute(text("SELECT COUNT(*) FROM price_history"))
        assert int(price_count.scalar_one()) >= 1

    src_engine.dispose()
    dst_engine.dispose()


def test_load_catalog_main_invalid_fallback(tmp_path: Path) -> None:
    src_path = tmp_path / "invalid_src.db"
    dst_path = tmp_path / "invalid_dst.db"

    src_engine = create_engine(_sqlite_dsn(src_path))
    dst_engine = create_engine(_sqlite_dsn(dst_path))

    _setup_catalog_source(src_engine)
    _setup_catalog_destination(dst_engine)

    with pytest.raises(typer.BadParameter):
        load_catalog.main(
            legacy_dsn=_sqlite_dsn(src_path),
            postgres_dsn=_sqlite_dsn(dst_path),
            batch_size=10,
            default_currency="USD",
            store_currency_file=None,
            fallback_owner_email="missing@example.com",
            echo_sql=False,
        )

    src_engine.dispose()
    dst_engine.dispose()


def test_load_reference_data_main_populates_tables(tmp_path: Path) -> None:
    dst_path = tmp_path / "reference.db"
    engine = create_engine(_sqlite_dsn(dst_path))
    SQLModel.metadata.create_all(engine)

    load_reference_data.main(
        postgres_dsn=_sqlite_dsn(dst_path),
        echo_sql=False,
    )

    with engine.connect() as conn:
        roles = conn.execute(text("SELECT COUNT(*) FROM roles")).scalar_one()
        settings = conn.execute(text("SELECT COUNT(*) FROM app_settings")).scalar_one()

    assert roles > 0
    assert settings > 0

    engine.dispose()


def test_validate_counts_main(tmp_db_dir: Path) -> None:
    src_path = tmp_db_dir / "counts_src.db"
    dst_path = tmp_db_dir / "counts_dst.db"

    table_defs = [
        "CREATE TABLE users (id INTEGER PRIMARY KEY)",
        "CREATE TABLE user_identities (id INTEGER PRIMARY KEY)",
        "CREATE TABLE stores (id INTEGER PRIMARY KEY)",
        "CREATE TABLE products (id INTEGER PRIMARY KEY)",
        "CREATE TABLE tags (id INTEGER PRIMARY KEY)",
        "CREATE TABLE product_urls (id INTEGER PRIMARY KEY)",
        "CREATE TABLE price_history (id INTEGER PRIMARY KEY)",
    ]

    with _sqlite_engine(src_path) as src_engine, _sqlite_engine(dst_path) as dst_engine:
        with src_engine.begin() as conn:
            _create_tables(conn, table_defs)
            conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        with dst_engine.begin() as conn:
            _create_tables(conn, table_defs)
            conn.execute(text("INSERT INTO users (id) VALUES (1)"))

        validate_counts.main(
            legacy_dsn=_sqlite_dsn(src_path),
            postgres_dsn=_sqlite_dsn(dst_path),
            echo_sql=False,
        )

        with dst_engine.begin() as conn:
            conn.execute(text("DELETE FROM users"))

        with pytest.raises(Exit):
            validate_counts.main(
                legacy_dsn=_sqlite_dsn(src_path),
                postgres_dsn=_sqlite_dsn(dst_path),
                echo_sql=False,
            )


def test_validate_fks_main(tmp_db_dir: Path) -> None:
    dst_path = tmp_db_dir / "fks.db"

    with _sqlite_engine(dst_path) as engine:
        with engine.begin() as conn:
            _create_tables(
                conn,
                [
                    "CREATE TABLE products (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE stores (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE product_urls (id INTEGER PRIMARY KEY, product_id INTEGER, store_id INTEGER)",
                    "CREATE TABLE price_history (id INTEGER PRIMARY KEY, product_id INTEGER)",
                    "INSERT INTO products (id) VALUES (1)",
                    "INSERT INTO stores (id) VALUES (1)",
                    "INSERT INTO product_urls (id, product_id, store_id) VALUES (1, 1, 1)",
                    "INSERT INTO price_history (id, product_id) VALUES (1, 1)",
                ],
            )

        validate_fks.main(postgres_dsn=_sqlite_dsn(dst_path), echo_sql=False)

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products"))

        with pytest.raises(Exit):
            validate_fks.main(postgres_dsn=_sqlite_dsn(dst_path), echo_sql=False)
