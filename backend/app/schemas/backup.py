from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.models.product import ProductStatus


class BackupTag(BaseModel):
    slug: str
    name: str


class BackupStore(BaseModel):
    slug: str
    name: str
    website_url: HttpUrl | None = None
    active: bool = True
    locale: str | None = None
    currency: str | None = None
    domains: list[dict[str, Any]] = Field(default_factory=list)
    scrape_strategy: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class BackupProduct(BaseModel):
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
    tags: list[BackupTag] = Field(default_factory=list)


class BackupProductURL(BaseModel):
    url: HttpUrl
    is_primary: bool = False
    active: bool = True
    store: BackupStore


class BackupPriceHistory(BaseModel):
    price: float
    currency: str
    recorded_at: datetime
    url: HttpUrl | None = None


class ProductBackupEntry(BaseModel):
    product: BackupProduct
    urls: list[BackupProductURL] = Field(default_factory=list)
    price_history: list[BackupPriceHistory] = Field(default_factory=list)


class CatalogBackup(BaseModel):
    version: int = 1
    exported_at: datetime
    products: list[ProductBackupEntry] = Field(default_factory=list)


class CatalogImportResponse(BaseModel):
    products_created: int
    products_updated: int
    product_urls_created: int
    product_urls_updated: int
    price_history_created: int
    price_history_skipped: int
    stores_created: int
    stores_updated: int
    tags_created: int
    tags_updated: int
