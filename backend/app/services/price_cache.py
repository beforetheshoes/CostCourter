from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from sqlmodel import Session, select

from app.models import PriceHistory, Product, ProductURL, Store
from app.models.base import utcnow

DEFAULT_LOCALE = "en_US"
DEFAULT_CURRENCY = "USD"


class Trend(StrEnum):
    """Price trend categories retained for parity with the legacy stack."""

    UP = "up"
    DOWN = "down"
    LOWEST = "lowest"
    NONE = "none"


@dataclass(slots=True)
class PriceCacheEntry:
    store_id: int | None
    store_name: str | None
    url_id: int | None
    url: str | None
    trend: Trend
    price: float | None
    history: dict[date, float]
    last_scrape: datetime | None
    locale: str | None
    currency: str | None
    aggregates: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        sorted_history = dict(
            sorted((day.isoformat(), price) for day, price in self.history.items())
        )
        return {
            "store_id": self.store_id,
            "store_name": self.store_name,
            "url_id": self.url_id,
            "url": self.url,
            "trend": self.trend.value,
            "price": self.price,
            "history": sorted_history,
            "last_scrape": (
                self.last_scrape.astimezone(UTC).isoformat()
                if self.last_scrape and self.last_scrape.tzinfo is not None
                else (self.last_scrape.isoformat() if self.last_scrape else None)
            ),
            "locale": self.locale,
            "currency": self.currency,
            "aggregates": self.aggregates,
        }


def rebuild_product_price_cache(
    session: Session,
    product: Product,
    *,
    horizon_days: int = 365,
) -> list[dict[str, Any]]:
    """Recompute cached price aggregates for the given product.

    Returns a serialisable payload ready for persistence on the `Product` model.
    """

    if product.id is None:
        return []

    entries = _collect_price_cache_entries(session, product, horizon_days=horizon_days)
    entries.sort(
        key=lambda entry: (
            entry.price if entry.price is not None else float("inf"),
            entry.store_name or "",
        )
    )
    payload = [entry.as_dict() for entry in entries]

    product.price_cache = payload
    product.current_price = (
        entries[0].price if entries and entries[0].price is not None else None
    )
    product.updated_at = utcnow()

    return payload


def _collect_price_cache_entries(
    session: Session,
    product: Product,
    *,
    horizon_days: int,
) -> list[PriceCacheEntry]:
    product_url_join = cast(Any, PriceHistory.product_url_id == ProductURL.id)
    store_join = cast(Any, ProductURL.store_id == Store.id)
    statement = (
        select(PriceHistory, ProductURL, Store)
        .join(ProductURL, product_url_join, isouter=True)
        .join(Store, store_join, isouter=True)
        .where(PriceHistory.product_id == product.id)
        .where(PriceHistory.price > 0)
    )

    raw_rows = session.exec(statement).all()
    rows: Iterable[tuple[PriceHistory, ProductURL | None, Store | None]] = cast(
        Iterable[tuple[PriceHistory, ProductURL | None, Store | None]], raw_rows
    )
    grouped: dict[
        int | None, list[tuple[PriceHistory, ProductURL | None, Store | None]]
    ] = defaultdict(list)
    for history, product_url, store in rows:
        key = product_url.id if product_url and product_url.id is not None else None
        grouped[key].append((history, product_url, store))

    cutoff = utcnow() - timedelta(days=horizon_days) if horizon_days > 0 else None

    entries: list[PriceCacheEntry] = []
    for group in grouped.values():
        entry = _build_entry(group, cutoff=cutoff)
        if entry is not None:
            entries.append(entry)
    return entries


def _build_entry(
    rows: list[tuple[PriceHistory, ProductURL | None, Store | None]],
    *,
    cutoff: datetime | None,
) -> PriceCacheEntry | None:
    if not rows:
        return None

    rows.sort(key=lambda item: _normalize_datetime(item[0].recorded_at))

    history_by_day: dict[date, float] = {}
    last_scrape: datetime | None = None
    currency: str | None = None
    for history, _, _ in rows:
        recorded = _normalize_datetime(history.recorded_at)
        if cutoff is not None and recorded < cutoff:
            continue
        if last_scrape is None or recorded > last_scrape:
            last_scrape = recorded
        currency = history.currency or currency
        day = recorded.date()
        price_value = round(float(history.price), 2)
        previous = history_by_day.get(day)
        if previous is None or price_value < previous:
            history_by_day[day] = price_value

    if not history_by_day:
        return None

    if len(history_by_day) == 1:
        (only_day, only_price) = next(iter(history_by_day.items()))
        history_by_day[only_day - timedelta(days=1)] = only_price

    sorted_history = sorted(history_by_day.items())
    prices = [price for _, price in sorted_history]
    current_price = prices[-1] if prices else None
    average = sum(prices) / len(prices) if prices else 0.0
    lowest = min(prices) if prices else 0.0
    highest = max(prices) if prices else 0.0
    trend = (
        _calculate_trend(current_price, average, lowest)
        if current_price is not None
        else Trend.NONE
    )

    product_url = rows[0][1]
    store = rows[0][2]
    locale_settings: dict[str, Any] = {}
    if store and isinstance(store.settings, dict):
        locale_settings = store.settings.get("locale_settings", {}) or {}

    locale = (
        locale_settings.get("locale") if isinstance(locale_settings, dict) else None
    )
    currency_setting = (
        locale_settings.get("currency") if isinstance(locale_settings, dict) else None
    )

    entry_currency = currency or currency_setting or DEFAULT_CURRENCY
    entry_locale = locale or DEFAULT_LOCALE

    aggregates: dict[str, float] = {}
    if prices:
        aggregates = {
            "min": round(lowest, 2),
            "max": round(highest, 2),
            "avg": round(average, 2),
        }

    return PriceCacheEntry(
        store_id=store.id if store else None,
        store_name=store.name if store else None,
        url_id=product_url.id if product_url else None,
        url=product_url.url if product_url else None,
        trend=trend,
        price=current_price,
        history=dict(sorted_history),
        last_scrape=last_scrape,
        locale=entry_locale,
        currency=entry_currency,
        aggregates=aggregates,
    )


def _calculate_trend(current_price: float, average: float, lowest: float) -> Trend:
    if current_price <= lowest:
        return Trend.LOWEST
    if current_price < average:
        return Trend.DOWN
    if current_price > average:
        return Trend.UP
    return Trend.NONE


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)
