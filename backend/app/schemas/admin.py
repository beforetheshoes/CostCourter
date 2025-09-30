from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.catalog import PriceHistoryPoint, PriceTrend


class DashboardTotals(BaseModel):
    products: int = 0
    favourites: int = 0
    active_urls: int = 0


class DashboardProductSummary(BaseModel):
    id: int
    name: str
    slug: str
    current_price: float | None = None
    trend: PriceTrend = PriceTrend.NONE
    store_name: str | None = None
    image_url: str | None = None
    last_refreshed_at: datetime | None = None
    history: list[PriceHistoryPoint] = Field(default_factory=list)


class DashboardTagGroup(BaseModel):
    label: str
    products: list[DashboardProductSummary]


class DashboardMetricsResponse(BaseModel):
    totals: DashboardTotals
    spotlight: list[DashboardProductSummary]
    tag_groups: list[DashboardTagGroup]
    last_updated_at: datetime | None
