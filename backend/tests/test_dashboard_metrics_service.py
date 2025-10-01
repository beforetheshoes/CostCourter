"""Direct unit tests for dashboard metrics helpers."""

from __future__ import annotations

from datetime import date

from app.models import Product
from app.schemas.catalog import PriceTrend
from app.services.dashboard_metrics import _build_history_points, _extract_summary


def test_build_history_points_filters_invalid_entries() -> None:
    entry = {
        "history": {
            "2024-05-01": 99.5,
            "invalid": "oops",
            "2024-05-03": "104.25",
        }
    }
    points = _build_history_points(entry)
    assert [point.date for point in points] == [date(2024, 5, 1), date(2024, 5, 3)]
    assert [point.price for point in points] == [99.5, 104.25]


def test_extract_summary_normalizes_trend_and_times() -> None:
    product = Product(user_id=1, name="Widget", slug="widget")
    product.id = 42
    product.price_cache = [
        {
            "trend": "unexpected",
            "last_scrape": "2024-05-04T12:00:00",
            "price": "199.99",
            "store_name": "Example Shop",
            "history": {
                "2024-05-02": 205.0,
                "bad": "-",
                "2024-05-03": 199.99,
            },
        }
    ]

    summary = _extract_summary(product)
    assert summary is not None
    assert summary.trend is PriceTrend.NONE
    assert summary.last_refreshed_at is not None
    assert summary.last_refreshed_at.tzinfo is not None
    assert summary.current_price == 199.99
    assert summary.history[-1].price == 199.99
