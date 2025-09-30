from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx
from fastapi.testclient import TestClient

import app.models as models
from app.api.endpoints import search as search_endpoint
from app.core.config import settings
from app.services.search import HttpClient, SearxSearchService


class ApiFakeHttpClient:
    def __init__(
        self, responses: list[dict[str, Any]], calls: list[dict[str, Any]]
    ) -> None:
        self._responses = list(responses)
        self.calls = calls

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        timeout: httpx.Timeout,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers})
        if not self._responses:
            raise AssertionError("Unexpected HTTP call")
        payload = self._responses.pop(0)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code=200, json=payload, request=request)


def test_search_endpoint_returns_results(authed_client: TestClient) -> None:
    previous_url = settings.searxng_url
    settings.searxng_url = "https://searx.test/search"

    responses = [
        {
            "results": [
                {
                    "title": "Sample Result",
                    "url": "https://example.com/product",
                    "content": "Product description",
                    "engine": "google",
                }
            ]
        }
    ]
    calls: list[dict[str, Any]] = []

    def factory(timeout: httpx.Timeout) -> HttpClient:
        return ApiFakeHttpClient(responses, calls)

    previous_service = search_endpoint._search_service
    search_endpoint._search_service = SearxSearchService(
        settings_obj=settings,
        http_client_factory=factory,
    )

    try:
        store_payload = {
            "name": "Example Store",
            "slug": "example-store",
            "website_url": "https://example.com",
            "domains": [{"domain": "example.com"}],
        }
        store_response = authed_client.post("/api/stores", json=store_payload)
        assert store_response.status_code == 201
        store_data = store_response.json()

        response = authed_client.get("/api/search", params={"query": "headphones"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["cache_hit"] is False
        assert len(payload["results"]) == 1
        result = payload["results"][0]
        assert result["store_id"] == store_data["id"]
        assert calls
    finally:
        search_endpoint._search_service = previous_service
        settings.searxng_url = previous_url


def test_search_owner_override_allows_admin(
    client: TestClient,
    make_auth_headers: Callable[[models.User], dict[str, str]],
    standard_user: models.User,
    admin_user: models.User,
) -> None:
    previous_url = settings.searxng_url
    settings.searxng_url = "https://searx.test/search"

    responses = [
        {
            "results": [
                {
                    "title": "Sample Result",
                    "url": "https://example.com/product",
                    "engine": "bing",
                }
            ]
        }
    ]
    calls: list[dict[str, Any]] = []

    def factory(timeout: httpx.Timeout) -> HttpClient:
        return ApiFakeHttpClient(responses, calls)

    previous_service = search_endpoint._search_service
    search_endpoint._search_service = SearxSearchService(
        settings_obj=settings,
        http_client_factory=factory,
    )

    try:
        user_headers = make_auth_headers(standard_user)
        store_payload = {
            "name": "Example Store",
            "slug": "example-store",
            "website_url": "https://example.com",
            "domains": [{"domain": "example.com"}],
        }
        store_response = client.post(
            "/api/stores", json=store_payload, headers=user_headers
        )
        assert store_response.status_code == 201
        store_data = store_response.json()

        admin_headers = make_auth_headers(admin_user)
        response = client.get(
            "/api/search",
            params={"query": "headphones", "owner_id": standard_user.id},
            headers=admin_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["cache_hit"] is False
        result = payload["results"][0]
        assert result["store_id"] == store_data["id"]
        assert calls
    finally:
        search_endpoint._search_service = previous_service
        settings.searxng_url = previous_url


def test_search_endpoint_requires_admin_for_owner_override(
    authed_client: TestClient,
) -> None:
    previous_service = search_endpoint._search_service
    search_endpoint._search_service = previous_service

    try:
        response = authed_client.get(
            "/api/search", params={"query": "test", "owner_id": 999}
        )
        assert response.status_code == 403
    finally:
        search_endpoint._search_service = previous_service


def test_search_owner_override_missing_user_returns_404(
    client: TestClient,
    make_auth_headers: Callable[[models.User], dict[str, str]],
    admin_user: models.User,
) -> None:
    headers = make_auth_headers(admin_user)
    response = client.get(
        "/api/search",
        params={"query": "test", "owner_id": 424242},
        headers=headers,
    )
    assert response.status_code == 404


def test_search_endpoint_handles_execution_error(
    authed_client: TestClient,
) -> None:
    class FailingService:
        def search(self, *args: Any, **kwargs: Any) -> Any:
            raise search_endpoint.SearchExecutionError("boom")

    previous_service = search_endpoint._search_service
    search_endpoint._search_service = cast(SearxSearchService, FailingService())
    try:
        response = authed_client.get("/api/search", params={"query": "test"})
        assert response.status_code == 503
        assert response.json()["detail"] == "boom"
    finally:
        search_endpoint._search_service = previous_service
