from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.core.config import settings
from app.worker import _apply_schedule_from_json, _load_beat_schedule, celery_app


def test_celery_app_configuration_matches_settings() -> None:
    assert celery_app.main == "costcourter"
    assert celery_app.conf.broker_url == settings.redis_uri
    assert celery_app.conf.result_backend == settings.redis_uri
    assert celery_app.conf.timezone == settings.timezone
    assert celery_app.conf.broker_pool_limit == settings.redis_pool_max_connections
    assert celery_app.conf.redis_max_connections == settings.redis_pool_max_connections
    assert celery_app.conf.broker_transport_options["max_connections"] == (
        settings.redis_pool_max_connections
    )
    assert celery_app.conf.result_backend_transport_options["max_connections"] == (
        settings.redis_pool_max_connections
    )


@pytest.fixture(name="schedule_guard")
def schedule_guard() -> Iterator[None]:
    original = celery_app.conf.beat_schedule.copy()
    try:
        yield
    finally:
        celery_app.conf.beat_schedule = original


def test_apply_schedule_from_json_updates_celery(schedule_guard: None) -> None:
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "schedule.json"
        path.write_text(
            json.dumps(
                {
                    "pricing.update_all_products": {
                        "task": "pricing.update_all_products",
                        "schedule": 3600,
                        "args": [],
                    }
                }
            ),
            encoding="utf-8",
        )

        count = _apply_schedule_from_json(path)
        assert count == 1
        entry = celery_app.conf.beat_schedule["pricing.update_all_products"]
        from datetime import timedelta

        assert entry["schedule"].run_every == timedelta(seconds=3600)


def test_load_beat_schedule_reads_config(schedule_guard: None) -> None:
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "schedule.json"
        path.write_text(
            json.dumps(
                {
                    "custom.task": {
                        "task": "custom.task",
                        "schedule": 1800,
                        "args": [1, 2, 3],
                        "kwargs": {"logging": True},
                    }
                }
            ),
            encoding="utf-8",
        )

        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = str(path)
        try:
            _load_beat_schedule()
            assert "custom.task" in celery_app.conf.beat_schedule
            entry = celery_app.conf.beat_schedule["custom.task"]
            assert entry["kwargs"]["logging"] is True
        finally:
            settings.celery_beat_schedule_path = previous_path


def test_load_beat_schedule_handles_invalid_json(schedule_guard: None) -> None:
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "schedule.json"
        path.write_text("not-json", encoding="utf-8")

        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = str(path)
        try:
            _load_beat_schedule()
            assert "pricing.update_all_products" in celery_app.conf.beat_schedule
        finally:
            settings.celery_beat_schedule_path = previous_path
