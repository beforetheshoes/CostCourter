from __future__ import annotations

import smtplib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from email.message import EmailMessage
from typing import Any, cast

import httpx
import structlog
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.config import settings as runtime_settings
from app.models import (
    NotificationSetting,
    PriceHistory,
    Product,
    ProductURL,
    Store,
    User,
)
from app.services.audit import record_audit_log
from app.services.notification_preferences import decrypt_secret_value

_logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PriceAlertPayload:
    title: str
    summary: str
    product_url: str | None
    price: float
    currency: str | None
    store_name: str | None


def _default_http_client(timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(timeout=timeout)


class NotificationService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client_factory: Callable[[float], httpx.Client] | None = None,
    ) -> None:
        self._settings = settings or runtime_settings
        self._http_client_factory = http_client_factory or _default_http_client

    # ---------------------------------------------------------------------
    # Public API used by price fetching services
    # ---------------------------------------------------------------------
    def send_price_alert(
        self,
        session: Session,
        *,
        product: Product,
        product_url: ProductURL,
        history: PriceHistory,
    ) -> None:
        owner = product.owner
        if owner is None and product.user_id is not None:
            owner = session.get(User, product.user_id)
            if owner is not None:
                product.owner = owner
        if owner is None or owner.id is None:
            _logger.info(
                "notifications.price_alert.skip_no_owner",
                product_id=product.id,
            )
            return

        payload = self._build_price_alert_payload(
            session, product, product_url, history
        )
        channels = list(self._resolve_channels(session, owner))
        if not channels:
            _logger.info(
                "notifications.price_alert.no_channels",
                product_id=product.id,
                user_id=owner.id,
            )
            return

        for channel, config in channels:
            try:
                self._dispatch_channel(
                    channel,
                    owner,
                    payload,
                    config=config,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                _logger.warning(
                    "notifications.price_alert.channel_error",
                    channel=channel,
                    user_id=owner.id,
                    product_id=product.id,
                    error=str(exc),
                )

        record_audit_log(
            session,
            action="notification.price_alert",
            actor_id=owner.id,
            entity_type="product",
            entity_id=str(product.id) if product.id is not None else None,
            context={
                "product_url": product_url.url,
                "store": payload.store_name,
                "price": payload.price,
                "currency": payload.currency,
            },
        )

    def notify_scrape_failure(
        self,
        session: Session,
        *,
        product: Product,
        summary: Any,
    ) -> None:
        owner = product.owner
        if owner is None and product.user_id is not None:
            owner = session.get(User, product.user_id)
            if owner is not None:
                product.owner = owner
        if owner is None or owner.id is None:
            return

        channels = list(self._resolve_channels(session, owner))
        message = PriceAlertPayload(
            title="Error scraping product urls",
            summary=product.name,
            product_url=None,
            price=(
                float(summary.failed_urls) if hasattr(summary, "failed_urls") else 0.0
            ),
            currency=None,
            store_name=None,
        )

        for channel, config in channels:
            try:
                self._dispatch_channel(
                    channel,
                    owner,
                    message,
                    config=config,
                    template="failure",
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                _logger.warning(
                    "notifications.scrape_failure.channel_error",
                    channel=channel,
                    user_id=owner.id,
                    product_id=product.id,
                    error=str(exc),
                )

        record_audit_log(
            session,
            action="notification.scrape_failure",
            actor_id=owner.id,
            entity_type="product",
            entity_id=str(product.id) if product.id is not None else None,
            context={
                "failed_urls": getattr(summary, "failed_urls", None),
                "total_urls": getattr(summary, "total_urls", None),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_channels(
        self,
        session: Session,
        user: User,
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        settings_by_channel = {
            setting.channel: setting
            for setting in session.exec(
                select(NotificationSetting).where(
                    NotificationSetting.user_id == user.id
                )
            )
        }

        if self._settings.notify_email_enabled and user.email:
            setting = settings_by_channel.get("email")
            if setting is None or setting.enabled:
                email_config = dict(setting.config or {}) if setting else {}
                yield "email", email_config

        pushover_setting = settings_by_channel.get("pushover")
        config_data: dict[str, Any] = (
            dict(pushover_setting.config or {}) if pushover_setting else {}
        )
        token = None
        raw_token = config_data.get("api_token")
        if isinstance(raw_token, str):
            token = decrypt_secret_value(raw_token, config=self._settings)
        if not token:
            token = self._settings.notify_pushover_token

        user_key = None
        raw_user_key = config_data.get("user_key")
        if isinstance(raw_user_key, str):
            user_key = decrypt_secret_value(raw_user_key, config=self._settings)
        if not user_key:
            user_key = self._settings.notify_pushover_user

        if (
            token
            and user_key
            and (pushover_setting is None or pushover_setting.enabled)
        ):
            yield "pushover", {"user_key": user_key, "token": token}

        gotify_url = self._settings.notify_gotify_url
        gotify_token = self._settings.notify_gotify_token
        if gotify_url and gotify_token:
            setting = settings_by_channel.get("gotify")
            if setting is None or setting.enabled:
                yield "gotify", {"url": str(gotify_url), "token": gotify_token}

        apprise_path = self._settings.apprise_config_path
        if apprise_path:
            setting = settings_by_channel.get("apprise")
            if setting is None or setting.enabled:
                yield "apprise", {"config_path": apprise_path}

    def _resolve_channel_config(
        self,
        session: Session,
        user: User,
        channel: str,
    ) -> dict[str, Any] | None:
        for resolved_channel, config in self._resolve_channels(session, user):
            if resolved_channel == channel:
                return config
        return None

    def send_channel_test(
        self,
        session: Session,
        *,
        user: User,
        channel: str,
    ) -> bool:
        config = self._resolve_channel_config(session, user, channel)
        if config is None:
            return False

        payload = PriceAlertPayload(
            title=f"{self._settings.app_name} notification test",
            summary="This is a test notification from CostCourter.",
            product_url=None,
            price=0.0,
            currency=None,
            store_name=None,
        )
        self._dispatch_channel(
            channel,
            user,
            payload,
            config=config,
            template="system",
        )
        return True

    def send_system_alert(
        self,
        session: Session,
        *,
        user: User,
        title: str,
        summary: str,
        link: str | None = None,
    ) -> bool:
        """Dispatch a system alert to ``user`` via enabled channels."""

        payload = PriceAlertPayload(
            title=title,
            summary=summary,
            product_url=link,
            price=0.0,
            currency=None,
            store_name=None,
        )
        delivered = False
        for channel, config in self._resolve_channels(session, user):
            self._dispatch_channel(
                channel,
                user,
                payload,
                config=config,
                template="system",
            )
            delivered = True
        return delivered

    def _dispatch_channel(
        self,
        channel: str,
        user: User,
        payload: PriceAlertPayload,
        *,
        config: dict[str, Any],
        template: str = "price",
    ) -> None:
        if channel == "email":
            self._send_email(user, payload, template=template)
        elif channel == "pushover":
            self._send_pushover(payload, config)
        elif channel == "gotify":
            self._send_gotify(payload, config)
        elif channel == "apprise":
            self._send_apprise(payload, config)
        else:  # pragma: no cover - defensive logging
            _logger.info("notifications.channel.skipped", channel=channel)

    def _build_price_alert_payload(
        self,
        session: Session,
        product: Product,
        product_url: ProductURL,
        history: PriceHistory,
    ) -> PriceAlertPayload:
        store = session.get(Store, product_url.store_id)
        currency = history.currency
        price_value = float(history.price)
        formatted_price = f"{price_value:,.2f}"
        price_with_currency = (
            f"{currency} {formatted_price}" if currency else formatted_price
        )
        title = f"Price drop: {product.name} ({price_with_currency})"
        store_name = store.name if store else None
        summary_parts = [
            store_name or "Store",
            "has had a price drop for",
            product.name,
            "-",
            price_with_currency,
        ]
        summary = " ".join(part for part in summary_parts if part)

        return PriceAlertPayload(
            title=title,
            summary=summary,
            product_url=product_url.url,
            price=price_value,
            currency=currency,
            store_name=store_name,
        )

    def _send_email(
        self,
        user: User,
        payload: PriceAlertPayload,
        *,
        template: str,
    ) -> None:
        host = self._settings.smtp_host
        port = self._settings.smtp_port or 587
        if not host:
            _logger.info("notifications.email.disabled")
            return

        message = EmailMessage()
        message["To"] = user.email
        from_address = self._settings.smtp_from_address or "alerts@example.com"
        message["From"] = from_address
        message["Subject"] = payload.title
        body_lines = [payload.summary]
        if payload.product_url:
            body_lines.append(f"Product URL: {payload.product_url}")
        message.set_content("\n".join(body_lines))

        with smtplib.SMTP(host, port) as smtp:
            if self._settings.smtp_username and self._settings.smtp_password:
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
            smtp.send_message(message)

    def _send_pushover(
        self,
        payload: PriceAlertPayload,
        config: dict[str, Any],
    ) -> None:
        user_key = config.get("user_key")
        token = config.get("token")
        if not user_key or not token:
            _logger.info("notifications.pushover.missing_credentials")
            return

        client = self._http_client_factory(10.0)
        data = {
            "token": token,
            "user": user_key,
            "message": payload.summary,
            "title": payload.title,
        }
        if payload.product_url:
            data["url"] = payload.product_url
            data["url_title"] = "View product"

        client.post("https://api.pushover.net/1/messages.json", data=data)
        client.close()

    def _send_gotify(
        self,
        payload: PriceAlertPayload,
        config: dict[str, Any],
    ) -> None:
        token = config.get("token")
        base_url = config.get("url")
        if not token or not base_url:
            _logger.info("notifications.gotify.missing_credentials")
            return

        client = self._http_client_factory(10.0)
        endpoint = f"{base_url.rstrip('/')}/message"
        params = {"token": token}
        body = {
            "title": payload.title,
            "message": payload.summary,
            "priority": 5,
        }
        if payload.product_url:
            body["extras"] = {"client::display": {"contentType": "text/plain"}}
            body["client::buttons"] = [{"label": "View", "url": payload.product_url}]
        client.post(endpoint, params=params, json=body)
        client.close()

    def _send_apprise(
        self,
        payload: PriceAlertPayload,
        config: dict[str, Any],
    ) -> None:
        config_path = config.get("config_path")
        if not config_path:
            _logger.info("notifications.apprise.missing_config")
            return

        try:
            import apprise
        except ImportError:  # pragma: no cover - optional dependency
            _logger.warning("notifications.apprise.not_installed")
            return

        app = apprise.Apprise()
        app.add(apprise.AppriseConfig(path=config_path))
        body_lines = [payload.summary]
        if payload.product_url:
            body_lines.append(payload.product_url)
        app.notify(body="\n".join(body_lines), title=payload.title)


def _coerce_float(value: float | Decimal | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)
    return float(value)


def product_threshold_met(
    session: Session,
    *,
    product: Product,
    history: PriceHistory,
) -> bool:
    if product.id is None:
        return False

    price_value = _coerce_float(history.price)
    if price_value is None:
        return False

    if product.notify_price is not None and price_value <= float(product.notify_price):
        return True

    if product.notify_percent is not None and product.notify_percent > 0:
        recorded_at_column = cast(Any, PriceHistory.recorded_at)
        first_history = session.exec(
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .order_by(recorded_at_column)
        ).first()
        if first_history and first_history.price is not None:
            starting_price = _coerce_float(first_history.price)
            if starting_price:
                threshold = starting_price - (
                    starting_price * (float(product.notify_percent) / 100.0)
                )
                return price_value <= threshold

    return False


def url_price_changed_since_last_notification(
    session: Session,
    *,
    product_url: ProductURL,
    history: PriceHistory,
) -> bool:
    if product_url.id is None:
        return True

    notified_column = cast(Any, PriceHistory.notified)
    recorded_at_column = cast(Any, PriceHistory.recorded_at)
    last_notified = session.exec(
        select(PriceHistory)
        .where(PriceHistory.product_url_id == product_url.id)
        .where(notified_column.is_(True))
        .order_by(recorded_at_column.desc())
    ).first()

    if last_notified is None:
        return True

    recent_entries = session.exec(
        select(PriceHistory)
        .where(PriceHistory.product_url_id == product_url.id)
        .where(recorded_at_column >= last_notified.recorded_at)
        .order_by(recorded_at_column)
    ).all()

    if not recent_entries:
        return True

    same_price_count = sum(
        1 for entry in recent_entries if abs(entry.price - history.price) < 1e-9
    )
    return len(recent_entries) > same_price_count


def should_send_price_alert(
    session: Session,
    *,
    product: Product,
    product_url: ProductURL,
    history: PriceHistory,
) -> bool:
    if product.notify_price is None and product.notify_percent is None:
        return False

    if not product_threshold_met(session, product=product, history=history):
        return False

    return url_price_changed_since_last_notification(
        session, product_url=product_url, history=history
    )


_service_factory: Callable[[], NotificationService] | None = None


def set_notification_service_factory(
    factory: Callable[[], NotificationService] | None,
) -> None:
    global _service_factory
    _service_factory = factory


def get_notification_service() -> NotificationService:
    if _service_factory is not None:
        return _service_factory()
    return NotificationService()


__all__ = [
    "NotificationService",
    "PriceAlertPayload",
    "set_notification_service_factory",
    "get_notification_service",
    "should_send_price_alert",
    "product_threshold_met",
    "url_price_changed_since_last_notification",
]
