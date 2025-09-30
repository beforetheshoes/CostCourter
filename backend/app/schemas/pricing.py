from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PriceFetchResultRead(BaseModel):
    product_url_id: int
    success: bool
    price: float | None = None
    currency: str | None = None
    reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PriceFetchSummaryRead(BaseModel):
    total_urls: int
    successful_urls: int
    failed_urls: int
    results: list[PriceFetchResultRead]

    model_config = ConfigDict(from_attributes=True)


class PriceFetchJobQueuedRead(BaseModel):
    task_id: str
    task_name: str
    status: str
    eta: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PricingScheduleEntry(BaseModel):
    name: str
    task: str
    schedule: Any | None = None
    enabled: bool | None = True
    args: list[Any] | None = None
    kwargs: dict[str, Any] | None = None
    minute: str | int | None = None
    hour: str | int | None = None
    day_of_week: str | int | None = None
    day_of_month: str | int | None = None
    month_of_year: str | int | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class PricingScheduleRead(BaseModel):
    entries: list[PricingScheduleEntry]
