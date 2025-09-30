from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import JSONDecodeError, loads
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import Settings, settings
from app.models import AppSetting, Product, ProductURL, SearchCache, Store, User
from app.models.base import utcnow
from app.schemas import SearchResponse, SearchResult

_logger = structlog.get_logger(__name__)

IGNORED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"}
MAX_ALLOWED_PAGES = 10
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_HEADERS = {
    "User-Agent": "CostCourter/1.0 (+https://costcourter.jez.me)",
    "X-Forwarded-For": "198.51.100.1",
    "X-Real-IP": "198.51.100.1",
}


class SearchConfigurationError(RuntimeError):
    """Raised when search cannot be performed due to missing configuration."""


class SearchExecutionError(RuntimeError):
    """Raised when the upstream search request fails."""


class HttpClient(Protocol):
    def __enter__(self) -> HttpClient: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None: ...

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        timeout: httpx.Timeout,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response: ...


HttpClientFactory = Callable[[httpx.Timeout], HttpClient]


@dataclass(slots=True)
class RawSearchResult:
    title: str | None
    url: str
    snippet: str | None
    thumbnail: str | None
    domain: str | None
    engine: str | None
    score: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "thumbnail": self.thumbnail,
            "domain": self.domain,
            "engine": self.engine,
            "score": self.score,
        }


@dataclass(slots=True)
class SearchIntegrationSettings:
    enabled: bool
    url: str | None
    prefix: str | None
    max_pages: int
    prune_days: int | None
    cache_ttl_seconds: int


def _default_http_client_factory(timeout: httpx.Timeout) -> HttpClient:
    return httpx.Client(timeout=timeout)


class SearxSearchService:
    """High-level orchestrator for SearXNG backed search with caching."""

    def __init__(
        self,
        *,
        settings_obj: Settings | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._settings = settings_obj or settings
        self._http_client_factory = http_client_factory or _default_http_client_factory
        self._timeout = DEFAULT_TIMEOUT

    def search(
        self,
        session: Session,
        *,
        query: str,
        owner: User,
        force_refresh: bool = False,
        max_pages: int | None = None,
    ) -> SearchResponse:
        normalized_query = query.strip()
        if not normalized_query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must not be empty",
            )
        if owner.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Requesting user must be persisted",
            )

        integration = self._resolve_settings(session)
        if not integration.enabled or not integration.url:
            raw_results = self._fallback_local_results(
                session,
                owner_id=owner.id,
                query=normalized_query,
                limit=25,
            )
            lookup = self._build_store_lookup(session, owner_id=owner.id)
            enriched_results = self._attach_store_matches(raw_results, lookup)
            extra_metadata = self._build_extra_metadata(raw_results)
            extra_metadata["fallback"] = "disabled"
            return SearchResponse(
                query=normalized_query,
                cache_hit=False,
                expires_at=None,
                results=enriched_results,
                extra=extra_metadata,
            )

        page_count = self._resolve_page_count(integration, max_pages)
        prepared_query = self._apply_prefix(normalized_query, integration.prefix)
        query_hash = self._hash_query(
            integration.url,
            prepared_query,
            page_count,
        )

        cached_results, cache_expiry = (None, None)
        if not force_refresh:
            cached = self._load_cache(session, query_hash)
            if cached is not None:
                cached_results, cache_expiry = cached

        fallback_used = False
        if cached_results is None:
            try:
                raw_results = self._fetch_results(
                    integration.url,
                    prepared_query,
                    page_count,
                )
                cache_expiry = self._persist_cache(
                    session,
                    query_hash,
                    prepared_query,
                    raw_results,
                    ttl_seconds=integration.cache_ttl_seconds,
                )
                cache_hit = False
            except SearchExecutionError:
                raw_results = self._fallback_local_results(
                    session,
                    owner_id=owner.id,
                    query=normalized_query,
                    limit=25,
                )
                cache_expiry = None
                cache_hit = False
                fallback_used = True
        else:
            raw_results = cached_results
            cache_hit = True

        lookup = self._build_store_lookup(session, owner_id=owner.id)
        enriched_results = self._attach_store_matches(raw_results, lookup)
        extra_metadata = self._build_extra_metadata(raw_results)
        if fallback_used:
            extra_metadata["fallback"] = "local-cache"

        return SearchResponse(
            query=prepared_query,
            cache_hit=cache_hit,
            expires_at=cache_expiry,
            results=enriched_results,
            extra=extra_metadata,
        )

    def _resolve_settings(self, session: Session) -> SearchIntegrationSettings:
        integration_settings = self._load_integration_settings(session)
        env_url = self._settings.searxng_url
        configured_url = integration_settings.get("url") or env_url

        enabled_value = integration_settings.get("enabled")
        if enabled_value is None:
            enabled = bool(configured_url)
        else:
            enabled = bool(enabled_value) and bool(configured_url)

        prefix = self._clean_string(integration_settings.get("search_prefix"))
        raw_max_pages = integration_settings.get("max_pages")
        if isinstance(raw_max_pages, str) and raw_max_pages.isdigit():
            raw_max_pages = int(raw_max_pages)
        max_pages = raw_max_pages if isinstance(raw_max_pages, int) else 1
        if max_pages < 1:
            max_pages = 1
        max_pages = min(max_pages, MAX_ALLOWED_PAGES)

        prune_days = integration_settings.get("prune_days")
        if isinstance(prune_days, str) and prune_days.isdigit():
            prune_days = int(prune_days)
        prune_days = (
            prune_days if isinstance(prune_days, int) and prune_days > 0 else None
        )

        ttl_seconds = max(self._settings.search_cache_ttl_seconds, 1)
        if prune_days:
            prune_seconds = prune_days * 86400
            ttl_seconds = min(ttl_seconds, prune_seconds)

        return SearchIntegrationSettings(
            enabled=enabled,
            url=configured_url,
            prefix=prefix,
            max_pages=max_pages,
            prune_days=prune_days,
            cache_ttl_seconds=ttl_seconds,
        )

    def _resolve_page_count(
        self, integration: SearchIntegrationSettings, override: int | None
    ) -> int:
        if override is None:
            return integration.max_pages or 1
        return max(1, min(override, MAX_ALLOWED_PAGES, integration.max_pages or 1))

    def _load_integration_settings(self, session: Session) -> dict[str, Any]:
        record = session.get(AppSetting, "integrated_services")
        if record is None or not record.value:
            return {}
        try:
            payload = loads(record.value)
        except (JSONDecodeError, TypeError):
            _logger.warning("search.invalid_integrated_services_payload")
            return {}
        if not isinstance(payload, dict):
            return {}
        searx_payload = payload.get("searxng", {})
        return searx_payload if isinstance(searx_payload, dict) else {}

    def _load_cache(
        self, session: Session, query_hash: str
    ) -> tuple[list[RawSearchResult], datetime] | None:
        statement = select(SearchCache).where(SearchCache.query_hash == query_hash)
        cached = session.exec(statement).first()
        if cached is None:
            return None
        expiry = self._normalize_datetime(cached.expires_at)
        if expiry <= utcnow():
            return None
        payload_raw = cached.response or {}
        payload = cast(dict[str, Any], payload_raw)
        results_raw = payload.get("results", [])
        if not isinstance(results_raw, list):
            return None
        raw_results: list[RawSearchResult] = []
        for item in results_raw:
            if not isinstance(item, dict):
                continue
            raw = self._raw_from_dict(item)
            if raw is not None:
                raw_results.append(raw)
        return raw_results, expiry

    def _persist_cache(
        self,
        session: Session,
        query_hash: str,
        prepared_query: str,
        raw_results: list[RawSearchResult],
        *,
        ttl_seconds: int,
    ) -> datetime:
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        payload: dict[str, object] = {
            "results": [result.as_dict() for result in raw_results]
        }

        statement = select(SearchCache).where(SearchCache.query_hash == query_hash)
        cached = session.exec(statement).first()
        if cached is None:
            cached = SearchCache(
                query_hash=query_hash,
                query=prepared_query,
                response=payload,
                expires_at=expires_at,
            )
            session.add(cached)
        else:
            cached.query = prepared_query
            cached.response = payload
            cached.expires_at = expires_at
        session.commit()
        return expires_at

    def _fetch_results(
        self,
        base_url: str,
        query: str,
        page_count: int,
    ) -> list[RawSearchResult]:
        url = base_url.rstrip("/")
        results: list[RawSearchResult] = []
        seen_urls: set[str] = set()
        try:
            with self._http_client_factory(self._timeout) as client:
                for page in range(1, page_count + 1):
                    params = {"format": "json", "q": query, "pageno": page}
                    response = client.get(
                        url,
                        params=params,
                        timeout=self._timeout,
                        headers=_DEFAULT_HEADERS,
                    )
                    response.raise_for_status()
                    data = response.json()
                    raw_items = (
                        data.get("results", []) if isinstance(data, dict) else []
                    )
                    for raw in raw_items:
                        normalized = self._normalize_result(raw)
                        if normalized is None:
                            continue
                        if normalized.url in seen_urls:
                            continue
                        seen_urls.add(normalized.url)
                        results.append(normalized)
        except httpx.HTTPError as exc:
            _logger.warning(
                "search.http_error",
                error=str(exc),
                url=url,
            )
            raise SearchExecutionError("Failed to query SearXNG") from exc
        except Exception as exc:  # pragma: no cover - defensive logging only
            _logger.exception("search.unexpected_error", error=str(exc))
            raise SearchExecutionError(
                "Unexpected error while querying SearXNG"
            ) from exc
        return results

    def _fallback_local_results(
        self,
        session: Session,
        *,
        owner_id: int,
        query: str,
        limit: int,
    ) -> list[RawSearchResult]:
        pattern = f"%{query.lower()}%"
        product_join = cast(Any, ProductURL.product_id == Product.id)
        store_join = cast(Any, ProductURL.store_id == Store.id)
        updated_at_column = cast(Any, Product.updated_at)
        statement = (
            select(ProductURL, Product, Store)
            .join(Product, product_join)
            .join(Store, store_join, isouter=True)
            .where(Product.user_id == owner_id)
            .where(
                func.lower(Product.name).like(pattern)
                | func.lower(Product.slug).like(pattern)
                | func.lower(ProductURL.url).like(pattern)
                | func.lower(func.coalesce(Store.name, "")).like(pattern)
            )
            .order_by(updated_at_column.desc())
            .limit(limit)
        )
        entries = session.exec(statement).all()
        results: list[RawSearchResult] = []
        for product_url, product, store in entries:
            url_value = str(product_url.url)
            snippet_parts: list[str] = []
            if store and store.name:
                snippet_parts.append(store.name)
            if product.description:
                snippet_parts.append(product.description)
            snippet = " • ".join(part for part in snippet_parts if part)
            results.append(
                RawSearchResult(
                    title=product.name,
                    url=url_value,
                    snippet=snippet or None,
                    thumbnail=None,
                    domain=self._canonical_domain(url_value),
                    engine="local",
                    score=None,
                )
            )
        return results

    def _normalize_result(self, raw: Any) -> RawSearchResult | None:
        if not isinstance(raw, dict):
            return None
        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            return None
        url = url.strip()
        if self._has_ignored_extension(url):
            return None

        domain = self._canonical_domain(url)
        title = self._clean_string(raw.get("title"))
        snippet = self._clean_string(raw.get("content") or raw.get("snippet"))
        thumbnail_raw = raw.get("thumbnail") or raw.get("img_src")
        thumbnail = (
            thumbnail_raw.strip()
            if isinstance(thumbnail_raw, str) and thumbnail_raw.strip()
            else None
        )
        engine = self._clean_string(raw.get("engine"))
        score = self._coerce_optional_float(raw.get("score"))

        return RawSearchResult(
            title=title,
            url=url,
            snippet=snippet,
            thumbnail=thumbnail,
            domain=domain,
            engine=engine,
            score=score,
        )

    def _raw_from_dict(self, payload: dict[str, Any]) -> RawSearchResult | None:
        url = payload.get("url")
        if not isinstance(url, str):
            return None
        return RawSearchResult(
            title=self._clean_string(payload.get("title")),
            url=url,
            snippet=self._clean_string(payload.get("snippet")),
            thumbnail=self._clean_string(payload.get("thumbnail")),
            domain=self._clean_string(payload.get("domain")),
            engine=self._clean_string(payload.get("engine")),
            score=self._coerce_optional_float(payload.get("score")),
        )

    def _attach_store_matches(
        self,
        raw_results: list[RawSearchResult],
        store_lookup: dict[str, tuple[int, str]],
    ) -> list[SearchResult]:
        enriched: list[SearchResult] = []
        for index, raw in enumerate(raw_results):
            domain = raw.domain if raw.domain else self._canonical_domain(raw.url)
            store_info = store_lookup.get(domain)
            store_id = store_name = None
            if store_info is None and domain.startswith("www."):
                store_info = store_lookup.get(domain[4:])
            if store_info is not None:
                store_id, store_name = store_info
            enriched.append(
                SearchResult(
                    title=raw.title,
                    url=raw.url,
                    snippet=raw.snippet,
                    thumbnail=raw.thumbnail,
                    domain=domain,
                    relevance=index,
                    engine=raw.engine,
                    score=raw.score,
                    store_id=store_id,
                    store_name=store_name,
                )
            )
        return enriched

    def _build_store_lookup(
        self, session: Session, *, owner_id: int
    ) -> dict[str, tuple[int, str]]:
        lookup: dict[str, tuple[int, str]] = {}
        stores = session.exec(select(Store).where(Store.user_id == owner_id)).all()
        for store in stores:
            if store.id is None or not isinstance(store.domains, Iterable):
                continue
            for entry in store.domains:
                domain = None
                if isinstance(entry, dict):
                    domain_value = entry.get("domain")
                    domain = domain_value if isinstance(domain_value, str) else None
                elif isinstance(entry, str):
                    domain = entry
                if not domain:
                    continue
                canonical = self._canonical_domain(domain)
                if not canonical:
                    continue
                lookup[canonical] = (store.id, store.name)
                if not canonical.startswith("www."):
                    lookup[f"www.{canonical}"] = (store.id, store.name)
        return lookup

    def _build_extra_metadata(
        self, raw_results: list[RawSearchResult]
    ) -> dict[str, Any]:
        engines = Counter(result.engine for result in raw_results if result.engine)
        return {"engines": dict(engines)}

    def _apply_prefix(self, query: str, prefix: str | None) -> str:
        if not prefix:
            return query
        return f"{prefix.strip()} {query}".strip()

    def _hash_query(self, base_url: str, query: str, page_count: int) -> str:
        key = f"{base_url.lower()}|{page_count}|{query.lower()}"
        return sha256(key.encode("utf-8", errors="ignore")).hexdigest()

    def _clean_string(self, value: Any) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return None

    def _coerce_optional_float(self, value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _has_ignored_extension(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path or ""
        if "." not in path:
            return False
        extension = path.rsplit(".", 1)[1].lower()
        return extension in IGNORED_EXTENSIONS

    def _canonical_domain(self, url_or_domain: str) -> str:
        candidate = url_or_domain.strip().lower()
        parsed = urlparse(
            candidate if "://" in candidate else f"//{candidate}", scheme=""
        )
        domain = parsed.netloc or parsed.path
        if not domain:
            return ""
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        try:
            return domain.encode("idna").decode("ascii")
        except UnicodeError:
            return domain

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = ["SearxSearchService", "SearchConfigurationError", "SearchExecutionError"]
