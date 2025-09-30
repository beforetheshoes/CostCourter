from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

import httpx
import structlog
from sqlmodel import Session, select

from app.core.config import Settings, settings
from app.models import PriceHistory, Product, ProductURL, Store
from app.services.audit import record_audit_log
from app.services.notifications import (
    get_notification_service,
    should_send_price_alert,
)
from app.services.price_cache import rebuild_product_price_cache
from app.services.schedule_tracker import record_schedule_run
from app.services.scrape_utils import (
    extract_with_css,
    extract_with_regex,
    normalize_strategy_data,
    parse_strategy_selector,
)


class PriceFetcherConfigurationError(RuntimeError):
    """Raised when price fetching cannot proceed due to missing configuration."""


class HttpClient(Protocol):
    def __enter__(self) -> HttpClient: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None: ...

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: Any,
    ) -> Any: ...

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        timeout: Any,
    ) -> Any: ...


HttpClientFactory = Callable[[tuple[float, float]], HttpClient]


@dataclass(slots=True)
class PriceFetchResult:
    product_url_id: int
    success: bool
    price: float | None = None
    currency: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_url_id": self.product_url_id,
            "success": self.success,
            "price": self.price,
            "currency": self.currency,
            "reason": self.reason,
        }


@dataclass(slots=True)
class PriceFetchSummary:
    total_urls: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    results: list[PriceFetchResult] = field(default_factory=list)

    def merge(self, other: PriceFetchSummary) -> None:
        self.total_urls += other.total_urls
        self.successful_urls += other.successful_urls
        self.failed_urls += other.failed_urls
        self.results.extend(other.results)

    def add_result(self, result: PriceFetchResult) -> None:
        self.total_urls += 1
        if result.success:
            self.successful_urls += 1
        else:
            self.failed_urls += 1
        self.results.append(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_urls": self.total_urls,
            "successful_urls": self.successful_urls,
            "failed_urls": self.failed_urls,
            "results": [result.to_dict() for result in self.results],
        }


_logger = structlog.get_logger(__name__)


def _default_http_client_factory(timeout: tuple[float, float]) -> HttpClient:
    connect_timeout, request_timeout = timeout
    timeout_config = httpx.Timeout(request_timeout, connect=connect_timeout)
    return httpx.Client(timeout=timeout_config)


class PriceFetcherService:
    """Service responsible for orchestrating price fetches via the scraper API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._settings = settings or get_price_fetcher_settings()
        self._http_client_factory = http_client_factory or _default_http_client_factory
        self._timeout = (
            float(self._settings.scraper_connect_timeout),
            float(self._settings.scraper_request_timeout),
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    def fetch_price_for_url(
        self, session: Session, product_url_id: int
    ) -> PriceFetchResult:
        product_url = session.get(ProductURL, product_url_id)
        if product_url is None:
            raise ValueError("Product URL not found")

        request = self._build_scraper_request(session, product_url)

        data: dict[str, Any] | None = None
        fallback_used = False

        try:
            with self._http_client_factory(request.timeout) as client:
                response = client.post(
                    request.url,
                    json=request.payload,
                    timeout=httpx.Timeout(
                        request.timeout[1], connect=request.timeout[0]
                    ),
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else None
            if status_code == 404:
                _logger.info(
                    "price_fetch.scrape_endpoint_missing",
                    product_url_id=product_url_id,
                    url=request.url,
                )
                data = self._fetch_price_via_article(product_url, request)
                fallback_used = data is not None
            else:
                _logger.warning(
                    "price_fetch.http_error",
                    product_url_id=product_url_id,
                    error=str(exc),
                )
                return PriceFetchResult(
                    product_url_id=product_url_id,
                    success=False,
                    reason="http_error",
                )
        except httpx.HTTPError as exc:
            _logger.warning(
                "price_fetch.http_error",
                product_url_id=product_url_id,
                error=str(exc),
            )
            data = self._fetch_price_via_article(product_url, request)
            fallback_used = data is not None
        except Exception as exc:
            _logger.warning(
                "price_fetch.unexpected_error",
                product_url_id=product_url_id,
                error=str(exc),
            )
            return PriceFetchResult(
                product_url_id=product_url_id,
                success=False,
                reason="http_error",
            )
        else:
            payload = response.json()
            if payload.get("price") in (None, ""):
                fallback = self._fetch_price_via_article(product_url, request)
                if fallback is not None:
                    data = fallback
                    fallback_used = True
                else:
                    data = payload
            else:
                data = payload

        if data is None:
            return PriceFetchResult(
                product_url_id=product_url_id,
                success=False,
                reason="http_error",
            )

        price_raw = data.get("price")
        if price_raw in (None, ""):
            _logger.info(
                "price_fetch.missing_price",
                product_url_id=product_url_id,
            )
            return PriceFetchResult(
                product_url_id=product_url_id,
                success=False,
                reason="missing_price",
            )

        if fallback_used:
            _logger.info(
                "price_fetch.fallback_price",
                product_url_id=product_url_id,
            )

        try:
            price = self._coerce_price(price_raw)
        except (InvalidOperation, ValueError) as exc:
            _logger.warning(
                "price_fetch.invalid_price",
                product_url_id=product_url_id,
                raw_value=price_raw,
                error=str(exc),
            )
            return PriceFetchResult(
                product_url_id=product_url_id,
                success=False,
                reason="invalid_price",
            )

        currency = data.get("currency") or "USD"
        history = PriceHistory(
            product_id=product_url.product_id,
            product_url_id=product_url.id,
            price=price,
            currency=currency,
        )
        session.add(history)
        session.flush()
        product = session.get(Product, product_url.product_id)
        if product is not None:
            rebuild_product_price_cache(session, product)
            if should_send_price_alert(
                session,
                product=product,
                product_url=product_url,
                history=history,
            ):
                history.notified = True
                notification_service = get_notification_service()
                notification_service.send_price_alert(
                    session,
                    product=product,
                    product_url=product_url,
                    history=history,
                )
        session.commit()
        session.refresh(history)
        if product is not None:
            session.refresh(product)

        _logger.info(
            "price_fetch.success",
            product_url_id=product_url_id,
            price=price,
            currency=currency,
        )
        return PriceFetchResult(
            product_url_id=product_url_id,
            success=True,
            price=price,
            currency=currency,
        )

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
        product = session.get(Product, product_id)
        if product is None:
            raise ValueError("Product not found")

        if owner_id is not None and product.user_id != owner_id:
            _logger.info(
                "price_fetch.skip_wrong_owner",
                product_id=product_id,
                product_owner_id=product.user_id,
                requested_owner_id=owner_id,
            )
            return PriceFetchSummary()

        active_column = cast(Any, ProductURL.active)
        url_id_column = cast(Any, ProductURL.id)
        url_stmt = (
            select(ProductURL)
            .where(ProductURL.product_id == product.id)
            .where(active_column.is_(True))
            .order_by(url_id_column)
        )
        urls = list(session.exec(url_stmt))
        summary = PriceFetchSummary()

        for url in urls:
            if url.id is None:
                continue
            result = self.fetch_price_for_url(session, url.id)
            summary.add_result(result)
            if logging:
                _logger.info(
                    "price_fetch.result",
                    product_url_id=url.id,
                    success=result.success,
                    reason=result.reason,
                )

        if summary.failed_urls > 0:
            notification_service = get_notification_service()
            notification_service.notify_scrape_failure(
                session,
                product=product,
                summary=summary,
            )

        record_schedule_run(session, "pricing.update_product_prices")
        if audit_actor_id is not None:
            record_audit_log(
                session,
                action="pricing.refresh_product",
                actor_id=audit_actor_id,
                entity_type="product",
                entity_id=str(product_id),
                ip_address=audit_ip,
                context=summary.to_dict(),
            )
        return summary

    def update_all_products(
        self,
        session: Session,
        *,
        logging: bool = False,
        owner_id: int | None = None,
        audit_actor_id: int | None = None,
        audit_ip: str | None = None,
    ) -> PriceFetchSummary:
        product_active = cast(Any, Product.is_active)
        product_id_column = cast(Any, Product.id)
        owner_column = cast(Any, Product.user_id)
        product_stmt = (
            select(Product.id)
            .where(product_active.is_(True))
            .order_by(product_id_column)
        )
        if owner_id is not None:
            product_stmt = product_stmt.where(owner_column == owner_id)
        product_ids = [pid for pid in session.exec(product_stmt) if pid is not None]
        summary = PriceFetchSummary()

        for chunk in _chunk(product_ids, self._settings.price_fetch_chunk_size):
            for product_id in chunk:
                result = self.update_product_prices(
                    session,
                    product_id,
                    logging=logging,
                    owner_id=owner_id,
                    audit_actor_id=audit_actor_id,
                    audit_ip=audit_ip,
                )
                summary.merge(result)
        record_schedule_run(session, "pricing.update_all_products")
        if audit_actor_id is not None:
            context_payload = summary.to_dict()
            context_payload["product_ids"] = product_ids
            if owner_id is not None:
                context_payload["owner_id"] = owner_id
            record_audit_log(
                session,
                action="pricing.refresh_all",
                actor_id=audit_actor_id,
                entity_type="pricing",
                entity_id="all",
                ip_address=audit_ip,
                context=context_payload,
            )
        return summary

    @staticmethod
    def _coerce_price(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.replace(",", "").replace("$", "").strip()
            return float(Decimal(normalized))
        raise ValueError(f"Unsupported price type: {type(value)!r}")

    # ------------------------------------------------------------------
    # Scraper configuration helpers
    # ------------------------------------------------------------------

    def _build_scraper_request(
        self, session: Session, product_url: ProductURL
    ) -> _ScraperRequest:
        store: Store | None = None
        if product_url.store_id is not None:
            store = session.get(Store, product_url.store_id)

        base_url = (self._settings.scraper_base_url or "").strip()
        connect_timeout, request_timeout = self._timeout
        payload: dict[str, Any] = {"url": product_url.url}

        if store is not None:
            store_settings = getattr(store, "settings", {}) or {}
            scraper_service = (
                str(store_settings.get("scraper_service") or "").strip() or "http"
            )
            strategy = getattr(store, "scrape_strategy", {}) or {}

            overrides = self._parse_scraper_service_settings(
                store_settings.get("scraper_service_settings")
            )

            base_override = (
                overrides.pop("base_url", "")
                or overrides.pop("scraper_base_url", "")
                or overrides.pop("endpoint", "")
            ).strip()
            if base_override:
                base_url = base_override

            connect_override = (
                overrides.pop("connect_timeout", "")
                or overrides.pop("connect-timeout", "")
            ).strip()
            if connect_override:
                connect_timeout = self._safe_float(connect_override, connect_timeout)

            request_override = (
                overrides.pop("request_timeout", "")
                or overrides.pop("request-timeout", "")
            ).strip()
            if request_override:
                request_timeout = self._safe_float(request_override, request_timeout)

            extra_options: dict[str, Any] = {
                key: value
                for key, value in overrides.items()
                if value not in (None, "")
            }
            locale_settings = store_settings.get("locale_settings")
            if isinstance(locale_settings, dict) and locale_settings:
                extra_options.setdefault("locale_settings", locale_settings)

            if scraper_service and scraper_service != "http":
                payload["service"] = scraper_service
            if strategy:
                payload["strategy"] = strategy
            if extra_options:
                payload["options"] = extra_options

        if not base_url:
            slug = getattr(store, "slug", None)
            identifier = f" for store '{slug}'" if slug else ""
            raise PriceFetcherConfigurationError(
                f"SCRAPER_BASE_URL is not configured{identifier}"
            )

        endpoint = base_url.rstrip("/") + "/scrape"
        return _ScraperRequest(
            url=endpoint,
            payload=payload,
            timeout=(connect_timeout, request_timeout),
            base_url=base_url,
            store=store,
        )

    def _fetch_price_via_article(
        self, product_url: ProductURL, request: _ScraperRequest
    ) -> dict[str, Any] | None:
        if not request.base_url:
            return None
        endpoint = request.base_url.rstrip("/") + "/api/article"
        params = {
            "url": product_url.url,
            "full-content": "true",
            "cache": "false",
        }
        try:
            with self._http_client_factory(request.timeout) as client:
                response = client.get(
                    endpoint,
                    params=params,
                    timeout=httpx.Timeout(
                        request.timeout[1], connect=request.timeout[0]
                    ),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning(
                "price_fetch.fallback_http_error",
                product_url_id=product_url.id,
                error=str(exc),
            )
            return None
        except Exception as exc:
            _logger.warning(
                "price_fetch.fallback_unexpected_error",
                product_url_id=product_url.id,
                error=str(exc),
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None

        html = payload.get("fullContent") or payload.get("content")
        if not isinstance(html, str) or not html:
            return None

        store = request.store
        strategy = (
            getattr(store, "scrape_strategy", {}) if store is not None else {}
        ) or {}
        raw_price = self._extract_strategy_value(html, strategy, field="price")
        if raw_price is None:
            return None

        currency = payload.get("currency") or self._resolve_store_currency(store)
        return {"price": raw_price, "currency": currency}

    def _extract_strategy_value(
        self,
        html: str,
        strategy: dict[str, Any],
        *,
        field: str,
    ) -> str | None:
        entry = strategy.get(field)
        if not isinstance(entry, dict):
            return None
        entry_type = str(entry.get("type") or "").lower()
        value = entry.get("value")
        if not value:
            return None

        if entry_type == "css":
            selector, attr = parse_strategy_selector(str(value))
            if not selector:
                return None
            return extract_with_css(html, selector, attr, field)
        if entry_type == "regex":
            return extract_with_regex(html, str(value), field)
        if entry_type in {"scrape_api", "fallback"}:
            data_value = entry.get("data")
            if data_value in (None, ""):
                return None
            return normalize_strategy_data(field, str(data_value))
        return None

    def _resolve_store_currency(self, store: Store | None) -> str:
        if store is not None:
            if getattr(store, "currency", None):
                currency_value = str(store.currency).strip()
                if currency_value:
                    return currency_value.upper()
            settings_payload = getattr(store, "settings", {}) or {}
            if isinstance(settings_payload, dict):
                locale_settings = settings_payload.get("locale_settings")
                if isinstance(locale_settings, dict):
                    currency = locale_settings.get("currency")
                    if isinstance(currency, str) and currency.strip():
                        return currency.strip().upper()
        return "USD"

    @staticmethod
    def _parse_scraper_service_settings(raw: Any) -> dict[str, str]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return {str(key).strip(): str(value).strip() for key, value in raw.items()}
        if not isinstance(raw, str):
            return {}
        overrides: dict[str, str] = {}
        for line in raw.splitlines():
            cleaned = line.strip()
            if not cleaned or "=" not in cleaned:
                continue
            key, value = cleaned.split("=", 1)
            overrides[key.strip()] = value.strip()
        return overrides

    @staticmethod
    def _safe_float(value: str, fallback: float) -> float:
        try:
            return float(value)
        except ValueError:
            return fallback


def _chunk(values: Iterable[int], size: int) -> Iterable[list[int]]:
    chunk: list[int] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


_service_factory: Callable[[], PriceFetcherService] | None = None


def set_price_fetcher_service_factory(
    factory: Callable[[], PriceFetcherService] | None,
) -> None:
    global _service_factory
    _service_factory = factory


def get_price_fetcher_service() -> PriceFetcherService:
    if _service_factory is not None:
        return _service_factory()
    return PriceFetcherService()


def get_price_fetcher_settings() -> Settings:
    return settings


@dataclass(slots=True)
class _ScraperRequest:
    url: str
    payload: dict[str, Any]
    timeout: tuple[float, float]
    base_url: str
    store: Store | None
