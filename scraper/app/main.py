from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    async_playwright,
)

LOGGER = logging.getLogger("costcourter.scraper")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-CH-UA": '"Google Chrome";v="128", "Chromium";v="128", "Not=A?Brand";v="24"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass(slots=True)
class BrowserPool:
    playwright: Playwright | None = None
    browser: Browser | None = None

    async def startup(self) -> None:
        if self.playwright is not None:
            return
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-features=IsolateOrigins,site-per-process",
                "--ignore-certificate-errors",
                "--window-size=1280,720",
            ],
        )

    async def shutdown(self) -> None:
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None

    @asynccontextmanager
    async def context(self, *, storage_state: dict[str, Any] | None = None) -> BrowserContext:
        if self.browser is None:
            raise RuntimeError("Browser not initialised")
        context = await self.browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
            extra_http_headers=DEFAULT_HEADERS,
            storage_state=storage_state,
        )
        try:
            yield context
        finally:
            await context.close()


@dataclass(slots=True)
class ScraperService:
    pool: BrowserPool
    navigation_timeout_ms: int = 45000
    wait_after_load_ms: int = 1500
    chewy_storage_state: dict[str, Any] | None = None

    async def fetch(self, url: str) -> dict[str, Any]:
        hostname = urlparse(url).hostname or ""
        if hostname.endswith("chewy.com"):
            return await self._fetch_chewy(url)
        return await self._fetch_generic(url)

    async def _fetch_generic(self, url: str) -> dict[str, Any]:
        async with self.pool.context() as context:
            page = await context.new_page()
            await page.set_extra_http_headers(DEFAULT_HEADERS)
            await self._prime_page(page)
            await self._navigate(page, url)
            return await self._extract_payload(page, url)

    async def _fetch_chewy(self, url: str) -> dict[str, Any]:
        async with self.pool.context(storage_state=self.chewy_storage_state) as context:
            page = await context.new_page()
            await page.set_extra_http_headers(DEFAULT_HEADERS)
            await self._prime_page(page)
            try:
                await self._navigate(
                    page,
                    "https://www.chewy.com/",
                    wait_until="domcontentloaded",
                    referer=None,
                )
                await asyncio.sleep(1.5)
            except HTTPException:
                LOGGER.info("Failed to warm up chewy homepage; continuing")
            await asyncio.sleep(0.5)
            await self._navigate(
                page,
                url,
                wait_until="networkidle",
                referer="https://www.chewy.com/",
            )
            # If Akamai still serves a throttle page, try once more after delay
            await self._ensure_chewy_content(page, url)
            result = await self._extract_payload(page, url)
            try:
                self.chewy_storage_state = await context.storage_state()
            except Exception:  # noqa: BLE001
                LOGGER.debug("Unable to persist chewy storage state", exc_info=True)
            return result

    async def _ensure_chewy_content(self, page: Page, url: str) -> None:
        probe_script = """
        () => {
            const blockingScript = document.querySelector('script[src*="ips.js"], script[src*="akamai"]');
            const captcha = document.querySelector('[data-captcha], #px-captcha, #cf-chl-widget');
            const tooMany = document.body && document.body.innerText && document.body.innerText.includes('Too Many Requests');
            const title = document.querySelector("h1[data-testid='product-title']");
            const ogMeta = document.querySelector('meta[property="og:title"], meta[name="og:title"]');
            return { blockingScript: !!blockingScript, captcha: !!captcha, tooMany, productReady: !!(title || ogMeta) };
        }
        """

        wait_condition = """
        () => {
            const title = document.querySelector("h1[data-testid='product-title']");
            const og = document.querySelector("meta[property='og:title'], meta[name='og:title']");
            return !!(title || og);
        }
        """

        for attempt in range(6):
            try:
                await page.wait_for_function(wait_condition, timeout=12000)
            except Exception:  # noqa: BLE001
                pass

            probe = await page.evaluate(probe_script)
            if probe.get("productReady") and not (
                probe.get("blockingScript") or probe.get("captcha") or probe.get("tooMany")
            ):
                return

            LOGGER.info(
                "Chewy challenge detected (attempt %s): %s", attempt + 1, probe
            )
            await asyncio.sleep(5 + attempt * 2)
            if attempt >= 2:
                await self._navigate(
                    page,
                    url,
                    wait_until="networkidle",
                    referer="https://www.chewy.com/",
                    allow_retry=False,
                )

        LOGGER.warning("Chewy content still not available after retries for %s", url)

    async def _navigate(
        self,
        page: Page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        referer: str | None = None,
        allow_retry: bool = True,
    ) -> None:
        try:
            response: Response | None = await page.goto(
                url,
                wait_until=wait_until,
                timeout=self.navigation_timeout_ms,
                referer=referer,
            )
            if response and response.status >= 500 and allow_retry:
                LOGGER.info(
                    "Retrying navigation to %s after server status %s", url, response.status
                )
                await asyncio.sleep(1.5)
                await page.goto(
                    url,
                    wait_until=wait_until,
                    timeout=self.navigation_timeout_ms,
                    referer=referer,
                )
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:  # noqa: BLE001
                pass
            if self.wait_after_load_ms:
                await asyncio.sleep(self.wait_after_load_ms / 1000)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load %s: %s", url, exc)
            raise HTTPException(status_code=502, detail="Navigation failed") from exc

    async def _extract_payload(self, page: Page, url: str) -> dict[str, Any]:
        html = await page.content()
        title = await page.title()
        lang = await page.evaluate("() => document.documentElement.lang || ''")
        meta = await self._collect_meta(page)
        excerpt = meta.get("description") or meta.get("og:description") or ""
        result = {
            "source": url,
            "title": title.strip() if title else "",
            "excerpt": excerpt.strip(),
            "lang": (lang or "").strip() or None,
            "meta": meta,
            "content": html,
            "fullContent": html,
        }
        return result

    async def _collect_meta(self, page: Page) -> dict[str, str]:
        script = """
        () => {
            const tags = Array.from(document.querySelectorAll('meta'));
            return tags.flatMap(tag => {
                const key = tag.getAttribute('property') || tag.getAttribute('name');
                if (!key) return [];
                const value = tag.getAttribute('content');
                if (!value) return [];
                return [{ key, value }];
            });
        }
        """
        records = await page.evaluate(script)
        return {entry["key"].strip(): entry["value"].strip() for entry in records}

    async def _prime_page(self, page: Page) -> None:
        override_script = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
            if (!navigator.userAgentData) {
                const uaData = {
                    brands: [
                        { brand: 'Chromium', version: '128' },
                        { brand: 'Google Chrome', version: '128' },
                        { brand: 'Not=A?Brand', version: '24' },
                    ],
                    mobile: false,
                    platform: 'Windows',
                    getHighEntropyValues: async () => ({
                        architecture: 'x86',
                        bitness: '64',
                        model: '',
                        platform: 'Windows',
                        platformVersion: '15.0.0',
                        uaFullVersion: '128.0.0.0',
                        fullVersionList: [
                            { brand: 'Chromium', version: '128.0.0.0' },
                            { brand: 'Google Chrome', version: '128.0.0.0' },
                            { brand: 'Not=A?Brand', version: '24.0.0.0' },
                        ],
                    }),
                    toJSON: () => uaData,
                };
                Object.defineProperty(navigator, 'userAgentData', {
                    get: () => uaData,
                });
            }
        """
        await page.add_init_script(override_script)


class ArticleResponse(BaseModel):
    title: str | None = None
    excerpt: str | None = None
    lang: str | None = None
    meta: dict[str, str]
    content: str | None = None
    fullContent: str | None = None
    source: HttpUrl


class DiagnosticsResponse(BaseModel):
    ok: bool
    notes: list[str]


pool = BrowserPool()
scraper_service = ScraperService(pool=pool)


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    await pool.startup()
    try:
        yield
    finally:
        await pool.shutdown()


app = FastAPI(title="CostCourter Scraper", lifespan=lifespan)


def scrub_response(raw: dict[str, Any], full_content: bool) -> dict[str, Any]:
    payload = dict(raw)
    payload["title"] = (payload.get("title") or "").strip()
    payload["excerpt"] = (payload.get("excerpt") or "").strip()
    lang_value = payload.get("lang")
    if isinstance(lang_value, str):
        payload["lang"] = lang_value.strip()
    if not full_content:
        payload["fullContent"] = None
    if payload.get("content") is None:
        payload.pop("content", None)
    if not payload.get("title"):
        payload["title"] = ""
    if not payload.get("excerpt"):
        payload["excerpt"] = ""
    if not payload.get("lang"):
        payload.pop("lang", None)
    return payload


@app.get("/health", response_model=DiagnosticsResponse)
async def health() -> DiagnosticsResponse:
    if pool.browser is None:
        return DiagnosticsResponse(ok=False, notes=["browser unavailable"])
    return DiagnosticsResponse(ok=True, notes=[])


@app.get("/api/article", response_model=ArticleResponse)
async def get_article(
    url: HttpUrl = Query(..., description="Target URL to scrape"),
    full_content: bool = Query(False, alias="full-content"),
    cache: bool = Query(False, description="Ignored placeholder"),
) -> ArticleResponse:
    _ = cache
    try:
        raw = await scraper_service.fetch(str(url))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Unhandled scraper error for %s", url)
        raise HTTPException(status_code=500, detail="Unhandled scraper error") from exc
    payload = scrub_response(raw, full_content=full_content)
    try:
        return ArticleResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Invalid payload produced for %s: %s", url, exc)
        raise HTTPException(status_code=500, detail="Invalid payload generated") from exc


@app.post("/api/html", response_model=ArticleResponse)
async def fetch_via_post(body: dict[str, Any]) -> ArticleResponse:
    url = body.get("url")
    if not isinstance(url, str) or not url:
        raise HTTPException(status_code=422, detail="url is required")
    full_content = bool(body.get("fullContent"))
    raw = await scraper_service.fetch(url)
    payload = scrub_response(raw, full_content=full_content)
    return ArticleResponse.model_validate(payload)
