from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

import httpx
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.models import AuditLog, PriceHistory, Product, ProductURL, Store, User
from app.services.notifications import (
    NotificationService,
    PriceAlertPayload,
    product_threshold_met,
    should_send_price_alert,
    url_price_changed_since_last_notification,
)
from app.services.price_fetcher import PriceFetchSummary


class _HttpClientStub:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.closed = False

    def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.posts.append({"url": url, "data": data, "json": json, "params": params})

    def close(self) -> None:
        self.closed = True


class _RecordingService(NotificationService):
    def __init__(
        self,
        settings: Settings,
        *,
        http_client_factory: Callable[[float], httpx.Client] | None = None,
    ) -> None:
        super().__init__(settings=settings, http_client_factory=http_client_factory)
        self.dispatched: list[tuple[str, dict[str, Any]]] = []

    def _dispatch_channel(
        self,
        channel: str,
        user: User,
        payload: PriceAlertPayload,
        *,
        config: dict[str, Any],
        template: str = "price",
    ) -> None:
        self.dispatched.append((channel, config))


class _DirectNotificationService(NotificationService):
    def send_pushover_public(
        self,
        payload: PriceAlertPayload,
        config: dict[str, Any],
    ) -> None:
        self._send_pushover(payload, config)

    def send_gotify_public(
        self,
        payload: PriceAlertPayload,
        config: dict[str, Any],
    ) -> None:
        self._send_gotify(payload, config)


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Any]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _create_catalog(session: Session) -> tuple[User, Product, ProductURL]:
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    session.refresh(owner)

    store = Store(user_id=owner.id, name="Example Store", slug="example-store")
    product = Product(user_id=owner.id, name="Widget", slug="widget")
    session.add(store)
    session.add(product)
    session.commit()
    session.refresh(store)
    session.refresh(product)

    product_url = ProductURL(
        product_id=product.id,
        store_id=store.id,
        url="https://example.com/widget",
        is_primary=True,
    )
    session.add(product_url)
    session.commit()
    session.refresh(product_url)
    return owner, product, product_url


def test_product_threshold_met_by_notify_price(engine: Any) -> None:
    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        product.notify_price = 100.0
        session.add(product)
        session.commit()
        history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=99.5,
            currency="USD",
        )
        session.add(history)
        session.commit()

        assert product_threshold_met(session, product=product, history=history) is True


def test_product_threshold_met_by_percent(engine: Any) -> None:
    with Session(engine) as session:
        _, product, product_url = _create_catalog(session)
        product.notify_percent = 10.0
        session.add(product)
        session.commit()

        first_history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=200.0,
            currency="USD",
        )
        session.add(first_history)
        session.commit()

        second_history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=175.0,
            currency="USD",
        )
        session.add(second_history)
        session.commit()

        assert (
            product_threshold_met(session, product=product, history=second_history)
            is True
        )


def test_url_price_changed_since_last_notification(engine: Any) -> None:
    with Session(engine) as session:
        _, product, product_url = _create_catalog(session)

        first = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=120.0,
            currency="USD",
            notified=True,
        )
        session.add(first)
        session.commit()

        repeat = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=120.0,
            currency="USD",
        )
        session.add(repeat)
        session.commit()

        should_notify = url_price_changed_since_last_notification(
            session,
            product_url=product_url,
            history=repeat,
        )
        assert should_notify is False


def test_should_send_price_alert_requires_threshold(engine: Any) -> None:
    with Session(engine) as session:
        _, product, product_url = _create_catalog(session)
        history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=210.0,
            currency="USD",
        )
        session.add(history)
        session.commit()

        assert (
            should_send_price_alert(
                session,
                product=product,
                product_url=product_url,
                history=history,
            )
            is False
        )


def test_notification_service_send_price_alert_records_channels(engine: Any) -> None:
    settings = Settings(
        notify_email_enabled=True,
        smtp_host="localhost",
        notify_pushover_token="token",
        notify_pushover_user="user",
        notify_gotify_url=cast(AnyHttpUrl, "https://gotify.local"),
        notify_gotify_token="secret",
    )

    service = _RecordingService(settings)

    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        product.notify_price = 150.0
        session.add(product)
        session.commit()

        history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=149.0,
            currency="USD",
        )
        session.add(history)
        session.commit()

        service.send_price_alert(
            session,
            product=product,
            product_url=product_url,
            history=history,
        )

        dispatched_channels = {channel for channel, _ in service.dispatched}
        assert dispatched_channels == {"email", "pushover", "gotify"}

        audit_entries = session.exec(select(AuditLog)).all()
        assert audit_entries and audit_entries[0].action == "notification.price_alert"


def test_notification_service_notify_scrape_failure(engine: Any) -> None:
    settings = Settings(notify_email_enabled=False)
    service = _RecordingService(settings)

    with Session(engine) as session:
        _, product, _ = _create_catalog(session)
        summary = PriceFetchSummary(failed_urls=1, total_urls=2)

        service.notify_scrape_failure(session, product=product, summary=summary)

        audit_entry = session.exec(select(AuditLog)).one()
        assert audit_entry.action == "notification.scrape_failure"


def test_send_pushover_uses_http_client() -> None:
    settings = Settings(notify_pushover_token="token", notify_pushover_user="user")
    recorder = _HttpClientStub()
    service = _DirectNotificationService(
        settings,
        http_client_factory=lambda _: cast(httpx.Client, recorder),
    )
    payload = PriceAlertPayload(
        title="Price drop",
        summary="Summary",
        product_url="https://example.com",
        price=10.0,
        currency="USD",
        store_name="Example Store",
    )

    service.send_pushover_public(payload, {"user_key": "user", "token": "token"})

    assert recorder.posts and recorder.closed is True


def test_send_gotify_posts_message() -> None:
    settings = Settings(
        notify_gotify_url=cast(AnyHttpUrl, "https://gotify.local"),
        notify_gotify_token="secret",
    )
    recorder = _HttpClientStub()
    service = _DirectNotificationService(
        settings,
        http_client_factory=lambda _: cast(httpx.Client, recorder),
    )
    payload = PriceAlertPayload(
        title="Price drop",
        summary="Summary",
        product_url=None,
        price=10.0,
        currency="USD",
        store_name=None,
    )

    service.send_gotify_public(
        payload, {"url": "https://gotify.local", "token": "secret"}
    )

    assert recorder.posts and recorder.posts[0]["params"] == {"token": "secret"}
