from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.models import (
    AuditLog,
    NotificationSetting,
    PriceHistory,
    Product,
    ProductURL,
    Store,
    User,
)
from app.models.base import utcnow
from app.services.notifications import (
    NotificationService,
    PriceAlertPayload,
    _coerce_float,
    get_notification_service,
    product_threshold_met,
    set_notification_service_factory,
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
def engine_fixture() -> Iterator[Engine]:
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


def test_product_threshold_met_by_notify_price(engine: Engine) -> None:
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


def test_product_threshold_met_by_percent(engine: Engine) -> None:
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


def test_url_price_changed_since_last_notification(engine: Engine) -> None:
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


def test_should_send_price_alert_requires_threshold(engine: Engine) -> None:
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


def test_notification_service_send_price_alert_records_channels(engine: Engine) -> None:
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


def test_notification_service_notify_scrape_failure(engine: Engine) -> None:
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


def test_send_channel_test_dispatches(engine: Engine) -> None:
    settings = Settings(
        notify_pushover_token=None,
        notify_pushover_user=None,
        app_name="CostCourter",
    )
    service = _RecordingService(settings)

    with Session(engine) as session:
        owner, _, _ = _create_catalog(session)
        assert owner.id is not None
        session.add(
            NotificationSetting(
                user_id=owner.id,
                channel="pushover",
                enabled=True,
                config={"api_token": "app-token", "user_key": "override"},
            )
        )
        session.commit()

        delivered = service.send_channel_test(session, user=owner, channel="pushover")

    assert delivered is True
    assert service.dispatched == [
        ("pushover", {"user_key": "override", "token": "app-token"})
    ]


def test_send_channel_test_returns_false_when_disabled(engine: Engine) -> None:
    settings = Settings(app_name="CostCourter")
    service = _RecordingService(settings)

    with Session(engine) as session:
        owner, _, _ = _create_catalog(session)
        assert owner.id is not None
        session.add(
            NotificationSetting(
                user_id=owner.id,
                channel="pushover",
                enabled=False,
                config={"api_token": "app-token", "user_key": "override"},
            )
        )
        session.commit()

        delivered = service.send_channel_test(session, user=owner, channel="pushover")

    assert delivered is False
    assert service.dispatched == []


def test_send_email_uses_configured_smtp() -> None:
    service = NotificationService(
        settings=Settings(
            notify_email_enabled=True,
            smtp_host="smtp.local",
            smtp_port=2525,
            smtp_username="user",
            smtp_password="pass",
            smtp_from_address="alerts@example.com",
        )
    )
    payload = PriceAlertPayload(
        title="Price alert",
        summary="Price changed",
        product_url="https://example.com/product",
        price=10.0,
        currency="USD",
        store_name="Example",
    )
    user = User(email="owner@example.com")

    smtp_context = MagicMock()
    smtp_client = MagicMock()
    smtp_context.__enter__.return_value = smtp_client

    with patch(
        "app.services.notifications.smtplib.SMTP", return_value=smtp_context
    ) as smtp_cls:
        service._send_email(user, payload, template="price")

    smtp_cls.assert_called_once_with("smtp.local", 2525)
    smtp_client.login.assert_called_once_with("user", "pass")
    smtp_client.send_message.assert_called_once()


def test_send_email_skips_when_disabled() -> None:
    service = NotificationService(
        settings=Settings(
            notify_email_enabled=True,
            smtp_host=None,
        )
    )
    payload = PriceAlertPayload(
        title="Notice",
        summary="No-op",
        product_url=None,
        price=0.0,
        currency=None,
        store_name=None,
    )
    user = User(email="owner@example.com")

    with patch("app.services.notifications.smtplib.SMTP") as smtp_cls:
        service._send_email(user, payload, template="system")
    smtp_cls.assert_not_called()


def test_send_system_alert_dispatches_enabled_channels(engine: Engine) -> None:
    http_stub = _HttpClientStub()
    settings_obj = Settings(
        notify_email_enabled=True,
        smtp_host="smtp.local",
        notify_gotify_url=cast(AnyHttpUrl, "https://notify.local"),
        notify_gotify_token="token",
    )
    service = _RecordingService(
        settings_obj,
        http_client_factory=lambda _: cast(httpx.Client, http_stub),
    )

    with Session(engine) as session:
        owner, _, _ = _create_catalog(session)
        assert owner.id is not None

        delivered = service.send_system_alert(
            session,
            user=owner,
            title="System",
            summary="Alert",
            link="https://example.com",
        )

    assert delivered is True
    dispatched_channels = {channel for channel, _ in service.dispatched}
    assert dispatched_channels == {"email", "gotify"}


def test_send_system_alert_returns_false_without_channels(engine: Engine) -> None:
    service = NotificationService(Settings(notify_email_enabled=False, smtp_host=None))
    with Session(engine) as session:
        owner, _, _ = _create_catalog(session)
        assert owner.id is not None

        delivered = service.send_system_alert(
            session,
            user=owner,
            title="Notice",
            summary="No channels",
            link=None,
        )

    assert delivered is False


def test_notification_service_defaults_to_runtime_settings() -> None:
    service = NotificationService()
    assert service._settings is not None  # noqa: SLF001 - internal check for coverage


def test_send_price_alert_returns_when_owner_missing(engine: Engine) -> None:
    service = NotificationService(Settings(notify_email_enabled=False))
    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        assert owner.id is not None
        owner_id = cast(int, owner.id)
        with session.no_autoflush:
            product.user_id = owner_id + 999
            object.__setattr__(product, "owner", None)

            history = PriceHistory(
                product_id=product.id,
                product_url_id=product_url.id,
                price=Decimal("19.99"),
                currency="USD",
            )

            service.send_price_alert(
                session,
                product=product,
                product_url=product_url,
                history=history,
            )


def test_send_price_alert_resolves_owner_without_channels(engine: Engine) -> None:
    service = NotificationService(Settings(notify_email_enabled=False))
    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        assert owner.id is not None
        with session.no_autoflush:
            object.__setattr__(product, "owner", None)

            history = PriceHistory(
                product_id=product.id,
                product_url_id=product_url.id,
                price=Decimal("42.00"),
                currency="USD",
            )

            service.send_price_alert(
                session,
                product=product,
                product_url=product_url,
                history=history,
            )
            assert product.owner is not None


def test_notify_scrape_failure_handles_missing_owner(engine: Engine) -> None:
    service = NotificationService(Settings(notify_email_enabled=False))
    summary = SimpleNamespace(failed_urls=3, total_urls=5)
    with Session(engine) as session:
        owner, product, _ = _create_catalog(session)
        assert owner.id is not None
        owner_id = cast(int, owner.id)
        with session.no_autoflush:
            object.__setattr__(product, "owner", None)
            product.user_id = owner_id + 999

            service.notify_scrape_failure(
                session,
                product=product,
                summary=summary,
            )


def test_notify_scrape_failure_dispatches_channels(engine: Engine) -> None:
    settings = Settings(
        notify_email_enabled=True,
        smtp_host="smtp.local",
        notify_pushover_token="server-token",
        notify_pushover_user="server-user",
    )
    service = _RecordingService(settings)
    with Session(engine) as session:
        owner, product, _ = _create_catalog(session)
        assert owner.id is not None

        summary = SimpleNamespace(failed_urls=2, total_urls=4)
        service.notify_scrape_failure(
            session,
            product=product,
            summary=summary,
        )

    dispatched_channels = {channel for channel, _ in service.dispatched}
    assert dispatched_channels == {"email", "pushover"}


def test_resolve_channels_includes_optional_providers(engine: Engine) -> None:
    settings = Settings(
        notify_email_enabled=True,
        smtp_host="smtp.local",
        notify_pushover_token="token",
        notify_pushover_user="user",
        notify_gotify_url=cast(AnyHttpUrl, "https://notify.local"),
        notify_gotify_token="token",
        apprise_config_path="/etc/apprise.yml",
    )
    service = NotificationService(settings)
    with Session(engine) as session:
        owner, _, _ = _create_catalog(session)
        channels = dict(service._resolve_channels(session, owner))

    assert "email" in channels
    assert "gotify" in channels
    assert "apprise" in channels


def test_dispatch_channel_routes_all_types(engine: Engine) -> None:
    service = NotificationService(
        Settings(notify_email_enabled=True, smtp_host="smtp.local")
    )
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url=None,
        price=10.0,
        currency="USD",
        store_name="Store",
    )
    user = User(email="owner@example.com")

    with (
        patch.object(service, "_send_email") as email_mock,
        patch.object(service, "_send_pushover") as pushover_mock,
        patch.object(service, "_send_gotify") as gotify_mock,
        patch.object(service, "_send_apprise") as apprise_mock,
    ):
        service._dispatch_channel("email", user, payload, config={}, template="system")
        service._dispatch_channel(
            "pushover", user, payload, config={}, template="system"
        )
        service._dispatch_channel("gotify", user, payload, config={}, template="system")
        service._dispatch_channel(
            "apprise", user, payload, config={}, template="system"
        )

    email_mock.assert_called_once()
    pushover_mock.assert_called_once()
    gotify_mock.assert_called_once()
    apprise_mock.assert_called_once()


def test_send_pushover_handles_missing_credentials() -> None:
    service = NotificationService(Settings())
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url=None,
        price=10.0,
        currency="USD",
        store_name=None,
    )
    service._send_pushover(payload, {})


def test_send_gotify_handles_missing_credentials() -> None:
    service = NotificationService(Settings())
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url=None,
        price=10.0,
        currency="USD",
        store_name=None,
    )
    service._send_gotify(payload, {})


def test_send_gotify_attaches_button_when_url_present() -> None:
    class _ClientStub:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(self, url: str, params: dict[str, Any], json: dict[str, Any]) -> None:
            self.calls.append({"url": url, "params": params, "json": json})

        def close(self) -> None:  # pragma: no cover - no-op
            pass

    stub = _ClientStub()
    service = NotificationService(
        Settings(),
        http_client_factory=lambda _: cast(httpx.Client, stub),
    )
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url="https://example.com",
        price=10.0,
        currency="USD",
        store_name=None,
    )
    service._send_gotify(
        payload,
        {"token": "token", "url": "https://notify.local"},
    )
    assert stub.calls
    body = stub.calls[0]["json"]
    assert "extras" in body and "client::buttons" in body


def test_send_apprise_handles_missing_config() -> None:
    service = NotificationService(Settings())
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url=None,
        price=10.0,
        currency="USD",
        store_name=None,
    )
    service._send_apprise(payload, {})


def test_send_apprise_dispatches_with_stubbed_library() -> None:
    notifications: list[tuple[str, str]] = []

    class _AppriseStub:
        def __init__(self) -> None:
            self.configs: list[str] = []

        def add(self, config: Any) -> None:
            self.configs.append(config.path)

        def notify(self, body: str, title: str) -> None:
            notifications.append((body, title))

    class _AppriseConfigStub:
        def __init__(self, path: str) -> None:
            self.path = path

    module = ModuleType("apprise")
    module_any = cast(Any, module)
    module_any.Apprise = lambda: _AppriseStub()
    module_any.AppriseConfig = _AppriseConfigStub

    service = NotificationService(Settings())
    payload = PriceAlertPayload(
        title="Title",
        summary="Summary",
        product_url="https://example.com",
        price=10.0,
        currency="USD",
        store_name=None,
    )

    sys.modules["apprise"] = module
    try:
        service._send_apprise(
            payload,
            {"config_path": "/etc/apprise.yml"},
        )
    finally:
        sys.modules.pop("apprise", None)

    assert notifications


def test_coerce_float_handles_various_inputs() -> None:
    assert _coerce_float(None) is None
    assert _coerce_float(5) == 5.0
    assert _coerce_float(Decimal("7.5")) == 7.5


def test_product_threshold_met_requires_product_id(engine: Engine) -> None:
    product = Product(user_id=1, name="Orphan", slug="orphan")
    history = PriceHistory(price=Decimal("12.0"), currency="USD")
    with Session(engine) as session:
        assert product_threshold_met(session, product=product, history=history) is False


def test_product_threshold_met_false_when_price_missing(engine: Engine) -> None:
    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=None,
            currency="USD",
        )
        assert product_threshold_met(session, product=product, history=history) is False


def test_url_price_changed_since_last_notification_blank_id() -> None:
    product_url = ProductURL(
        product_id=1, store_id=1, url="https://example.com", is_primary=True
    )
    product_url.id = None
    history = PriceHistory(price=Decimal("10.0"), currency="USD")

    class _ExecStub:
        def exec(self, *_: Any, **__: Any) -> Any:
            return SimpleNamespace(first=lambda: None)

    dummy_session = cast(Session, _ExecStub())
    result = url_price_changed_since_last_notification(
        dummy_session,
        product_url=product_url,
        history=history,
    )
    assert result is True


class _FakeResult:
    def __init__(self, *, first: Any = None, all_values: Any = None) -> None:
        self._first = first
        self._all = all_values

    def first(self) -> Any:
        return self._first

    def all(self) -> Any:
        return self._all


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results

    def exec(self, *_: Any, **__: Any) -> _FakeResult:
        return self._results.pop(0)


def test_url_price_changed_since_last_notification_when_recent_entries_empty() -> None:
    product_url = ProductURL(
        product_id=1, store_id=1, url="https://example.com", is_primary=True
    )
    product_url.id = 10
    recorded_at = utcnow()
    session_stub = cast(
        Session,
        _FakeSession(
            [
                _FakeResult(
                    first=SimpleNamespace(
                        price=Decimal("10.0"), recorded_at=recorded_at
                    ),
                ),
                _FakeResult(all_values=[]),
            ]
        ),
    )
    history = PriceHistory(price=Decimal("12.0"), currency="USD")
    assert (
        url_price_changed_since_last_notification(
            session_stub, product_url=product_url, history=history
        )
        is True
    )


def test_should_send_price_alert_returns_false_when_threshold_not_met(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        owner, product, product_url = _create_catalog(session)
        product.notify_price = 1.0
        history = PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=Decimal("5.0"),
            currency="USD",
        )
        assert (
            should_send_price_alert(
                session,
                product=product,
                product_url=product_url,
                history=history,
            )
            is False
        )


def test_get_notification_service_uses_default_factory() -> None:
    set_notification_service_factory(None)
    service = get_notification_service()
    assert isinstance(service, NotificationService)
