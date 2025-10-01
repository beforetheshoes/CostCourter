from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.models.product import ProductStatus


class StoreDomain(BaseModel):
    domain: str


class StoreStrategyField(BaseModel):
    type: str
    value: str
    data: str | float | int | None = None


class StoreBase(BaseModel):
    name: str
    slug: str
    website_url: HttpUrl | None = None
    active: bool = True
    domains: list[StoreDomain] = Field(default_factory=list)
    scrape_strategy: dict[str, StoreStrategyField] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    locale: str | None = None
    currency: str | None = None


class StoreCreate(StoreBase):
    pass


class StoreRead(StoreBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class StoreUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    website_url: HttpUrl | None = None
    active: bool | None = None
    domains: list[StoreDomain] | None = None
    scrape_strategy: dict[str, StoreStrategyField] | None = None
    settings: dict[str, Any] | None = None
    notes: str | None = None
    locale: str | None = None
    currency: str | None = None


class StoreQuickAddRequest(BaseModel):
    website: str
    currency: str | None = None
    locale: str | None = None

    @field_validator("website")
    @classmethod
    def _ensure_website(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Website must be provided")
        return normalized

    @field_validator("currency", "locale")
    @classmethod
    def _normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class StoreQuickAddResponse(BaseModel):
    store: StoreRead
    warnings: list[str] = Field(default_factory=list)
    created: bool


class TagBase(BaseModel):
    name: str
    slug: str


class TagCreate(TagBase):
    pass


class TagRead(TagBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class TagUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class ProductCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    is_active: bool = True
    status: ProductStatus = ProductStatus.PUBLISHED
    favourite: bool = True
    only_official: bool = False
    notify_price: float | None = None
    notify_percent: float | None = None
    ignored_urls: list[str] = Field(default_factory=list)
    image_url: str | None = None
    tag_slugs: list[str] = Field(default_factory=list)


class PriceTrend(StrEnum):
    UP = "up"
    DOWN = "down"
    LOWEST = "lowest"
    NONE = "none"


class PriceCacheEntry(BaseModel):
    store_id: int | None = None
    store_name: str | None = None
    url_id: int | None = None
    url: HttpUrl | None = None
    trend: PriceTrend = PriceTrend.NONE
    price: float | None = None
    history: dict[str, float] = Field(default_factory=dict)
    last_scrape: datetime | None = None
    locale: str | None = None
    currency: str | None = None
    aggregates: dict[str, float] = Field(default_factory=dict)


class PriceHistoryPoint(BaseModel):
    date: date
    price: float


class PriceAggregates(BaseModel):
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    locale: str | None = None


class ProductRead(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    is_active: bool
    status: ProductStatus
    favourite: bool
    only_official: bool
    notify_price: float | None
    notify_percent: float | None
    current_price: float | None
    price_cache: list[PriceCacheEntry]
    price_trend: PriceTrend = PriceTrend.NONE
    last_refreshed_at: datetime | None = None
    history_points: list[PriceHistoryPoint] = Field(default_factory=list)
    price_aggregates: PriceAggregates | None = None
    ignored_urls: list[str]
    image_url: str | None = None
    tags: list[TagRead]
    urls: list[ProductURLRead]
    latest_price: PriceHistoryRead | None = None
    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_active: bool | None = None
    status: ProductStatus | None = None
    favourite: bool | None = None
    only_official: bool | None = None
    notify_price: float | None = None
    notify_percent: float | None = None
    ignored_urls: list[str] | None = None
    image_url: str | None = None
    tag_slugs: list[str] | None = None


class ProductBulkUpdateAttributes(BaseModel):
    status: ProductStatus | None = None
    is_active: bool | None = None
    favourite: bool | None = None
    only_official: bool | None = None

    @model_validator(mode="after")
    def _ensure_updates(self) -> ProductBulkUpdateAttributes:
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one update field must be provided")
        return self


class ProductBulkUpdateRequest(BaseModel):
    product_ids: list[int]
    updates: ProductBulkUpdateAttributes

    @field_validator("product_ids")
    @classmethod
    def _ensure_product_ids(cls, value: list[int]) -> list[int]:
        unique_ids = list(dict.fromkeys(value))
        if not unique_ids:
            raise ValueError("At least one product id must be provided")
        return unique_ids


class ProductBulkUpdateResponse(BaseModel):
    updated_ids: list[int]
    skipped_ids: list[int]
    missing_ids: list[int]


class ProductURLCreate(BaseModel):
    product_id: int
    store_id: int
    url: HttpUrl
    is_primary: bool = False
    active: bool = True
    created_by_id: int | None = None


class ProductURLRead(BaseModel):
    id: int
    product_id: int
    store_id: int
    url: HttpUrl
    is_primary: bool
    active: bool
    created_by_id: int | None
    store: StoreRead | None = None
    latest_price: float | None = None
    latest_price_currency: str | None = None
    latest_price_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class ProductURLUpdate(BaseModel):
    store_id: int | None = None
    url: HttpUrl | None = None
    is_primary: bool | None = None
    active: bool | None = None
    created_by_id: int | None = None


class ProductURLMetadata(BaseModel):
    title: str | None = None
    description: str | None = None
    image: str | None = None
    price: str | None = None
    currency: str | None = None
    locale: str | None = None


class ProductURLRefreshResponse(BaseModel):
    product_id: int
    product_url_id: int
    metadata: ProductURLMetadata
    applied_name: str
    applied_image_url: str | None
    name_updated: bool
    image_updated: bool
    warnings: list[str] = Field(default_factory=list)


class PriceHistoryCreate(BaseModel):
    product_id: int
    price: float
    currency: str = "USD"
    product_url_id: int | None = None
    recorded_at: datetime | None = None


class PriceHistoryRead(BaseModel):
    id: int
    product_id: int
    product_url_id: int | None
    price: float
    currency: str
    recorded_at: datetime
    product_url: ProductURLRead | None = None
    model_config = ConfigDict(from_attributes=True)


class BulkImportItem(BaseModel):
    url: HttpUrl
    set_primary: bool = False


class BulkImportRequest(BaseModel):
    items: list[BulkImportItem]
    product_id: int | None = None
    search_query: str | None = Field(default=None, max_length=255)
    enqueue_refresh: bool = False

    @field_validator("items")
    @classmethod
    def _ensure_items(cls, value: list[BulkImportItem]) -> list[BulkImportItem]:
        if not value:
            raise ValueError("At least one item must be provided")
        return value


class BulkImportCreatedURL(BaseModel):
    product_url_id: int
    store_id: int
    url: HttpUrl
    is_primary: bool
    price: float | None = None
    currency: str | None = None


class BulkImportSkipped(BaseModel):
    url: HttpUrl
    reason: str


class BulkImportResponse(BaseModel):
    product_id: int
    product_name: str
    product_slug: str
    created_product: bool
    created_urls: list[BulkImportCreatedURL]
    skipped: list[BulkImportSkipped]


class TagMergeRequest(BaseModel):
    source_tag_id: int
    target_tag_id: int
    delete_source: bool = True

    @model_validator(mode="after")
    def _ensure_distinct(self) -> TagMergeRequest:
        if self.source_tag_id == self.target_tag_id:
            raise ValueError("Source and target tags must differ")
        return self


class TagMergeResponse(BaseModel):
    source_tag_id: int
    target_tag_id: int
    moved_links: int
    removed_duplicate_links: int
    deleted_source: bool
