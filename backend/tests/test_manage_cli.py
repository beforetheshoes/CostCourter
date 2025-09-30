from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
import typer
from sqlalchemy import func, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from typer.testing import CliRunner

import app.core.database as db
from app.core.config import settings
from app.models import (
    NotificationSetting,
    PriceHistory,
    Product,
    ProductURL,
    SearchCache,
    Store,
    Tag,
    User,
)
from app.services.notification_preferences import UnknownNotificationChannelError
from app.services.price_cache import rebuild_product_price_cache
from app.services.price_fetcher import (
    PriceFetcherService,
    PriceFetchResult,
    PriceFetchSummary,
    set_price_fetcher_service_factory,
)
from scripts import manage


@dataclass
class _StubPriceFetcher:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def update_product_prices(
        self,
        session: Session,
        product_id: int,
        *,
        logging: bool = False,
        owner_id: int | None = None,
    ) -> PriceFetchSummary:
        summary = PriceFetchSummary(
            total_urls=1,
            successful_urls=1,
            failed_urls=0,
            results=[
                PriceFetchResult(
                    product_url_id=321,
                    success=True,
                    price=19.99,
                    currency="USD",
                    reason=None,
                )
            ],
        )
        self.calls.append(
            {
                "mode": "product",
                "product_id": product_id,
                "logging": logging,
                "owner_id": owner_id,
            }
        )
        return summary

    def update_all_products(
        self,
        session: Session,
        *,
        logging: bool = False,
        owner_id: int | None = None,
    ) -> PriceFetchSummary:
        summary = PriceFetchSummary(
            total_urls=2,
            successful_urls=1,
            failed_urls=1,
            results=[
                PriceFetchResult(
                    product_url_id=654,
                    success=False,
                    price=None,
                    currency=None,
                    reason="http_error",
                )
            ],
        )
        self.calls.append(
            {
                "mode": "all",
                "owner_id": owner_id,
                "logging": logging,
            }
        )
        return summary


@pytest.fixture(autouse=True)
def override_engine() -> Iterator[None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    original_manage_engine = manage.engine
    original_db_engine = db.engine
    manage.engine = test_engine
    db.engine = test_engine
    try:
        yield
    finally:
        manage.engine = original_manage_engine
        db.engine = original_db_engine
        test_engine.dispose()


@pytest.fixture
def stub_price_fetcher() -> Iterator[_StubPriceFetcher]:
    stub = _StubPriceFetcher()

    def factory() -> PriceFetcherService:
        return cast(PriceFetcherService, stub)

    set_price_fetcher_service_factory(factory)
    try:
        yield stub
    finally:
        set_price_fetcher_service_factory(None)


def test_refresh_prices_for_product(stub_price_fetcher: _StubPriceFetcher) -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["refresh-prices", "--product-id", "42", "--log"],
    )

    assert result.exit_code == 0, result.stdout
    product_call = next(
        call for call in stub_price_fetcher.calls if call["mode"] == "product"
    )
    assert product_call["product_id"] == 42
    assert product_call["logging"] is True
    assert "URLs processed: 1" in result.stdout
    assert "Successful URLs: 1" in result.stdout
    assert "Failed URLs: 0" in result.stdout


def test_refresh_prices_for_all_products(stub_price_fetcher: _StubPriceFetcher) -> None:
    runner = CliRunner()
    result = runner.invoke(manage.app, ["refresh-prices", "--all"])

    assert result.exit_code == 0, result.stdout
    all_call = next(call for call in stub_price_fetcher.calls if call["mode"] == "all")
    assert all_call["owner_id"] is None
    assert all_call["logging"] is False
    assert "URLs processed: 2" in result.stdout
    assert "Failed URLs: 1" in result.stdout
    assert "http_error" in result.stdout


def test_refresh_prices_for_owner_email_scopes_to_user(
    stub_price_fetcher: _StubPriceFetcher,
) -> None:
    runner = CliRunner()
    with Session(manage.engine) as session:
        owner = User(email="scoped@example.com")
        session.add(owner)
        session.commit()
        session.refresh(owner)

    result = runner.invoke(
        manage.app,
        ["refresh-prices", "--all", "--owner-email", "scoped@example.com"],
    )

    assert result.exit_code == 0, result.stdout
    all_call = next(call for call in stub_price_fetcher.calls if call["mode"] == "all")
    assert all_call["owner_id"] == owner.id


def test_refresh_prices_owner_email_requires_all(
    stub_price_fetcher: _StubPriceFetcher,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["refresh-prices", "--owner-email", "scoped@example.com"],
    )

    assert result.exit_code != 0
    assert "requires --all" in result.output
    assert not stub_price_fetcher.calls


def test_refresh_prices_owner_email_missing_user(
    stub_price_fetcher: _StubPriceFetcher,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["refresh-prices", "--all", "--owner-email", "missing@example.com"],
    )

    assert result.exit_code != 0
    assert "User not found" in result.output
    assert not stub_price_fetcher.calls


def test_refresh_prices_requires_parameters() -> None:
    runner = CliRunner()
    result = runner.invoke(manage.app, ["refresh-prices"])

    assert result.exit_code != 0
    assert "Provide --product-id or use --all" in result.output


def test_refresh_prices_exclusive_arguments() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["refresh-prices", "--product-id", "1", "--all"],
    )

    assert result.exit_code != 0
    assert "Choose one of --product-id or --all" in result.output


def test_promote_admin_promotes_existing_user() -> None:
    with Session(manage.engine) as session:
        user = User(email="admin@example.com")
        session.add(user)
        session.commit()

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["promote-admin", "--email", "admin@example.com"],
    )

    assert result.exit_code == 0, result.stdout
    with Session(manage.engine) as session:
        promoted = session.exec(
            select(User).where(User.email == "admin@example.com")
        ).one()
        assert promoted.is_superuser is True


def test_promote_admin_missing_user_exits() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["promote-admin", "--email", "missing@example.com"],
    )

    assert result.exit_code == 1
    assert "User not found" in result.stdout


def test_issue_token_cmd_outputs_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with Session(manage.engine) as session:
        user = User(email="token@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)

    monkeypatch.setattr(
        manage,
        "issue_access_token",
        lambda settings, user_id, scope: f"token-{user_id}",
    )

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["issue-token-cmd", "--email", "token@example.com"],
    )

    assert result.exit_code == 0, result.stdout
    assert "token-" in result.stdout


def test_issue_token_cmd_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        manage,
        "issue_access_token",
        lambda settings, user_id, scope: "should-not-run",
    )

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["issue-token-cmd", "--email", "missing@example.com"],
    )

    assert result.exit_code == 1
    assert "User not found" in result.stdout


def test_track_url_creates_user_and_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_result = SimpleNamespace(
        title="CLI Added",
        product_id=101,
        product_url_id=202,
        store_id=303,
        price=88.5,
        currency="USD",
        image="https://example.com/image.jpg",
        warnings=[],
    )

    monkeypatch.setattr(
        manage, "quick_add_product", lambda *args, **kwargs: dummy_result
    )

    with Session(manage.engine) as session:
        session.add(User(email="owner@example.com"))
        session.commit()

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "track-url",
            "https://store.example.com/item",
            "--owner-email",
            "owner@example.com",
            "--owner-name",
            "Owner Name",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Tracked product" in result.stdout
    assert "CLI Added" in result.stdout
    assert "Seed price" in result.stdout

    with Session(manage.engine) as session:
        owner = session.exec(
            select(User).where(User.email == "owner@example.com")
        ).one()
        assert owner.full_name == "Owner Name"


def test_seed_sample_data_creates_records() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["seed-sample-data", "--owner-email", "owner@example.com"],
    )

    assert result.exit_code == 0, result.stdout
    with Session(manage.engine) as session:
        owner = session.exec(
            select(User).where(User.email == "owner@example.com")
        ).one()
        store_total = session.exec(select(func.count()).select_from(Store)).one()
        product_total = session.exec(select(func.count()).select_from(Product)).one()
        url_total = session.exec(select(func.count()).select_from(ProductURL)).one()
        price_total = session.exec(select(func.count()).select_from(PriceHistory)).one()

    assert owner.email == "owner@example.com"
    assert store_total == 1
    assert product_total == 1
    assert url_total >= 1
    assert price_total >= 1


def _insert_search_cache_entries() -> None:
    now = datetime.now(UTC)
    with Session(manage.engine) as session:
        session.add_all(
            [
                SearchCache(
                    query_hash="expired-1",
                    query="one",
                    response={},
                    expires_at=now - timedelta(days=2),
                ),
                SearchCache(
                    query_hash="expired-2",
                    query="two",
                    response={},
                    expires_at=now - timedelta(hours=12),
                ),
                SearchCache(
                    query_hash="future",
                    query="three",
                    response={},
                    expires_at=now + timedelta(days=3),
                ),
            ]
        )
        session.commit()


def test_prune_search_cache_cli_dry_run() -> None:
    _insert_search_cache_entries()
    runner = CliRunner()
    result = runner.invoke(manage.app, ["prune-search-cache", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    assert "Would remove 2 search cache entries" in result.stdout

    with Session(manage.engine) as session:
        remaining = session.exec(select(func.count()).select_from(SearchCache)).one()
    assert remaining == 3


def test_prune_search_cache_cli_prunes_entries() -> None:
    _insert_search_cache_entries()
    runner = CliRunner()
    result = runner.invoke(manage.app, ["prune-search-cache"])

    assert result.exit_code == 0, result.stdout
    assert "Removed 2 search cache entries" in result.stdout

    with Session(manage.engine) as session:
        remaining = session.exec(select(func.count()).select_from(SearchCache)).one()
    assert remaining == 1


def test_prune_search_cache_requires_single_threshold() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "prune-search-cache",
            "--dry-run",
            "--older-than-days",
            "2",
            "--before",
            "2025-01-01T00:00:00",
        ],
    )

    assert result.exit_code != 0
    assert "Provide either --older-than-days or --before" in result.stdout


def test_prune_search_cache_invalid_timestamp() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["prune-search-cache", "--before", "not-a-timestamp"],
    )

    assert result.exit_code != 0
    assert "Invalid ISO timestamp" in result.stdout


def test_create_store_cli_persists_locale_and_strategy() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "create-store",
            "--owner-email",
            "owner@example.com",
            "--name",
            "Custom Store",
            "--slug",
            "custom-store",
            "--website-url",
            "https://custom.example.com",
            "--domain",
            "custom.example.com",
            "--domain",
            "www.custom.example.com",
            "--locale",
            "en_US",
            "--currency",
            "USD",
            "--selector",
            "title=css:.product-title",
            "--selector",
            "price=json:$.price",
            "--selector",
            "image=attr:img::src",
            "--test-url",
            "https://custom.example.com/item/123",
            "--notes",
            "Curated store",
        ],
    )

    assert result.exit_code == 0, result.stdout

    with Session(manage.engine) as session:
        store = session.exec(select(Store)).one()
        assert store.slug == "custom-store"
        assert store.locale == "en_US"
        assert store.currency == "USD"
        assert store.notes == "Curated store"
        assert {entry["domain"] for entry in store.domains} == {
            "custom.example.com",
            "www.custom.example.com",
        }
        assert store.scrape_strategy["title"]["type"] == "css"
        assert store.scrape_strategy["price"]["value"] == "$.price"
        assert store.scrape_strategy["image"]["type"] == "attr"
        assert store.settings["test_url"] == "https://custom.example.com/item/123"
        assert store.settings["locale_settings"]["locale"] == "en_US"
        assert store.settings["locale_settings"]["currency"] == "USD"


def test_create_store_requires_domain_argument() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "create-store",
            "--owner-email",
            "owner@example.com",
            "--name",
            "Missing Domain Store",
            "--slug",
            "missing-domain",
        ],
    )

    assert result.exit_code != 0
    assert "Provide at least one --domain" in result.output


def test_create_store_rejects_blank_domain() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "create-store",
            "--owner-email",
            "owner@example.com",
            "--name",
            "Blank Domain Store",
            "--slug",
            "blank-domain",
            "--domain",
            " ",
        ],
    )

    assert result.exit_code != 0
    assert "non-empty --domain" in result.output


def test_list_products_cli_outputs_summary() -> None:
    with Session(manage.engine) as session:
        owner = User(email="owner@example.com")
        session.add(owner)
        session.commit()
        session.refresh(owner)

        store = Store(
            user_id=owner.id,
            name="CLI Store",
            slug="cli-store",
        )
        product = Product(
            user_id=owner.id,
            name="CLI Gadget",
            slug="cli-gadget",
        )
        session.add(store)
        session.add(product)
        session.commit()
        session.refresh(store)
        session.refresh(product)

        product_url = ProductURL(
            product_id=product.id,
            store_id=store.id,
            url="https://cli.example.com/gadget",
            is_primary=True,
        )
        session.add(product_url)
        session.commit()
        session.refresh(product_url)

        tag = Tag(user_id=owner.id, name="Gadgets", slug="gadgets")
        session.add(tag)
        session.commit()
        session.refresh(tag)
        session.execute(
            text(
                "INSERT INTO product_tag_link (product_id, tag_id) VALUES (:pid, :tid)"
            ),
            {"pid": product.id, "tid": tag.id},
        )
        session.commit()

        base_time = datetime.now(tz=UTC) - timedelta(days=2)
        session.add_all(
            [
                PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=120.0,
                    currency="USD",
                    recorded_at=base_time,
                ),
                PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=110.0,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=1),
                ),
                PriceHistory(
                    product_id=product.id,
                    product_url_id=product_url.id,
                    price=115.0,
                    currency="USD",
                    recorded_at=base_time + timedelta(days=2),
                ),
            ]
        )
        session.commit()

        rebuild_product_price_cache(session, product)
        session.commit()

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["list-products", "--owner-email", "owner@example.com", "--page-size", "1"],
    )

    assert result.exit_code == 0, result.stdout
    assert "CLI Gadget" in result.stdout
    assert "History:" in result.stdout
    assert "Primary:" in result.stdout
    assert "Tags:" in result.stdout
    assert "More products available" in result.stdout


def test_show_schedule_cli_outputs_json_and_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        {
            "name": "daily",
            "next_run_at": datetime(2025, 1, 1, tzinfo=UTC),
            "last_run_at": None,
            "enabled": True,
        }
    ]
    monkeypatch.setattr(manage, "describe_pricing_schedule", lambda session: entries)

    runner = CliRunner()
    result_json = runner.invoke(manage.app, ["show-schedule", "--json"])
    assert result_json.exit_code == 0, result_json.stdout
    assert '"daily"' in result_json.stdout

    result_table = runner.invoke(manage.app, ["show-schedule"])
    assert result_table.exit_code == 0, result_table.stdout
    assert "daily" in result_table.stdout
    assert "Enabled" in result_table.stdout


def test_show_schedule_cli_no_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manage, "describe_pricing_schedule", lambda session: [])

    runner = CliRunner()
    result = runner.invoke(manage.app, ["show-schedule"])
    assert result.exit_code == 0, result.stdout
    assert "No schedule entries configured" in result.stdout


def test_notifications_list_cli_outputs_channels() -> None:
    previous = {
        "notify_email_enabled": settings.notify_email_enabled,
        "smtp_host": settings.smtp_host,
        "notify_pushover_token": settings.notify_pushover_token,
        "notify_pushover_user": settings.notify_pushover_user,
    }
    settings.notify_email_enabled = True
    settings.smtp_host = "smtp.example.com"
    settings.notify_pushover_token = "pushover-token"
    settings.notify_pushover_user = None

    try:
        with Session(manage.engine) as session:
            user = User(email="notify@example.com")
            session.add(user)
            session.commit()
            session.refresh(user)
            session.add(
                NotificationSetting(
                    user_id=user.id,
                    channel="pushover",
                    enabled=False,
                    config={"user_key": "override"},
                )
            )
            session.commit()

        runner = CliRunner()
        result = runner.invoke(
            manage.app,
            ["notifications-list", "--owner-email", "notify@example.com"],
        )

        assert result.exit_code == 0, result.stdout
        assert "Channel" in result.stdout
        assert "email" in result.stdout
        assert "pushover" in result.stdout
        assert "no" in result.stdout  # pushover disabled
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)


def test_notifications_list_cli_missing_user() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        ["notifications-list", "--owner-email", "unknown@example.com"],
    )

    assert result.exit_code == 1
    assert "User not found" in result.output


def test_manage_helper_functions_cover_formatting() -> None:
    field, selector = manage._parse_selector("title=css:.name")
    assert field == "title"
    assert selector.type == "css"
    assert selector.value == ".name"

    with pytest.raises(typer.BadParameter):
        manage._parse_selector("invalid")

    formatted = manage._format_timestamp(datetime(2025, 5, 1, tzinfo=UTC))
    assert formatted != "—"
    assert formatted.startswith("2025")
    assert manage._format_timestamp(None) == "—"

    assert manage._format_price_value(42.0, "USD") == "USD 42.00"
    assert manage._format_price_value(None, None) == "—"

    product = SimpleNamespace(
        latest_price=SimpleNamespace(price=19.99, currency="CHF"),
        price_cache=[{"currency": "SEK"}],
    )
    assert manage._resolve_product_currency(cast(Any, product)) == "CHF"

    product_no_latest = SimpleNamespace(
        latest_price=None,
        price_cache=[SimpleNamespace(currency="AUD")],
    )
    assert manage._resolve_product_currency(cast(Any, product_no_latest)) == "AUD"

    assert manage._format_trend(manage.PriceTrend.DOWN) == "↓ down"
    assert manage._format_trend("mystery") == "mystery"


def test_notifications_set_cli_updates_preferences() -> None:
    previous = {
        "notify_pushover_token": settings.notify_pushover_token,
        "notify_pushover_user": settings.notify_pushover_user,
    }
    settings.notify_pushover_token = "pushover-token"
    settings.notify_pushover_user = None

    try:
        with Session(manage.engine) as session:
            user = User(email="notify@example.com")
            session.add(user)
            session.commit()
            session.refresh(user)

        runner = CliRunner()
        result = runner.invoke(
            manage.app,
            [
                "notifications-set",
                "--owner-email",
                "notify@example.com",
                "--channel",
                "pushover",
                "--enable",
                "--set",
                "user_key=override",
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "enabled" in result.stdout

        with Session(manage.engine) as session:
            setting = session.exec(
                select(NotificationSetting).where(
                    NotificationSetting.channel == "pushover"
                )
            ).one()
            assert setting.enabled is True
            assert setting.config == {"user_key": "override"}
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)


def test_notifications_set_cli_invalid_config_pair() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "notifications-set",
            "--owner-email",
            "notify@example.com",
            "--channel",
            "email",
            "--set",
            "missing-value",
        ],
    )

    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_notifications_set_cli_empty_config_key() -> None:
    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "notifications-set",
            "--owner-email",
            "notify@example.com",
            "--channel",
            "email",
            "--set",
            "=value",
        ],
    )

    assert result.exit_code != 0
    assert "key must not be empty" in result.output


def test_notifications_set_cli_handles_unknown_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(manage.engine) as session:
        user = User(email="notify@example.com")
        session.add(user)
        session.commit()

    def _raise_unknown(*args: Any, **kwargs: Any) -> None:
        raise UnknownNotificationChannelError("unsupported")

    monkeypatch.setattr(
        manage,
        "update_notification_channel_for_user",
        _raise_unknown,
    )

    runner = CliRunner()
    result = runner.invoke(
        manage.app,
        [
            "notifications-set",
            "--owner-email",
            "notify@example.com",
            "--channel",
            "email",
        ],
    )

    assert result.exit_code == 1
    assert "unsupported" in result.output
