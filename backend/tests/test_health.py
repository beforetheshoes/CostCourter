from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models as models
from app.core.config import Settings, settings
from app.core.database import get_session
from app.main import app
from app.models.base import utcnow
from app.services.audit import record_audit_log
from app.services.health import _measure_redis, build_readiness_report
from app.services.schedule_tracker import record_schedule_run


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


@pytest.fixture(name="client")
def client_fixture(engine: Engine) -> Iterator[TestClient]:
    previous_redis_host = settings.redis_host
    settings.redis_host = ""

    def override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        settings.redis_host = previous_redis_host


def _seed_observability_data(engine: Engine) -> None:
    with Session(engine) as session:
        user = models.User(email="owner@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)

        store = models.Store(user_id=user.id, name="Demo Store", slug="demo-store")
        session.add(store)
        session.commit()
        session.refresh(store)

        product = models.Product(
            user_id=user.id,
            name="Demo Product",
            slug="demo-product",
        )
        session.add(product)
        session.commit()
        session.refresh(product)

        product_url = models.ProductURL(
            product_id=product.id,
            store_id=store.id,
            url="https://example.com/demo",
            is_primary=True,
            active=True,
        )
        session.add(product_url)
        session.commit()
        session.refresh(product_url)

        history = models.PriceHistory(
            product_id=product.id,
            product_url_id=product_url.id,
            price=42.0,
            currency="USD",
        )
        session.add(history)

        cache_entry = models.SearchCache(
            query_hash="demo-hash",
            query="demo",
            response={"results": []},
            expires_at=utcnow(),
        )
        session.add(cache_entry)
        session.commit()

        record_schedule_run(session, "pricing.update_all_products", timestamp=utcnow())
        record_audit_log(
            session,
            action="health.seed",
            actor_id=user.id,
            entity_type="product",
            entity_id=str(product.id),
            context={"seed": True},
        )


def test_healthcheck(client: TestClient, engine: Engine) -> None:
    _seed_observability_data(engine)

    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


def test_health_readiness_and_metrics(client: TestClient, engine: Engine) -> None:
    _seed_observability_data(engine)

    readiness_resp = client.get("/api/health/readiness")
    assert readiness_resp.status_code == 200
    readiness = readiness_resp.json()
    assert readiness["status"] == "ok"
    components = readiness["components"]
    assert components["database"]["status"] == "ok"
    assert components["redis"]["status"] == "skipped"
    assert components["celery_schedule"]["status"] == "ok"
    assert "last_runs" in components["celery_schedule"]

    metrics_resp = client.get("/api/health/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    resource_counts = metrics["resource_counts"]
    assert resource_counts["products"] == 1
    assert resource_counts["stores"] == 1
    assert resource_counts["product_urls"] == 1
    assert resource_counts["price_history"] == 1
    assert resource_counts["search_cache"] == 1
    assert resource_counts["audit_logs"] == 1
    assert metrics["readiness"]["status"] == "ok"


def test_measure_redis_handles_all_outcomes() -> None:
    settings_obj = Settings()

    with patch("app.services.health.redis.Redis.from_url") as from_url:
        client = MagicMock()
        from_url.return_value = client
        component = _measure_redis(settings_obj)
        assert component.status == "ok"
        details_ok = cast(dict[str, Any], component.details)
        assert "latency_ms" in details_ok
        client.ping.assert_called_once()

    with patch(
        "app.services.health.redis.Redis.from_url",
        side_effect=RedisError("boom"),
    ):
        component = _measure_redis(settings_obj)
        assert component.status == "error"
        details_error = cast(dict[str, Any], component.details)
        assert "boom" in details_error["error"]

    skipped = Settings(redis_host="")
    component = _measure_redis(skipped)
    assert component.status == "skipped"


def test_build_readiness_report_marks_missing_schedule(engine: Engine) -> None:
    with Session(engine) as session:
        config = Settings(redis_host="")
        with patch("app.services.health.fetch_last_run_map", return_value={}):
            with patch(
                "app.services.health.ScheduleHealthService.detect_alerts",
                return_value=[],
            ):
                report = build_readiness_report(session, config)

    assert report["status"] == "degraded"
    components = cast(dict[str, dict[str, Any]], report["components"])
    redis_component = components["redis"]
    schedule_component = components["celery_schedule"]
    assert redis_component["status"] == "skipped"
    assert schedule_component["status"] == "degraded"
    assert schedule_component["message"] == "No schedule runs recorded"
