from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import redis
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.core.config import Settings
from app.models import AuditLog, PriceHistory, Product, ProductURL, SearchCache, Store
from app.models.base import utcnow
from app.services.schedule_health import ScheduleHealthService
from app.services.schedule_tracker import fetch_last_run_map


@dataclass(slots=True)
class HealthComponent:
    name: str
    status: str
    details: Mapping[str, object]


def _overall_status(components: list[HealthComponent]) -> str:
    status_rank = {"ok": 0, "skipped": 0, "degraded": 1, "error": 2}
    worst = 0
    for component in components:
        worst = max(worst, status_rank.get(component.status, 1))
    for label, rank in status_rank.items():
        if rank == worst:
            return label
    return "degraded"


def _measure_database(session: Session) -> HealthComponent:
    start = time.perf_counter()
    try:
        session.exec(select(1)).one()
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        details: dict[str, object] = {"latency_ms": duration_ms}
        status = "ok"
    except Exception as exc:  # pragma: no cover - defensive logging
        details = {"error": str(exc)}
        status = "error"
    return HealthComponent(name="database", status=status, details=details)


def _measure_redis(settings: Settings) -> HealthComponent:
    if not settings.redis_host:
        return HealthComponent(
            name="redis",
            status="skipped",
            details={"message": "Redis not configured"},
        )

    try:
        client = redis.Redis.from_url(settings.redis_uri, socket_timeout=1.0)
        start = time.perf_counter()
        client.ping()
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        return HealthComponent(
            name="redis",
            status="ok",
            details={"latency_ms": duration_ms},
        )
    except RedisError as exc:
        return HealthComponent(
            name="redis",
            status="error",
            details={"error": str(exc)},
        )


def _count(session: Session, model: type[SQLModel]) -> int:
    statement = select(func.count()).select_from(model)
    return session.exec(statement).one()


def _collect_resource_counts(session: Session) -> dict[str, int]:
    return {
        "products": _count(session, Product),
        "stores": _count(session, Store),
        "product_urls": _count(session, ProductURL),
        "price_history": _count(session, PriceHistory),
        "search_cache": _count(session, SearchCache),
        "audit_logs": _count(session, AuditLog),
    }


def _collect_schedule_component(session: Session) -> HealthComponent:
    last_runs = fetch_last_run_map(session)
    serialized = {key: value.isoformat() for key, value in last_runs.items()}
    service = ScheduleHealthService()
    alerts = service.detect_alerts(session)

    details: dict[str, Any] = {"last_runs": dict(serialized)}
    if not last_runs:
        status = "degraded"
        details["message"] = "No schedule runs recorded"
    elif alerts:
        status = "degraded"
        details["alerts"] = [alert.to_dict() for alert in alerts]
    else:
        status = "ok"
    return HealthComponent(name="celery_schedule", status=status, details=details)


def build_readiness_report(session: Session, settings: Settings) -> dict[str, object]:
    components = [
        _measure_database(session),
        _measure_redis(settings),
        _collect_schedule_component(session),
    ]
    status = _overall_status(components)
    return {
        "status": status,
        "checked_at": utcnow().astimezone(UTC).isoformat(),
        "components": {
            component.name: {"status": component.status, **component.details}
            for component in components
        },
    }


def build_metrics_payload(session: Session, settings: Settings) -> dict[str, object]:
    readiness = build_readiness_report(session, settings)
    counts = _collect_resource_counts(session)
    return {
        "generated_at": utcnow().astimezone(UTC).isoformat(),
        "readiness": readiness,
        "resource_counts": counts,
    }


__all__ = [
    "build_metrics_payload",
    "build_readiness_report",
]
