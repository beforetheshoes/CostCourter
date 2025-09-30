from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import desc, func
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlmodel import Session, select

from app.models.product import Product, ProductStatus
from app.models.product_url import ProductURL
from app.models.user import User
from app.schemas import (
    DashboardMetricsResponse,
    DashboardProductSummary,
    DashboardTagGroup,
    DashboardTotals,
    PriceHistoryPoint,
    PriceTrend,
)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _build_history_points(entry: dict[str, Any]) -> list[PriceHistoryPoint]:
    history = entry.get("history")
    if not isinstance(history, dict):
        return []
    points: list[PriceHistoryPoint] = []
    for key, price in history.items():
        try:
            day = datetime.fromisoformat(f"{key}T00:00:00").date()
            points.append(PriceHistoryPoint(date=day, price=float(price)))
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item.date)
    return points[-10:]


def _extract_summary(product: Product) -> DashboardProductSummary | None:
    if product.id is None:
        return None
    if not product.price_cache:
        return None
    entry = product.price_cache[0]
    if not isinstance(entry, dict):
        return None
    trend_raw = entry.get("trend")
    try:
        trend = PriceTrend(str(trend_raw)) if trend_raw is not None else PriceTrend.NONE
    except ValueError:
        trend = PriceTrend.NONE
    last_refreshed = _parse_datetime(entry.get("last_scrape"))
    if last_refreshed is not None and last_refreshed.tzinfo is None:
        last_refreshed = last_refreshed.replace(tzinfo=UTC)
    current_price = entry.get("price")
    try:
        price_value: float | None = (
            None if current_price is None else float(current_price)
        )
    except (TypeError, ValueError):
        price_value = None
    history_points = _build_history_points(entry)
    return DashboardProductSummary(
        id=product.id,
        name=product.name,
        slug=product.slug,
        current_price=price_value,
        trend=trend,
        store_name=entry.get("store_name"),
        image_url=product.image_url,
        last_refreshed_at=last_refreshed,
        history=history_points,
    )


def build_dashboard_metrics(session: Session, owner: User) -> DashboardMetricsResponse:
    if owner.id is None:
        raise ValueError("Owner must have an identifier")

    owner_id = owner.id

    total_products = session.exec(
        select(func.count()).select_from(Product).where(Product.user_id == owner_id)
    ).one()
    total_favourites = session.exec(
        select(func.count())
        .select_from(Product)
        .where(Product.user_id == owner_id)
        .where(cast(InstrumentedAttribute[Any], Product.favourite).is_(True))
    ).one()
    product_ids_for_owner = select(Product.id).where(Product.user_id == owner_id)
    total_active_urls = session.exec(
        select(func.count())
        .select_from(ProductURL)
        .where(cast(InstrumentedAttribute[Any], ProductURL.active).is_(True))
        .where(
            cast(InstrumentedAttribute[Any], ProductURL.product_id).in_(
                product_ids_for_owner
            )
        )
    ).one()

    totals = DashboardTotals(
        products=int(total_products or 0),
        favourites=int(total_favourites or 0),
        active_urls=int(total_active_urls or 0),
    )

    product_statement = (
        select(Product)
        .where(Product.user_id == owner_id)
        .where(cast(InstrumentedAttribute[Any], Product.favourite).is_(True))
        .where(Product.status == ProductStatus.PUBLISHED)
        .order_by(desc(cast(InstrumentedAttribute[Any], Product.created_at)))
        .options(
            selectinload(
                cast(InstrumentedAttribute[Any], Product.tags),
            )
        )
    )
    favourite_products = session.exec(product_statement).all()

    summaries: list[DashboardProductSummary] = []
    grouped: dict[str, list[DashboardProductSummary]] = defaultdict(list)
    last_updated_at: datetime | None = None
    for product in favourite_products:
        summary = _extract_summary(product)
        if summary is None:
            continue
        summaries.append(summary)
        if product.updated_at and (
            last_updated_at is None or product.updated_at > last_updated_at
        ):
            last_updated_at = product.updated_at
        tag_names = sorted([tag.name for tag in product.tags]) if product.tags else []
        label = ", ".join(tag_names) if tag_names else "Uncategorized"
        grouped[label].append(summary)

    spotlight = summaries[: min(4, len(summaries))]

    tag_groups = [
        DashboardTagGroup(label=label, products=items)
        for label, items in grouped.items()
    ]
    tag_groups.sort(key=lambda group: group.label)

    return DashboardMetricsResponse(
        totals=totals,
        spotlight=spotlight,
        tag_groups=tag_groups,
        last_updated_at=last_updated_at,
    )


__all__ = ["build_dashboard_metrics"]
