from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import structlog
from celery import Celery
from celery.schedules import crontab, schedule

from .core.config import settings

celery_app = Celery(
    "costcourter",
    broker=settings.redis_uri,
    backend=settings.redis_uri,
)
celery_app.conf.timezone = settings.timezone
celery_app.conf.broker_pool_limit = settings.redis_pool_max_connections
existing_broker_transport_options = dict(
    getattr(celery_app.conf, "broker_transport_options", {}) or {}
)
existing_broker_transport_options["max_connections"] = (
    settings.redis_pool_max_connections
)
celery_app.conf.broker_transport_options = existing_broker_transport_options
existing_backend_transport_options = dict(
    getattr(celery_app.conf, "result_backend_transport_options", {}) or {}
)
existing_backend_transport_options["max_connections"] = (
    settings.redis_pool_max_connections
)
celery_app.conf.result_backend_transport_options = existing_backend_transport_options
celery_app.conf.redis_max_connections = settings.redis_pool_max_connections
celery_app.autodiscover_tasks(["app.tasks"])


_SCHEDULE_WATCH_THREAD_STARTED = False
_LAST_SCHEDULE_MTIME: float | None = None


def _apply_schedule_from_json(path: Path) -> int:
    logger = structlog.get_logger(__name__)
    with path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    beat_schedule: dict[str, dict] = {}
    for name, entry in config.items():
        if entry.get("enabled") is False:
            continue
        task = str(entry.get("task", name))
        raw = entry.get("schedule", 21600)
        if isinstance(raw, (int, float)):
            sched = schedule(raw)
        else:
            minute = entry.get("minute", 0)
            hour = entry.get("hour", "*/6")
            day_of_week = entry.get("day_of_week", "*")
            day_of_month = entry.get("day_of_month", "*")
            month_of_year = entry.get("month_of_year", "*")
            sched = crontab(
                minute=minute,
                hour=hour,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                month_of_year=month_of_year,
            )
        beat_schedule[name] = {
            "task": task,
            "schedule": sched,
            "args": entry.get("args", []),
            "kwargs": entry.get("kwargs", {}),
        }
    celery_app.conf.beat_schedule = beat_schedule
    logger.info("celery.beat_schedule.applied", entries=len(beat_schedule))
    return len(beat_schedule)


def _load_beat_schedule() -> None:
    logger = structlog.get_logger(__name__)
    path = settings.celery_beat_schedule_path
    if path:
        try:
            schedule_path = Path(path)
            if not schedule_path.is_absolute():
                schedule_path = Path(__file__).resolve().parent.parent / path
            _apply_schedule_from_json(schedule_path)
            global _LAST_SCHEDULE_MTIME
            _LAST_SCHEDULE_MTIME = schedule_path.stat().st_mtime
            logger.info("celery.beat_schedule.loaded", path=str(schedule_path))
            return
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("celery.beat_schedule.load_failed", error=str(exc))

    # Fallback default: update all products every 6 hours, top of the hour.
    celery_app.conf.beat_schedule = {
        "pricing.update_all_products": {
            "task": "pricing.update_all_products",
            "schedule": crontab(minute=0, hour="*/6"),
            "args": [],
            "kwargs": {"logging": False},
        }
    }
    structlog.get_logger(__name__).info(
        "celery.beat_schedule.default_applied", entries=1
    )


_load_beat_schedule()


def _watch_schedule_file(interval_seconds: float = 5.0) -> None:
    logger = structlog.get_logger(__name__)
    path = settings.celery_beat_schedule_path
    if not path:
        return
    schedule_path = Path(path)
    if not schedule_path.is_absolute():
        schedule_path = Path(__file__).resolve().parent.parent / path
    logger.info("celery.beat_schedule.watcher.start", path=str(schedule_path))
    global _LAST_SCHEDULE_MTIME
    while True:
        try:
            if schedule_path.exists():
                mtime = schedule_path.stat().st_mtime
                if _LAST_SCHEDULE_MTIME is None or mtime > _LAST_SCHEDULE_MTIME:
                    _apply_schedule_from_json(schedule_path)
                    _LAST_SCHEDULE_MTIME = mtime
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("celery.beat_schedule.watcher.error", error=str(exc))
        time.sleep(interval_seconds)


def _ensure_watcher_thread() -> None:
    global _SCHEDULE_WATCH_THREAD_STARTED
    if _SCHEDULE_WATCH_THREAD_STARTED:
        return
    t = threading.Thread(
        target=_watch_schedule_file, name="schedule-watcher", daemon=True
    )
    t.start()
    _SCHEDULE_WATCH_THREAD_STARTED = True


_ensure_watcher_thread()
