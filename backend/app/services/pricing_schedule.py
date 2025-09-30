from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from croniter import croniter
from sqlmodel import Session

from app.core.config import settings
from app.models.base import utcnow
from app.services.schedule_tracker import fetch_last_run_map

_LOGGER = structlog.get_logger(__name__)

_DEFAULT_SCHEDULE: dict[str, dict[str, Any]] = {
    "pricing.update_all_products": {
        "task": "pricing.update_all_products",
        "minute": 0,
        "hour": "*/6",
        "day_of_week": "*",
        "day_of_month": "*",
        "month_of_year": "*",
        "args": [],
        "kwargs": {"logging": False},
    }
}


@dataclass(slots=True)
class ScheduleDescription:
    """Normalised schedule entry augmented with run metadata."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def resolve_schedule_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    root = Path(__file__).resolve().parent.parent
    return root / path_value


def load_schedule_mapping(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Schedule file must be a JSON object mapping names to entries")

    mapping: dict[str, dict[str, Any]] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            _LOGGER.warning(
                "celery.schedule.entry_invalid",
                name=name,
                reason="entry must be a JSON object",
            )
            continue
        mapping[name] = entry
    return mapping


def describe_pricing_schedule(
    session: Session | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    schedule_path = resolve_schedule_path(settings.celery_beat_schedule_path)
    mapping: dict[str, dict[str, Any]]

    if schedule_path and schedule_path.exists():
        try:
            mapping = load_schedule_mapping(schedule_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _LOGGER.warning(
                "celery.schedule.load_failed",
                path=str(schedule_path),
                error=str(exc),
            )
            mapping = {}
    else:
        mapping = {}

    if not mapping:
        mapping = {key: value.copy() for key, value in _DEFAULT_SCHEDULE.items()}

    now_value = now or utcnow()
    last_runs = fetch_last_run_map(session) if session is not None else {}

    descriptions: list[dict[str, Any]] = []
    for name, entry in mapping.items():
        descriptions.append(
            _build_description(
                name=name,
                entry=entry,
                now_value=now_value,
                last_runs=last_runs,
            )
        )

    descriptions.sort(key=lambda payload: payload["name"])
    return descriptions


def _build_description(
    *,
    name: str,
    entry: Mapping[str, Any],
    now_value: datetime,
    last_runs: Mapping[str, datetime],
) -> dict[str, Any]:
    payload = dict(entry)
    task = str(payload.get("task", name))
    enabled = payload.get("enabled", True) is not False
    args = list(payload.get("args", []) or [])
    kwargs = dict(payload.get("kwargs", {}) or {})
    last_run = last_runs.get(task) or last_runs.get(name)
    next_run: datetime | None = None

    if enabled:
        next_run = _estimate_next_run(payload, now_value, last_run)

    normalised: dict[str, Any] = {
        key: value
        for key, value in payload.items()
        if key
        not in {"name", "args", "kwargs", "enabled", "last_run_at", "next_run_at"}
    }
    normalised.update(
        {
            "name": name,
            "task": task,
            "enabled": enabled,
            "args": args,
            "kwargs": kwargs,
            "last_run_at": last_run,
            "next_run_at": next_run,
        }
    )
    return normalised


def _estimate_next_run(
    entry: Mapping[str, Any], now_value: datetime, last_run: datetime | None
) -> datetime | None:
    schedule_value = entry.get("schedule")
    if isinstance(schedule_value, (int, float)):
        return _next_interval_run(
            timedelta(seconds=float(schedule_value)), now_value, last_run
        )

    if isinstance(schedule_value, str):
        stripped = schedule_value.strip()
        if _looks_like_cron_expression(stripped):
            return _next_cron_run(stripped, now_value, last_run)
        if stripped.replace(".", "", 1).isdigit():
            seconds = float(stripped)
            return _next_interval_run(timedelta(seconds=seconds), now_value, last_run)

    if isinstance(schedule_value, Mapping):
        inner = dict(schedule_value)
        if "cron" in inner and isinstance(inner["cron"], str):
            return _next_cron_run(inner["cron"], now_value, last_run)

    if _has_cron_fields(entry):
        expression = _build_cron_expression(entry)
        return _next_cron_run(expression, now_value, last_run)

    if schedule_value is None:
        # Fall back to default 6 hour cadence.
        return _next_interval_run(timedelta(hours=6), now_value, last_run)

    _LOGGER.warning(
        "celery.schedule.next_run_unsupported",
        schedule_type=type(schedule_value).__name__,
    )
    return None


def _next_interval_run(
    interval: timedelta, now_value: datetime, last_run: datetime | None
) -> datetime | None:
    if interval.total_seconds() <= 0:
        return None

    now_aware = _ensure_aware(now_value)
    reference = _ensure_aware(last_run) if last_run else now_aware

    if reference < now_aware:
        elapsed = (now_aware - reference).total_seconds()
        cycles = max(1, math.ceil(elapsed / interval.total_seconds()))
        return reference + (interval * cycles)

    return reference + interval


def _next_cron_run(
    expression: str, now_value: datetime, last_run: datetime | None
) -> datetime | None:
    base = _ensure_aware(last_run) if last_run else _ensure_aware(now_value)
    try:
        iterator = croniter(expression, base)
        candidate = iterator.get_next(datetime)
        if not isinstance(candidate, datetime):
            candidate = datetime.fromtimestamp(candidate, tz=UTC)
    except (ValueError, TypeError) as exc:
        _LOGGER.warning(
            "celery.schedule.cron_parse_failed",
            expression=expression,
            error=str(exc),
        )
        return None

    candidate = _ensure_aware(candidate)
    now_aware = _ensure_aware(now_value)

    while candidate <= now_aware:
        candidate = iterator.get_next(datetime)
        if not isinstance(candidate, datetime):
            candidate = datetime.fromtimestamp(candidate, tz=UTC)
        candidate = _ensure_aware(candidate)
    return candidate


def _looks_like_cron_expression(value: str) -> bool:
    return value.count(" ") >= 4


def _has_cron_fields(entry: Mapping[str, Any]) -> bool:
    return any(
        key in entry
        for key in ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")
    )


def _build_cron_expression(entry: Mapping[str, Any]) -> str:
    def _component(key: str, default: str) -> str:
        value = entry.get(key, default)
        return str(value if value not in (None, "") else default)

    return " ".join(
        [
            _component("minute", "0"),
            _component("hour", "*/6"),
            _component("day_of_month", "*"),
            _component("month_of_year", "*"),
            _component("day_of_week", "*"),
        ]
    )


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def estimate_schedule_interval(
    entry: Mapping[str, Any], *, reference: datetime | None = None
) -> timedelta | None:
    """Estimate the cadence for a Celery beat entry.

    Falls back to the default 6 hour cadence when no explicit schedule is
    provided. Returns ``None`` when the schedule cannot be interpreted.
    """

    schedule_value = entry.get("schedule")
    if isinstance(schedule_value, (int, float)):
        seconds = float(schedule_value)
        return timedelta(seconds=seconds) if seconds > 0 else None

    if isinstance(schedule_value, str):
        stripped = schedule_value.strip()
        if stripped.replace(".", "", 1).isdigit():
            seconds = float(stripped)
            return timedelta(seconds=seconds) if seconds > 0 else None
        if _looks_like_cron_expression(stripped):
            return _cron_interval(stripped, reference)

    if isinstance(schedule_value, Mapping):
        inner = dict(schedule_value)
        cron_value = inner.get("cron")
        if isinstance(cron_value, str):
            return _cron_interval(cron_value, reference)
        interval = inner.get("interval")
        if isinstance(interval, (int, float)):
            seconds = float(interval)
            return timedelta(seconds=seconds) if seconds > 0 else None

    if _has_cron_fields(entry):
        expression = _build_cron_expression(entry)
        return _cron_interval(expression, reference)

    if schedule_value is None:
        return timedelta(hours=6)

    return None


def _cron_interval(expression: str, reference: datetime | None) -> timedelta | None:
    base = _ensure_aware(reference or utcnow())
    try:
        iterator = croniter(expression, base)
        first = iterator.get_next(datetime)
        second = iterator.get_next(datetime)
    except (ValueError, TypeError) as exc:
        _LOGGER.warning(
            "celery.schedule.cron_interval_failed",
            expression=expression,
            error=str(exc),
        )
        return None

    if not isinstance(first, datetime):
        first = datetime.fromtimestamp(first, tz=UTC)
    if not isinstance(second, datetime):
        second = datetime.fromtimestamp(second, tz=UTC)

    first_aware = _ensure_aware(first)
    second_aware = _ensure_aware(second)
    interval = second_aware - first_aware
    if interval.total_seconds() <= 0:
        return None
    return interval


__all__ = [
    "ScheduleDescription",
    "describe_pricing_schedule",
    "estimate_schedule_interval",
    "load_schedule_mapping",
    "resolve_schedule_path",
]
