from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer
from pydantic import HttpUrl, TypeAdapter, ValidationError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.fixtures import install_reference_data, install_sample_catalog
from app.models import User
from app.schemas import (
    NotificationChannelName,
    NotificationChannelUpdateRequest,
    PriceTrend,
    ProductRead,
    StoreCreate,
    StoreDomain,
    StoreStrategyField,
)
from app.services import catalog
from app.services.auth import issue_access_token
from app.services.notification_preferences import (
    SECRET_PLACEHOLDER,
    InvalidNotificationConfigError,
    NotificationChannelUnavailableError,
    StoredConfigValue,
    UnknownNotificationChannelError,
    list_notification_channels_for_user,
    update_notification_channel_for_user,
)
from app.services.price_fetcher import get_price_fetcher_service
from app.services.pricing_schedule import describe_pricing_schedule
from app.services.product_quick_add import quick_add_product
from app.services.search_cache import prune_search_cache

app = typer.Typer(add_completion=False)


HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def _get_user_by_email(session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()


def _format_channel_config_value(value: str | None) -> str:
    if isinstance(value, str) and value == SECRET_PLACEHOLDER:
        return "[secret]"
    return value or ""


@app.command()
def promote_admin(
    email: Annotated[
        str,
        typer.Option("--email", help="User email to promote", show_default=False),
    ],
) -> None:
    """Promote a user to admin (is_superuser=True) by email."""
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            typer.echo(f"User not found: {email}")
            raise typer.Exit(code=1)
        user.is_superuser = True
        session.add(user)
        session.commit()
        typer.echo(f"Promoted {email} to admin")


@app.command()
def issue_token_cmd(
    email: Annotated[
        str,
        typer.Option(
            "--email",
            help="User email for token",
            show_default=False,
        ),
    ],
) -> None:
    """Issue a development access token for the given user email."""
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None or user.id is None:
            typer.echo(f"User not found: {email}")
            raise typer.Exit(code=1)
        token = issue_access_token(settings, user_id=user.id, scope=None)
        typer.echo(token)


@app.command()
def track_url(
    url: str = typer.Argument(..., help="Product URL to track"),
    owner_email: str = typer.Option(
        ...,
        "--owner-email",
        help="Email address of the item owner",
    ),
    owner_name: str | None = typer.Option(
        None,
        "--owner-name",
        help="Optional display name for the owner",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh/--no-refresh",
        help="Queue an immediate price refresh after creation",
    ),
) -> None:
    """Create store/product/url records for a given URL owned by ``owner_email``."""

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == owner_email)).first()
        if user is None:
            user = User(email=owner_email, full_name=owner_name)
            session.add(user)
            session.commit()
            session.refresh(user)
        elif owner_name and not user.full_name:
            user.full_name = owner_name
            session.add(user)
            session.commit()
            session.refresh(user)

        price_refresh = None
        if refresh:
            from app.tasks.pricing import update_product_prices_task

            def _enqueue(product_id: int) -> None:
                update_product_prices_task.delay(product_id=product_id, logging=False)

            price_refresh = _enqueue

        result = quick_add_product(
            session,
            owner=user,
            url=url,
            scraper_base_url=settings.scraper_base_url,
            price_refresh=price_refresh,
        )

        typer.echo("Tracked product:")
        typer.echo(f"  Title: {result.title}")
        typer.echo(f"  Product ID: {result.product_id}")
        typer.echo(f"  Product URL ID: {result.product_url_id}")
        typer.echo(f"  Store ID: {result.store_id}")
        if result.price not in (None, ""):
            typer.echo(f"  Seed price: {result.price} {result.currency}")
        if result.image:
            typer.echo(f"  Image: {result.image}")
        if result.warnings:
            typer.echo("Warnings:")
            for warning in result.warnings:
                typer.echo(f"  - {warning}")


def _parse_selector(value: str) -> tuple[str, StoreStrategyField]:
    if "=" not in value or ":" not in value:
        raise typer.BadParameter(
            "Selector must be in the form field=type:value (e.g. title=css:.selector)"
        )
    field, remainder = value.split("=", 1)
    selector_type, selector_value = remainder.split(":", 1)
    field_key = field.strip()
    selector_type = selector_type.strip()
    selector_value = selector_value.strip()
    if not field_key or not selector_type or not selector_value:
        raise typer.BadParameter(
            "Selector must provide non-empty field, type, and value"
        )
    return field_key, StoreStrategyField(type=selector_type, value=selector_value)


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_price_value(price: float | None, currency: str | None) -> str:
    if price is None:
        return "—"
    formatted = f"{price:,.2f}"
    return f"{currency} {formatted}" if currency else formatted


def _resolve_product_currency(product: ProductRead) -> str | None:
    latest = product.latest_price
    if latest and latest.currency:
        return latest.currency
    for entry in product.price_cache:
        if entry.currency:
            return entry.currency
    return None


def _format_trend(trend: PriceTrend | str) -> str:
    value = trend.value if isinstance(trend, PriceTrend) else str(trend)
    mapping = {
        "up": "↑ up",
        "down": "↓ down",
        "lowest": "★ lowest",
        "none": "—",
    }
    return mapping.get(value, value)


@app.command("list-products")
def list_products_cmd(
    owner_email: Annotated[
        str,
        typer.Option(
            "--owner-email",
            help="Email address whose catalog should be listed",
        ),
    ],
    search: Annotated[
        str | None,
        typer.Option(
            "--search",
            "-s",
            help="Filter products by name or slug substring",
            show_default=False,
        ),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option(
            "--tag",
            help="Filter by tag slug",
            show_default=False,
        ),
    ] = None,
    status: Annotated[
        str,
        typer.Option(
            "--status",
            help="Filter by active status",
            metavar="[all|active|inactive]",
            show_default=True,
        ),
    ] = "all",
    page: Annotated[
        int,
        typer.Option(
            "--page",
            min=1,
            help="Page number (1-indexed)",
        ),
    ] = 1,
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            min=1,
            max=100,
            help="Number of products per page",
        ),
    ] = 10,
) -> None:
    status_value = status.lower()
    if status_value not in {"all", "active", "inactive"}:
        typer.echo("Status must be one of: all, active, inactive")
        raise typer.Exit(code=1)

    normalized_search = search.strip() if search and search.strip() else None
    normalized_tag = tag.strip() if tag and tag.strip() else None
    is_active_filter = None
    if status_value == "active":
        is_active_filter = True
    elif status_value == "inactive":
        is_active_filter = False

    offset = (page - 1) * page_size

    with Session(engine) as session:
        owner = session.exec(select(User).where(User.email == owner_email)).first()
        if owner is None:
            typer.echo(f"Owner not found: {owner_email}")
            raise typer.Exit(code=1)

        products = catalog.list_products(
            session,
            owner=owner,
            limit=page_size,
            offset=offset,
            search=normalized_search,
            is_active=is_active_filter,
            tag=normalized_tag,
        )

    if not products:
        typer.echo("No products found.")
        return

    header = f"{'Name':30} {'Price':15} {'Trend':10} {'Last Refresh':25}"
    typer.echo(header)
    typer.echo("-" * len(header))

    for product in products:
        currency = _resolve_product_currency(product)
        price_value = product.current_price
        if price_value is None and product.latest_price is not None:
            price_value = product.latest_price.price
        price_display = _format_price_value(price_value, currency)
        trend_display = _format_trend(product.price_trend)
        refreshed_display = _format_timestamp(product.last_refreshed_at)
        name = product.name
        name_column = name if len(name) <= 30 else f"{name[:27]}…"
        typer.echo(
            f"{name_column:30} {price_display:15} {trend_display:10} {refreshed_display:25}"
        )

        primary_url = next(
            (url.url for url in product.urls if url.is_primary),
            None,
        )
        if primary_url:
            typer.echo(f"    Primary: {primary_url}")

        if product.history_points:
            recent = product.history_points[-3:]
            history_series = " → ".join(f"{point.price:.2f}" for point in recent)
            typer.echo(f"    History: {history_series}")

        if product.tags:
            tag_names = ", ".join(tag.name for tag in product.tags)
            typer.echo(f"    Tags: {tag_names}")

    if len(products) == page_size:
        typer.echo(
            f"More products available — rerun with --page {page + 1} to continue."
        )


@app.command("show-schedule")
def show_schedule_cmd(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output the schedule in JSON format",
            show_default=False,
        ),
    ] = False,
) -> None:
    """Display the Celery beat schedule with last/next run metadata."""

    with Session(engine) as session:
        entries = describe_pricing_schedule(session)

    if as_json:
        typer.echo(
            json.dumps(
                entries,
                indent=2,
                default=lambda value: (
                    value.isoformat() if isinstance(value, datetime) else value
                ),
            )
        )
        return

    if not entries:
        typer.echo("No schedule entries configured.")
        return

    header = f"{'Name':30} {'Next Run':25} {'Last Run':25} Enabled"
    typer.echo(header)
    typer.echo("-" * len(header))
    for entry in entries:
        name = entry.get("name", "<unknown>")
        next_run = _format_timestamp(entry.get("next_run_at"))
        last_run = _format_timestamp(entry.get("last_run_at"))
        enabled = "yes" if entry.get("enabled", True) else "no"
        typer.echo(f"{name:30} {next_run:25} {last_run:25} {enabled}")


@app.command("prune-search-cache")
def prune_search_cache_cmd(
    older_than_days: Annotated[
        int | None,
        typer.Option(
            "--older-than-days",
            min=1,
            help="Prune entries expiring on or before now minus the provided days.",
            show_default=False,
        ),
    ] = None,
    before: Annotated[
        str | None,
        typer.Option(
            "--before",
            help="Prune entries expiring on or before the ISO timestamp (UTC if no timezone).",
            show_default=False,
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview deletions without removing entries."),
    ] = False,
) -> None:
    """Remove stale SearX search cache rows based on expiry timestamps."""

    if older_than_days is not None and before is not None:
        typer.echo("Provide either --older-than-days or --before, not both.")
        raise typer.Exit(code=1)

    cutoff = None
    if before is not None:
        try:
            parsed = datetime.fromisoformat(before)
        except ValueError:
            typer.echo(
                "Invalid ISO timestamp for --before; expected YYYY-MM-DDTHH:MM:SS[±HH:MM]."
            )
            raise typer.Exit(code=1) from None
        cutoff = (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    elif older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    with Session(engine) as session:
        removed, threshold = prune_search_cache(session, before=cutoff, dry_run=dry_run)

    threshold_display = threshold.astimezone(UTC).isoformat()
    entry_word = "entry" if removed == 1 else "entries"

    if dry_run:
        typer.echo(
            f"Would remove {removed} search cache {entry_word} expiring on or before {threshold_display}."
        )
        if removed:
            typer.echo("Re-run without --dry-run to delete the cached responses.")
        return

    typer.echo(
        f"Removed {removed} search cache {entry_word} expiring on or before {threshold_display}."
    )
    if removed == 0:
        typer.echo("No stale search cache entries found.")


@app.command("create-store")
def create_store_cmd(
    owner_email: Annotated[
        str,
        typer.Option("--owner-email", help="Email that will own the store"),
    ],
    name: Annotated[str, typer.Option("--name", help="Store display name")],
    slug: Annotated[str, typer.Option("--slug", help="Unique slug")],
    website_url: Annotated[
        str | None,
        typer.Option(
            "--website-url",
            help="Optional website home page URL",
            show_default=False,
        ),
    ] = None,
    domains: Annotated[
        list[str] | None,
        typer.Option(
            "--domain",
            help="Domain associated with the store (repeat for multiple)",
        ),
    ] = None,
    selectors: Annotated[
        list[str] | None,
        typer.Option(
            "--selector",
            help="Selector mapping in field=type:value format (repeatable)",
        ),
    ] = None,
    locale: Annotated[
        str | None,
        typer.Option(
            "--locale", help="Locale identifier, e.g. en_US", show_default=False
        ),
    ] = None,
    currency: Annotated[
        str | None,
        typer.Option("--currency", help="Currency code, e.g. USD", show_default=False),
    ] = None,
    test_url: Annotated[
        str | None,
        typer.Option(
            "--test-url", help="Sample product URL for testing", show_default=False
        ),
    ] = None,
    notes: Annotated[
        str | None,
        typer.Option("--notes", help="Optional operator notes", show_default=False),
    ] = None,
) -> None:
    """Create a store with domains, selectors, and locale metadata."""

    if not domains:
        raise typer.BadParameter("Provide at least one --domain for the store")

    strategy: dict[str, StoreStrategyField] = {}
    for selector in selectors or []:
        key, field = _parse_selector(selector)
        strategy[key] = field

    normalized_currency = currency.strip().upper() if currency else None
    normalized_locale = locale.strip() if locale else None

    domain_models = [
        StoreDomain(domain=d.strip()) for d in (domains or []) if d.strip()
    ]
    if not domain_models:
        raise typer.BadParameter("Provide at least one non-empty --domain value")

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == owner_email)).first()
        if user is None:
            user = User(email=owner_email)
            session.add(user)
            session.commit()
            session.refresh(user)

        settings: dict[str, Any] = {
            "scraper_service": "http",
            "scraper_service_settings": "",
        }
        if test_url:
            settings["test_url"] = test_url
        if normalized_locale or normalized_currency:
            settings["locale_settings"] = {
                "locale": normalized_locale or "en_US",
                "currency": normalized_currency or "USD",
            }

        parsed_website: HttpUrl | None = None
        if website_url:
            try:
                parsed_website = HTTP_URL_ADAPTER.validate_python(website_url)
            except ValidationError as exc:
                raise typer.BadParameter("Invalid --website-url provided") from exc

        payload = StoreCreate(
            name=name,
            slug=slug,
            website_url=parsed_website,
            active=True,
            domains=domain_models,
            scrape_strategy=strategy,
            settings=settings,
            notes=notes,
            locale=normalized_locale,
            currency=normalized_currency,
        )

        created = catalog.create_store(session, payload, owner=user)

    typer.echo("Created store:")
    typer.echo(f"  ID: {created.id}")
    typer.echo(f"  Slug: {created.slug}")
    typer.echo(f"  Locale: {created.locale or '—'}")
    typer.echo(f"  Currency: {created.currency or '—'}")


@app.command()
def refresh_prices(
    product_id: int | None = typer.Option(
        None,
        "--product-id",
        help="Refresh a single product by its database ID",
    ),
    all_products: bool = typer.Option(
        False,
        "--all",
        help="Refresh all active products",
        is_flag=True,
    ),
    log: bool = typer.Option(
        False,
        "--log/--no-log",
        help="Enable verbose logging during the refresh",
    ),
    owner_email: str | None = typer.Option(
        None,
        "--owner-email",
        help="Restrict --all refresh to products owned by the given email",
    ),
) -> None:
    """Trigger manual price refreshes via the FastAPI price fetcher service."""

    if owner_email and not all_products:
        raise typer.BadParameter("--owner-email requires --all")
    if product_id is None and not all_products:
        raise typer.BadParameter(
            "Provide --product-id or use --all to refresh the catalog"
        )
    if product_id is not None and all_products:
        raise typer.BadParameter("Choose one of --product-id or --all, not both")

    service = get_price_fetcher_service()

    with Session(engine) as session:
        owner_id: int | None = None
        if owner_email:
            owner = session.exec(select(User).where(User.email == owner_email)).first()
            if owner is None or owner.id is None:
                raise typer.BadParameter(f"User not found for email {owner_email}")
            owner_id = owner.id

        if product_id is not None:
            summary = service.update_product_prices(session, product_id, logging=log)
            target_label = f"product {product_id}"
        else:
            summary = service.update_all_products(
                session,
                logging=log,
                owner_id=owner_id,
            )
            target_label = (
                f"all products for {owner_email}" if owner_email else "all products"
            )

    typer.echo(f"Triggered refresh for {target_label}.")
    typer.echo(f"URLs processed: {summary.total_urls}")
    typer.echo(f"Successful URLs: {summary.successful_urls}")
    typer.echo(f"Failed URLs: {summary.failed_urls}")

    if summary.results:
        typer.echo("Results:")
        for result in summary.results:
            status = "ok" if result.success else "failed"
            suffix_parts: list[str] = []
            if result.price is not None:
                formatted_price = (
                    f"{result.price:.2f}"
                    if isinstance(result.price, float)
                    else str(result.price)
                )
                if result.currency:
                    suffix_parts.append(f"price={formatted_price} {result.currency}")
                else:
                    suffix_parts.append(f"price={formatted_price}")
            if result.reason:
                suffix_parts.append(f"reason={result.reason}")
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            typer.echo(f"  - #{result.product_url_id} {status}{suffix}")


@app.command("notifications-list")
def notifications_list(
    owner_email: Annotated[
        str,
        typer.Option(
            "--owner-email",
            help="Email address whose notification channels should be listed",
        ),
    ],
    include_unavailable: Annotated[
        bool,
        typer.Option(
            "--all/--available-only",
            help="Show channels even when disabled via configuration",
        ),
    ] = False,
) -> None:
    """Display notification channel preferences for a user."""

    with Session(engine) as session:
        user = _get_user_by_email(session, owner_email)
        if user is None:
            typer.echo(f"User not found: {owner_email}")
            raise typer.Exit(code=1)

        channels = list_notification_channels_for_user(session, user)

    if not include_unavailable:
        channels = [channel for channel in channels if channel.available]

    if not channels:
        typer.echo("No notification channels found.")
        return

    header = f"{'Channel':<12}{'Enabled':<10}{'Available':<12}Config"
    typer.echo(header)
    typer.echo("-" * len(header))
    for channel in channels:
        enabled_label = "yes" if channel.enabled else "no"
        available_label = "yes" if channel.available else "no"
        config_parts = []
        for key, value in channel.config.items():
            display_value = _format_channel_config_value(value)
            if display_value:
                config_parts.append(f"{key}={display_value}")
        config_display = ", ".join(config_parts) if config_parts else "—"
        typer.echo(
            f"{channel.channel:<12}{enabled_label:<10}{available_label:<12}{config_display}"
        )
        if not channel.available and channel.unavailable_reason:
            typer.echo(f"  reason: {channel.unavailable_reason}")


@app.command("notifications-set")
def notifications_set(
    owner_email: Annotated[
        str,
        typer.Option(
            "--owner-email",
            help="Email address whose notification preference should be updated",
        ),
    ],
    channel: Annotated[
        NotificationChannelName,
        typer.Option("--channel", help="Channel slug to configure"),
    ],
    enabled: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable the channel"),
    ] = True,
    config_pairs: list[str] = typer.Option(
        [],
        "--set",
        help="Provide channel config as KEY=VALUE (repeat for multiple keys)",
    ),
) -> None:
    """Update a user's notification preference for a channel."""

    config: dict[str, str | None] = {}
    for pair in config_pairs:
        if "=" not in pair:
            raise typer.BadParameter(
                "Config values must be in KEY=VALUE form",
                param_hint="--set",
            )
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(
                "Config key must not be empty",
                param_hint="--set",
            )
        config[key] = value.strip() or None

    request = NotificationChannelUpdateRequest(
        enabled=enabled,
        config=config or None,
    )

    with Session(engine) as session:
        user = _get_user_by_email(session, owner_email)
        if user is None:
            typer.echo(f"User not found: {owner_email}")
            raise typer.Exit(code=1)

        try:
            result = update_notification_channel_for_user(
                session,
                user,
                channel,
                request,
            )
        except UnknownNotificationChannelError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1) from None
        except NotificationChannelUnavailableError as exc:
            message = exc.reason or str(exc)
            typer.echo(f"Error: {message}")
            raise typer.Exit(code=1) from None
        except InvalidNotificationConfigError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1) from None

    config_parts: list[str] = []
    config_items: dict[str, StoredConfigValue]
    if result.config is not None:
        config_items = dict(result.config)
    else:
        config_items = {}
    for key in config_items:
        stored_value = config_items[key]
        normalized_value: str | None
        if isinstance(stored_value, str):
            normalized_value = stored_value
        elif stored_value is None:
            normalized_value = None
        else:
            normalized_value = str(stored_value)
        display_value = _format_channel_config_value(normalized_value)
        if display_value:
            config_parts.append(f"{key}={display_value}")
    config_display = ", ".join(config_parts) if config_parts else "—"
    status_label = "enabled" if result.enabled else "disabled"
    typer.echo(f"Channel '{result.channel}' {status_label}.")
    if config_parts:
        typer.echo(f"Config: {config_display}")


@app.command()
def seed_sample_data(
    owner_email: Annotated[
        str,
        typer.Option("--owner-email", help="Email that will own the sample catalog"),
    ],
) -> None:
    """Install reference data and a sample catalog for local development."""

    with Session(engine) as session:
        owner = session.exec(select(User).where(User.email == owner_email)).first()
        if owner is None:
            owner = User(email=owner_email)
            session.add(owner)
            session.commit()
            session.refresh(owner)

        install_reference_data(session)
        result = install_sample_catalog(session, owner=owner)
        typer.echo("Seed data installed")
        typer.echo(f"  Store ID: {result.store_id}")
        typer.echo(f"  Product ID: {result.product_id}")
        if result.product_url_ids:
            typer.echo(f"  Product URLs: {', '.join(map(str, result.product_url_ids))}")


if __name__ == "__main__":
    app()
