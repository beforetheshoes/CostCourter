from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from fastapi import HTTPException, status
from pydantic import HttpUrl, ValidationError
from pydantic.type_adapter import TypeAdapter
from sqlmodel import Session, select

from app.models import Product, Store, User
from app.schemas import (
    PriceHistoryCreate,
    ProductCreate,
    ProductURLCreate,
    StoreCreate,
    StoreDomain,
    StoreStrategyField,
)
from app.services import catalog
from app.services.audit import record_audit_log
from app.services.scrape_utils import (
    extract_element_value,
    normalize_strategy_data,
    parse_strategy_selector,
)

HttpClientFactory = Callable[[], httpx.Client]
PriceRefreshCallback = Callable[[int], None]

_HTTP_URL = TypeAdapter(HttpUrl)
HTTP_URL_ADAPTER = _HTTP_URL

_FALLBACK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_FALLBACK_TIMEOUT = httpx.Timeout(15.0, connect=7.0)
_SCRAPER_TIMEOUT = httpx.Timeout(45.0, connect=15.0)
_SCRAPER_ENDPOINT = "/api/article"


_AUTO_CREATE_STRATEGIES: dict[str, dict[str, list[str]]] = {
    "title": {
        "selectors": [
            'meta[property="og:title"]|content',
            'meta[name="og:title"]|content',
            'meta[name="twitter:title"]|content',
            'meta[name="title"]|content',
            "title",
            "h1",
            '[itemprop="name"]',
            "#productTitle",
            ".product-title",
            '[class*="product-title"]',
        ],
        "regex": [
            r'id=["\']productTitle["\'][^>]*>([^<]+)<',
        ],
    },
    "price": {
        "selectors": [
            'meta[property="product:price:amount"]|content',
            'meta[property="og:price:amount"]|content',
            'meta[name="price"]|content',
            '[itemprop="price"]|content',
            ".a-price .a-offscreen",
            "span.a-offscreen",
            ".price",
            ".product-price",
            ".product-price-value",
            'span[data-selenium="pricingPrice"]',
            'span[data-selenium="pricingSalePrice"]',
            'span[data-selenium="pricingCurrentPrice"]',
            "span.price__value",
            '[class^="price"]',
            '[class*="price"]',
            "[data-price]",
        ],
        "regex": [
            r'"price"\s*:\s*"([^\"]+?)"',
            r">\s*[€£$]\s*([0-9][0-9.,]*)<",
            r"[€£$]\s*([0-9][0-9.,]*)",
            r'data-selenium="pricing(?:Sale|Current)?Price"[^>]*>\s*[€£$]?\s*([0-9][0-9.,]*)',
        ],
    },
    "image": {
        "selectors": [
            'meta[property="og:image"]|content',
            'meta[property="og:image:secure_url"]|content',
            'meta[name="og:image"]|content',
            'meta[name="twitter:image"]|content',
            'meta[name="twitter:image:src"]|content',
            'meta[itemprop="image"]|content',
            'img[itemprop="image"]|src',
            'link[rel="image_src"]|href',
            "img.product-image::attr(src)",
            'img[data-testid="product-image"]|src',
        ],
        "regex": [
            r'"hiRes"\s*:\s*"(.+?)"',
            r'"image"\s*:\s*"(.+?\.(?:jpe?g|png|webp))"',
        ],
    },
}


@dataclass(slots=True)
class QuickAddResult:
    product_id: int
    product_url_id: int
    store_id: int
    title: str
    price: Any
    currency: str
    image: str | None
    warnings: list[str]


@dataclass(slots=True)
class StoreQuickAddResult:
    store: Store
    warnings: list[str]
    created: bool


def _append_warning(messages: list[str] | None, message: str) -> None:
    if messages is None:
        return
    if message not in messages:
        messages.append(message)


def _slugify(value: str) -> str:
    import re

    v = value.lower()
    v = re.sub(r"[^a-z0-9]+", "-", v).strip("-")
    return v or "item"


def _normalise_host(value: str) -> str:
    host = value.strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    return host


def _derive_store_slug(host: str) -> str:
    canonical = _normalise_host(host)
    if canonical.startswith("www."):
        canonical = canonical[4:]
    slug_source = canonical.replace(".", "-")
    return _slugify(slug_source)


def _derive_store_name(host: str) -> str:
    canonical = _normalise_host(host)
    if canonical.startswith("www."):
        canonical = canonical[4:]
    if "." in canonical:
        canonical = canonical.split(".", 1)[0]
    friendly = canonical.replace("-", " ").strip()
    if friendly:
        return friendly.title()
    return host.title()


def _build_store_domains(host: str) -> list[StoreDomain]:
    canonical = host.lower()
    if canonical.startswith("www."):
        canonical = canonical[4:]
    raw_domains = [canonical]
    alt = f"www.{canonical}" if canonical else None
    if alt:
        raw_domains.append(alt)

    seen: set[str] = set()
    domains: list[StoreDomain] = []
    for domain in raw_domains:
        if not domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(StoreDomain(domain=domain))
    return domains


def _merge_store_domains(store: Store, host: str) -> bool:
    entries = getattr(store, "domains", []) or []
    seen = {
        str(entry.get("domain")).lower()
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("domain"), str)
    }
    changed = False
    for domain in _build_store_domains(host):
        key = domain.domain.lower()
        if key in seen:
            continue
        entries.append(domain.model_dump())
        seen.add(key)
        changed = True
    if changed:
        store.domains = entries
    return changed


def _detect_with_selectors(
    soup: BeautifulSoup, selectors: list[str], field: str
) -> StoreStrategyField | None:
    for raw in selectors:
        css, attr = parse_strategy_selector(raw)
        if not css:
            continue
        try:
            nodes = soup.select(css)
        except Exception:
            continue
        if not nodes:
            continue
        for node in nodes:
            if not isinstance(node, Tag):
                continue
            extracted = extract_element_value(node, attr)
            normalized = normalize_strategy_data(field, extracted)
            if normalized is None:
                continue
            return StoreStrategyField(type="css", value=raw, data=normalized)
    return None


def _detect_with_regex(
    html: str, patterns: list[str], field: str
) -> StoreStrategyField | None:
    for pattern in patterns:
        try:
            match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        except re.error:
            continue
        if not match:
            continue
        extracted = match.group(1)
        normalized = normalize_strategy_data(field, extracted)
        if normalized is None:
            continue
        return StoreStrategyField(type="regex", value=pattern, data=normalized)
    return None


def _auto_detect_strategy_fields(html: str) -> dict[str, StoreStrategyField]:
    soup = BeautifulSoup(html, "html.parser") if html else None
    detected: dict[str, StoreStrategyField] = {}
    for field, config in _AUTO_CREATE_STRATEGIES.items():
        selectors = config.get("selectors", [])
        regexes = config.get("regex", [])
        candidate: StoreStrategyField | None = None
        if soup is not None:
            candidate = _detect_with_selectors(soup, selectors, field)
        if candidate is None:
            candidate = _detect_with_regex(html, regexes, field)
        if candidate is not None:
            detected[field] = candidate
    return detected


def _has_metadata_fields(payload: dict[str, Any]) -> bool:
    for key in ("title", "description", "price", "currency", "image"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if value not in (None, "") and not isinstance(value, str):
            return True
    return False


def _build_scrape_strategy(
    meta: dict[str, Any], *, fallback_title: str
) -> dict[str, StoreStrategyField]:
    strategy: dict[str, StoreStrategyField] = {}
    defaults: dict[str, tuple[str | None, str]] = {
        "title": (fallback_title, "title"),
        "price": (None, "price"),
        "image": (None, "image"),
    }
    raw_html = meta.get("raw_html") or meta.get("_raw_html") or ""
    detected = _auto_detect_strategy_fields(str(raw_html)) if raw_html else {}
    for key, (fallback, meta_key) in defaults.items():
        candidate = detected.get(key)
        if candidate is not None:
            strategy[key] = candidate
            continue
        raw_value = meta.get(meta_key)
        if raw_value not in (None, ""):
            value = raw_value if isinstance(raw_value, str) else str(raw_value)
            strategy[key] = StoreStrategyField(
                type="scrape_api",
                value="payload",
                data=value.strip(),
            )
            continue
        strategy[key] = StoreStrategyField(
            type="fallback",
            value="inferred",
            data=fallback,
        )
    return strategy


def _build_store_settings(
    *, product_url: str, currency: str | None, locale: str | None
) -> dict[str, Any]:
    normalized_currency = (currency or "USD").upper()
    resolved_locale = (locale or "en_US").strip() or "en_US"
    return {
        "scraper_service": "http",
        "scraper_service_settings": "",
        "test_url": product_url,
        "locale_settings": {
            "locale": resolved_locale,
            "currency": normalized_currency,
        },
    }


def _coerce_price(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace(",", "").replace("$", "").strip()
        return float(Decimal(normalized))
    raise ValueError(f"Unsupported price type: {type(value)!r}")


def fetch_url_metadata(
    url: str,
    scraper_base_url: str | None,
    http_client_factory: HttpClientFactory | None,
    *,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    client_factory: Callable[[], httpx.Client]
    if http_client_factory is not None:
        client_factory = http_client_factory
    else:

        def _default_client_factory() -> httpx.Client:
            return httpx.Client(follow_redirects=True)

        client_factory = _default_client_factory

    if scraper_base_url:
        scraper_payload = _fetch_metadata_via_scraper(
            scraper_base_url, url, client_factory, diagnostics=diagnostics
        )
        if scraper_payload:
            return scraper_payload

    fallback = _fetch_metadata_via_http(url, client_factory, diagnostics=diagnostics)
    if fallback:
        if not _has_metadata_fields(fallback):
            _append_warning(
                diagnostics,
                "No metadata could be retrieved for the provided URL; using defaults.",
            )
        return fallback
    _append_warning(
        diagnostics,
        "No metadata could be retrieved for the provided URL; using defaults.",
    )
    return {}


def _fetch_metadata_via_scraper(
    base_url: str,
    target_url: str,
    client_factory: Callable[[], httpx.Client],
    *,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + _SCRAPER_ENDPOINT
    params = {
        "url": target_url,
        "full-content": "true",
        "cache": "false",
    }
    try:
        with client_factory() as client:
            response = client.get(endpoint, params=params, timeout=_SCRAPER_TIMEOUT)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        _append_warning(
            diagnostics,
            "Scraper request timed out; falling back to direct HTML parsing.",
        )
        return {}
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else "error"
        _append_warning(
            diagnostics,
            f"Scraper responded with HTTP {status_code}; falling back to HTML metadata.",
        )
        return {}
    except httpx.HTTPError as exc:
        _append_warning(
            diagnostics,
            f"Scraper request failed ({exc.__class__.__name__}); using fallback metadata.",
        )
        return {}
    except Exception:
        _append_warning(
            diagnostics,
            "Unexpected scraper error occurred; using fallback metadata.",
        )
        return {}

    if not isinstance(data, dict):
        _append_warning(
            diagnostics,
            "Scraper returned an unexpected payload; ignoring response.",
        )
        return {}
    parsed = _parse_scraper_payload(target_url, data)
    if not parsed:
        _append_warning(
            diagnostics,
            "Scraper payload lacked metadata; attempting HTML fallback.",
        )
    return parsed


class _MetadataHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self._title_chunks: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            content = attrs_dict.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            text = data.strip()
            if text:
                self._title_chunks.append(text)

    def get_title(self) -> str | None:
        for chunk in self._title_chunks:
            if chunk:
                return chunk
        return None


def _parse_html_metadata(html: str) -> dict[str, Any]:
    parser = _MetadataHTMLParser()
    parser.feed(html)
    parser.close()
    meta = parser.meta

    title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or meta.get("title")
        or parser.get_title()
    )
    image = meta.get("og:image") or meta.get("twitter:image")
    description = meta.get("og:description") or meta.get("description")
    price = (
        meta.get("product:price:amount")
        or meta.get("og:price:amount")
        or meta.get("price")
    )
    currency = (
        meta.get("product:price:currency")
        or meta.get("og:price:currency")
        or meta.get("price:currency")
    )

    payload: dict[str, Any] = {}
    if title:
        payload["title"] = title.strip()
    if image:
        payload["image"] = image.strip()
    if description:
        payload["description"] = description.strip()
    if price:
        payload["price"] = price.strip()
    if currency:
        payload["currency"] = currency.strip().upper()
    payload["raw_html"] = html
    return payload


def _fetch_metadata_via_http(
    url: str,
    client_factory: Callable[[], httpx.Client],
    *,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    try:
        with client_factory() as client:
            client.headers.update(_FALLBACK_HEADERS)
            response = client.get(url, timeout=_FALLBACK_TIMEOUT)
            response.raise_for_status()
    except httpx.TimeoutException:
        _append_warning(
            diagnostics,
            "Direct fetch timed out; metadata may be incomplete.",
        )
        return {}
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else "error"
        _append_warning(
            diagnostics,
            f"Direct fetch returned HTTP {status_code}; metadata unavailable.",
        )
        return {}
    except httpx.HTTPError as exc:
        _append_warning(
            diagnostics,
            f"Direct metadata fetch failed ({exc.__class__.__name__}).",
        )
        return {}
    except Exception:
        _append_warning(
            diagnostics,
            "Unexpected error during direct metadata fetch.",
        )
        return {}

    payload = _parse_html_metadata(response.text)
    if not _has_metadata_fields(payload):
        _append_warning(
            diagnostics,
            "No HTML metadata discovered in page content.",
        )
    return payload


def _parse_scraper_payload(target_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = (payload.get("title") or "").strip()
    description = (payload.get("excerpt") or "").strip()
    locale = (payload.get("lang") or "").strip()
    html_raw = payload.get("fullContent") or payload.get("content") or ""
    html = html_raw if isinstance(html_raw, str) else str(html_raw)

    image = None
    price = None
    currency = None

    meta = payload.get("meta") or {}

    parsed_target = urlparse(target_url)
    base_scheme = parsed_target.scheme or "https"
    base_root = (
        f"{base_scheme}://{parsed_target.netloc}"
        if parsed_target.netloc
        else target_url
    )

    def _normalize_image(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.startswith(("http://", "https://", "data:")):
            return candidate
        if candidate.startswith("//"):
            return f"{base_scheme}:{candidate}"
        if candidate.startswith(("./", "../")):
            return urljoin(target_url, candidate)
        if candidate.startswith("/"):
            return urljoin(base_root, candidate)
        return candidate

    if isinstance(meta, dict):
        for candidate in (
            meta.get("og:image:secure_url"),
            meta.get("og:image"),
            meta.get("og:image:url"),
            meta.get("twitter:image"),
            meta.get("twitter:image:src"),
        ):
            normalized = _normalize_image(candidate)
            if normalized:
                image = normalized
                break
        price = (
            meta.get("product:price:amount")
            or meta.get("og:price:amount")
            or meta.get("price")
        )
        currency = (
            meta.get("product:price:currency")
            or meta.get("og:price:currency")
            or meta.get("price:currency")
        )

    if html:
        if not image:
            html_image = _first_match(
                html,
                r'"hiRes"\s*:\s*"(https:[^"\\]+)"',
                r'id="landingImage"[^>]*data-old-hires="([^"]+)"',
                r'id="landingImage"[^>]*src="([^"]+)"',
            )
            if html_image:
                normalized_html_image = _normalize_image(html_image)
                if normalized_html_image:
                    image = normalized_html_image
        if not price:
            price = _first_match(
                html,
                r'class="a-offscreen">\$([0-9][0-9.,]*)',
                r'data-a-color="price"[^>]*>\s*<span[^>]*class="a-offscreen">\$([0-9][0-9.,]*)',
                r'data-selenium="pricing(?:Sale|Current)?Price"[^>]*>\s*[€£$]?\s*([0-9][0-9.,]*)',
                r'class="price__value"[^>]*>\s*[€£$]?\s*([0-9][0-9.,]*)',
                r'rf-pdp-currentprice"[^>]*>\s*[€£$]?\s*([0-9][0-9.,]*)',
            )
        if not price or not currency:
            ld_price, ld_currency = _extract_price_currency_from_ld_json(html)
            if not price and ld_price is not None:
                price = ld_price
            if not currency and ld_currency is not None:
                currency = ld_currency
        if not title:
            extracted_title = _first_match(html, r'id="productTitle"[^>]*>([^<]+)')
            if extracted_title:
                title = extracted_title.strip()

    result: dict[str, Any] = {}
    if title:
        result["title"] = title
    if description:
        result["description"] = description
    if image:
        result["image"] = image.strip()
    if price:
        result["price"] = price.strip()
    if currency:
        result["currency"] = currency.strip().upper()
    if locale:
        result["locale"] = locale

    if not result.get("currency") and "amazon." in target_url:
        result["currency"] = "USD"

    result["raw_html"] = html

    return result


def _first_match(html: str, *patterns: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_price_currency_from_ld_json(html: str) -> tuple[str | None, str | None]:
    if not html:
        return None, None
    matches = re.findall(
        r'<script[^>]+type\s*=\s*["\"]application/ld\+json["\"][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for raw in matches:
        raw_data = raw.strip()
        if not raw_data:
            continue
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            continue
        price, currency = _walk_ld_nodes_for_price(data)
        if price or currency:
            normalized_price = str(price).strip() if price is not None else None
            normalized_currency = (
                str(currency).strip().upper() if currency is not None else None
            )
            return normalized_price, normalized_currency
    return None, None


def _walk_ld_nodes_for_price(data: Any) -> tuple[Any | None, Any | None]:
    if isinstance(data, dict):
        if "price" in data or "priceCurrency" in data or "currency" in data:
            price = data.get("price")
            currency = data.get("priceCurrency") or data.get("currency")
            if price is not None or currency is not None:
                return price, currency
        offers = data.get("offers")
        if offers is not None:
            price, currency = _walk_ld_nodes_for_price(offers)
            if price is not None or currency is not None:
                return price, currency
        for value in data.values():
            price, currency = _walk_ld_nodes_for_price(value)
            if price is not None or currency is not None:
                return price, currency
    elif isinstance(data, list):
        for item in data:
            price, currency = _walk_ld_nodes_for_price(item)
            if price is not None or currency is not None:
                return price, currency
    return None, None


def ensure_store_for_owner(
    session: Session,
    owner: User,
    *,
    host: str,
    store_slug: str,
    product_url: str,
    strategy: dict[str, StoreStrategyField],
    website_url: HttpUrl | None,
    currency: str,
    locale: str,
) -> Store:
    statement = (
        select(Store).where(Store.slug == store_slug).where(Store.user_id == owner.id)
    )
    existing_store = session.exec(statement).first()
    if existing_store is None:
        store_domains = _build_store_domains(host)
        created = catalog.create_store(
            session,
            payload=StoreCreate(
                name=_derive_store_name(host),
                slug=store_slug,
                website_url=website_url,
                active=True,
                domains=store_domains,
                scrape_strategy=strategy,
                settings=_build_store_settings(
                    product_url=product_url, currency=currency, locale=locale
                ),
                locale=locale,
                currency=currency,
            ),
            owner=owner,
        )
        store_instance = session.get(Store, created.id)
        if store_instance is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load created store",
            )
        return store_instance

    updated = _merge_store_domains(existing_store, host)
    if not existing_store.scrape_strategy:
        existing_store.scrape_strategy = {
            key: value.model_dump() for key, value in strategy.items()
        }
        updated = True
    if not existing_store.settings:
        existing_store.settings = _build_store_settings(
            product_url=product_url, currency=currency, locale=locale
        )
        updated = True
    else:
        settings_payload = dict(existing_store.settings)
        locale_settings = dict(settings_payload.get("locale_settings") or {})
        settings_changed = False
        if locale and not locale_settings.get("locale"):
            locale_settings["locale"] = locale
            settings_changed = True
        if currency and not locale_settings.get("currency"):
            locale_settings["currency"] = currency
            settings_changed = True
        if not settings_payload.get("test_url"):
            settings_payload["test_url"] = product_url
            settings_changed = True
        if settings_changed:
            settings_payload["locale_settings"] = locale_settings
            existing_store.settings = settings_payload
            updated = True
    if website_url and not getattr(existing_store, "website_url", None):
        existing_store.website_url = str(website_url)
        updated = True
    if locale and not getattr(existing_store, "locale", None):
        existing_store.locale = locale
        updated = True
    if currency and not getattr(existing_store, "currency", None):
        existing_store.currency = currency
        updated = True
    if updated:
        session.add(existing_store)
        session.commit()
        session.refresh(existing_store)
    return existing_store


def quick_add_store(
    session: Session,
    *,
    owner: User,
    website: str,
    scraper_base_url: str | None,
    http_client_factory: HttpClientFactory | None = None,
    currency: str | None = None,
    locale: str | None = None,
) -> StoreQuickAddResult:
    if owner.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user is missing an identifier",
        )

    raw_input = (website or "").strip()
    if not raw_input:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Website must be provided",
        )

    seed_url = raw_input if "://" in raw_input else f"https://{raw_input}"
    parsed = urlparse(seed_url)
    host = parsed.hostname
    if not host:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to determine hostname from website",
        )
    if not parsed.scheme:
        seed_url = f"https://{host}"

    warnings: list[str] = []
    try:
        website_url: HttpUrl | None = _HTTP_URL.validate_python(seed_url)
    except ValidationError:
        website_url = None
        _append_warning(
            warnings,
            f"Could not normalise website URL '{seed_url}' for store metadata.",
        )

    meta = fetch_url_metadata(
        seed_url,
        scraper_base_url,
        http_client_factory,
        diagnostics=warnings,
    )

    display_name = (
        meta.get("site_name") or meta.get("title") or ""
    ).strip() or _derive_store_name(host)
    slug = _derive_store_slug(host)

    metadata_currency = meta.get("currency")
    resolved_currency: str | None = None
    for candidate in (currency, metadata_currency):
        if isinstance(candidate, str) and candidate.strip():
            resolved_currency = candidate.strip().upper()
            break
    if resolved_currency is None:
        resolved_currency = "USD"

    metadata_locale = meta.get("locale")
    resolved_locale: str | None = None
    for candidate in (locale, metadata_locale):
        if isinstance(candidate, str) and candidate.strip():
            resolved_locale = candidate.strip()
            break
    if resolved_locale is None:
        resolved_locale = "en_US"

    strategy = _build_scrape_strategy(meta, fallback_title=display_name)

    existing_stmt = (
        select(Store).where(Store.slug == slug).where(Store.user_id == owner.id)
    )
    existing_store = session.exec(existing_stmt).first()

    store = ensure_store_for_owner(
        session,
        owner,
        host=host,
        store_slug=slug,
        product_url=seed_url,
        strategy=strategy,
        website_url=website_url,
        currency=resolved_currency,
        locale=resolved_locale,
    )

    default_name = _derive_store_name(host)
    created = existing_store is None
    if (
        display_name
        and display_name != store.name
        and (created or store.name == default_name)
    ):
        store.name = display_name
        session.add(store)
        session.commit()
        session.refresh(store)

    return StoreQuickAddResult(store=store, warnings=warnings, created=created)


def quick_add_product(
    session: Session,
    *,
    owner: User,
    url: str,
    scraper_base_url: str | None,
    price_refresh: PriceRefreshCallback | None = None,
    http_client_factory: HttpClientFactory | None = None,
    audit_ip: str | None = None,
) -> QuickAddResult:
    if owner.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user is missing an identifier",
        )

    parsed = urlparse(url)
    host = parsed.hostname or "store"
    store_slug = _derive_store_slug(host)
    website = f"{parsed.scheme or 'https'}://{host}"
    warnings: list[str] = []
    try:
        website_url: HttpUrl | None = _HTTP_URL.validate_python(website)
    except ValidationError:
        website_url = None
        _append_warning(
            warnings,
            f"Could not normalise website URL '{website}' for store metadata.",
        )

    meta = fetch_url_metadata(
        url,
        scraper_base_url,
        http_client_factory,
        diagnostics=warnings,
    )

    title = (meta.get("title") or "").strip() or host
    if not meta.get("title"):
        _append_warning(
            warnings,
            "Metadata did not include a title; using hostname as fallback.",
        )
    product_slug = _slugify(title)
    currency = (meta.get("currency") or "USD").upper()
    locale = (meta.get("locale") or "en_US").strip() or "en_US"
    scrape_strategy = _build_scrape_strategy(meta, fallback_title=title)
    store = ensure_store_for_owner(
        session,
        owner,
        host=host,
        store_slug=store_slug,
        product_url=url,
        strategy=scrape_strategy,
        website_url=website_url,
        currency=currency,
        locale=locale,
    )

    existing_product = session.exec(
        select(Product)
        .where(Product.slug == product_slug)
        .where(Product.user_id == owner.id)
    ).first()
    if existing_product is None:
        product = catalog.create_product(
            session,
            payload=ProductCreate(
                name=title,
                slug=product_slug,
                description=None,
                is_active=True,
            ),
            owner=owner,
        )
        existing_product = session.get(Product, product.id)
        if existing_product is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load created product",
            )
    else:
        if existing_product.user_id != owner.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Product slug is already used by another user",
            )
    if store.id is None or existing_product.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing identifiers for store or product",
        )

    updated_product = False
    if not existing_product.favourite:
        existing_product.favourite = True
        updated_product = True
        _append_warning(
            warnings,
            "Product favourite flag restored for this owner.",
        )
    if not existing_product.is_active:
        existing_product.is_active = True
        updated_product = True
        _append_warning(
            warnings,
            "Product was inactive and has been reactivated.",
        )
    if updated_product:
        session.add(existing_product)
        session.commit()
        session.refresh(existing_product)

    image_url = meta.get("image") or meta.get("image_url")
    if image_url and existing_product.image_url != image_url:
        existing_product.image_url = str(image_url)
        session.add(existing_product)
        session.commit()
        session.refresh(existing_product)
    image_value = image_url or existing_product.image_url

    url_read = catalog.create_product_url(
        session,
        payload=ProductURLCreate(
            product_id=existing_product.id,
            store_id=store.id,
            url=_HTTP_URL.validate_python(url),
            is_primary=True,
            active=True,
        ),
        owner=owner,
    )
    if url_read.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Product URL creation failed",
        )

    price = meta.get("price")
    captured_price: float | None = None
    if price not in (None, "") and url_read.id is not None:
        try:
            coerced = _coerce_price(price)
            catalog.create_price_history(
                session,
                payload=PriceHistoryCreate(
                    product_id=existing_product.id,
                    product_url_id=url_read.id,
                    price=coerced,
                    currency=currency,
                ),
                owner=owner,
            )
            captured_price = coerced
        except Exception:
            _append_warning(
                warnings,
                "Scraped price could not be parsed; skipped seeding price history.",
            )
            pass

    if price_refresh is not None:
        try:
            price_refresh(existing_product.id)
        except Exception:
            _append_warning(
                warnings,
                "Failed to enqueue price refresh; consider triggering manually.",
            )
            pass

    record_audit_log(
        session,
        action="product.quick_add",
        actor_id=owner.id,
        entity_type="product",
        entity_id=str(existing_product.id),
        ip_address=audit_ip,
        context={
            "product_url_id": url_read.id,
            "store_id": store.id,
            "source_url": str(url),
            "title": title,
            "price_observed": captured_price,
            "currency": currency,
            "warnings": list(warnings),
        },
    )

    return QuickAddResult(
        product_id=existing_product.id,
        product_url_id=url_read.id,
        store_id=store.id,
        title=title,
        price=price,
        currency=currency,
        image=str(image_value) if image_value else None,
        warnings=list(warnings),
    )


__all__ = [
    "QuickAddResult",
    "fetch_url_metadata",
    "ensure_store_for_owner",
    "quick_add_product",
    "HTTP_URL_ADAPTER",
]
