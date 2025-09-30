from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest
from sqlmodel import Session

from app.services.notifications import (
    NotificationService,
    set_notification_service_factory,
)
from app.services.price_fetcher import (
    PriceFetcherService,
    PriceFetchResult,
    PriceFetchSummary,
    set_price_fetcher_service_factory,
)
from app.tasks.pricing import (
    set_task_session_factory,
    update_all_products_task,
    update_product_prices_task,
)


@dataclass
class _StubService:
    calls: list[dict[str, Any]]
    product_summary: PriceFetchSummary
    all_summary: PriceFetchSummary

    def update_product_prices(
        self,
        session: Session,
        product_id: int,
        *,
        logging: bool = False,
        owner_id: int | None = None,
        audit_actor_id: int | None = None,
        audit_ip: str | None = None,
    ) -> PriceFetchSummary:
        self.calls.append(
            {
                "mode": "product",
                "product_id": product_id,
                "logging": logging,
                "owner_id": owner_id,
                "actor_id": audit_actor_id,
                "ip": audit_ip,
                "session": session,
            }
        )
        return self.product_summary

    def update_all_products(
        self,
        session: Session,
        *,
        logging: bool = False,
        owner_id: int | None = None,
        audit_actor_id: int | None = None,
        audit_ip: str | None = None,
    ) -> PriceFetchSummary:
        self.calls.append(
            {
                "mode": "all",
                "logging": logging,
                "owner_id": owner_id,
                "actor_id": audit_actor_id,
                "ip": audit_ip,
                "session": session,
            }
        )
        return self.all_summary


class _DummySession:
    """Lightweight stand-in for a database session."""

    def close(self) -> None:
        return None


class _NotificationNoop(NotificationService):
    def __init__(self) -> None:
        super().__init__()

    def send_price_alert(self, *args: Any, **kwargs: Any) -> None:
        return None

    def notify_scrape_failure(self, *args: Any, **kwargs: Any) -> None:
        return None


@contextmanager
def _dummy_session_scope() -> Iterator[Session]:
    session = cast(Session, _DummySession())
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def reset_factories() -> Iterator[_StubService]:
    set_task_session_factory(_dummy_session_scope)
    set_notification_service_factory(lambda: _NotificationNoop())

    product_summary = PriceFetchSummary(
        total_urls=1,
        successful_urls=1,
        failed_urls=0,
        results=[PriceFetchResult(product_url_id=101, success=True, price=9.99)],
    )
    all_summary = PriceFetchSummary(total_urls=5, successful_urls=4, failed_urls=1)
    stub = _StubService([], product_summary, all_summary)

    def factory() -> PriceFetcherService:
        return cast(PriceFetcherService, stub)

    set_price_fetcher_service_factory(factory)
    try:
        yield stub
    finally:
        set_price_fetcher_service_factory(None)
        set_task_session_factory(None)
        set_notification_service_factory(None)


def test_update_product_prices_task_returns_summary(
    reset_factories: _StubService,
) -> None:
    payload = update_product_prices_task(product_id=7, logging=True)

    assert payload["total_urls"] == 1
    assert payload["successful_urls"] == 1
    assert payload["results"][0]["product_url_id"] == 101
    assert reset_factories.calls
    first_call = reset_factories.calls[0]
    assert first_call["mode"] == "product"
    assert first_call["product_id"] == 7
    assert first_call["logging"] is True


def test_update_all_products_task_returns_summary(
    reset_factories: _StubService,
) -> None:
    payload = update_all_products_task(logging=False)

    assert payload["total_urls"] == 5
    assert payload["successful_urls"] == 4
    assert payload["failed_urls"] == 1
    assert reset_factories.calls and reset_factories.calls[-1]["mode"] == "all"
    assert reset_factories.calls[-1]["logging"] is False


def test_update_product_prices_task_propagates_audit_metadata(
    reset_factories: _StubService,
) -> None:
    update_product_prices_task(
        product_id=12,
        logging=False,
        audit_actor_id=77,
        audit_ip="198.51.100.42",
    )

    assert reset_factories.calls
    call = reset_factories.calls[-1]
    assert call["mode"] == "product"
    assert call["actor_id"] == 77
    assert call["ip"] == "198.51.100.42"


def test_update_all_products_task_propagates_audit_metadata(
    reset_factories: _StubService,
) -> None:
    update_all_products_task(logging=True, audit_actor_id=91, audit_ip="203.0.113.7")

    assert reset_factories.calls
    call = reset_factories.calls[-1]
    assert call["mode"] == "all"
    assert call["actor_id"] == 91
    assert call["ip"] == "203.0.113.7"


def test_update_all_products_task_passes_owner_id(
    reset_factories: _StubService,
) -> None:
    update_all_products_task(logging=False, owner_id=42)

    assert reset_factories.calls
    call = reset_factories.calls[-1]
    assert call["mode"] == "all"
    assert call["owner_id"] == 42


def test_update_product_prices_task_passes_owner_id(
    reset_factories: _StubService,
) -> None:
    update_product_prices_task(product_id=3, logging=False, owner_id=99)

    assert reset_factories.calls
    call = reset_factories.calls[-1]
    assert call["mode"] == "product"
    assert call["owner_id"] == 99
