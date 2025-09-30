from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.services import pricing_schedule
from app.services.pricing_schedule import (
    _estimate_next_run,
    _next_cron_run,
    describe_pricing_schedule,
    estimate_schedule_interval,
    load_schedule_mapping,
    resolve_schedule_path,
)


def test_resolve_schedule_path_handles_relative() -> None:
    relative = "configs/schedule.json"
    resolved = resolve_schedule_path(relative)
    expected_root = Path(pricing_schedule.__file__).resolve().parent.parent
    assert resolved == expected_root / relative


def test_resolve_schedule_path_returns_none_for_empty() -> None:
    assert resolve_schedule_path(None) is None
    assert resolve_schedule_path("") is None


def test_load_schedule_mapping_discards_invalid_entries(tmp_path: Path) -> None:
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(
        json.dumps({"valid": {"task": "pricing.update"}, "invalid": []}),
        encoding="utf-8",
    )
    mapping = load_schedule_mapping(schedule_path)
    assert list(mapping) == ["valid"]


def test_describe_pricing_schedule_uses_default_when_file_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = settings.celery_beat_schedule_path
    settings.celery_beat_schedule_path = "missing.json"
    monkeypatch.setattr(
        "app.services.pricing_schedule.fetch_last_run_map",
        lambda session: {
            "pricing.update_all_products": datetime(2024, 1, 1, tzinfo=UTC)
        },
    )
    now_value = datetime(2024, 1, 1, 12, tzinfo=UTC)
    try:
        descriptions = describe_pricing_schedule(
            session=cast(Session, object()),
            now=now_value,
        )
    finally:
        settings.celery_beat_schedule_path = previous
    assert descriptions
    entry = descriptions[0]
    assert entry["task"] == "pricing.update_all_products"
    assert entry["last_run_at"].tzinfo is UTC
    assert entry["next_run_at"] is not None


def test_describe_pricing_schedule_handles_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule_path = tmp_path / "broken.json"
    schedule_path.write_text('{"oops":', encoding="utf-8")
    previous = settings.celery_beat_schedule_path
    settings.celery_beat_schedule_path = str(schedule_path)
    monkeypatch.setattr(
        "app.services.pricing_schedule.fetch_last_run_map",
        lambda session: {},
    )
    try:
        descriptions = describe_pricing_schedule(session=None, now=datetime.now(UTC))
    finally:
        settings.celery_beat_schedule_path = previous
    assert any(item["task"] == "pricing.update_all_products" for item in descriptions)


def test_estimate_next_run_supports_multiple_schedule_formats() -> None:
    now_value = datetime(2024, 1, 1, 12, tzinfo=UTC)
    last_run = datetime(2024, 1, 1, 11, 30, tzinfo=UTC)

    numeric = _estimate_next_run({"schedule": 300}, now_value, last_run)
    assert numeric is not None and numeric >= now_value

    numeric_str = _estimate_next_run({"schedule": "600"}, now_value, None)
    assert numeric_str is not None

    cron_str = _estimate_next_run({"schedule": "*/5 * * * *"}, now_value, None)
    assert cron_str is not None

    mapping_cron = _estimate_next_run(
        {"schedule": {"cron": "*/10 * * * *"}}, now_value, None
    )
    assert mapping_cron is not None

    cron_fields = _estimate_next_run({"minute": "*/15"}, now_value, None)
    assert cron_fields is not None

    default_interval = _estimate_next_run({"schedule": None}, now_value, None)
    assert default_interval is not None

    unsupported = _estimate_next_run({"schedule": []}, now_value, None)
    assert unsupported is None


def test_estimate_next_run_returns_none_for_invalid_interval() -> None:
    now_value = datetime(2024, 1, 1, 12, tzinfo=UTC)
    result = _estimate_next_run({"schedule": -5}, now_value, None)
    assert result is None


def test_next_cron_run_handles_invalid_expression() -> None:
    now_value = datetime(2024, 1, 1, tzinfo=UTC)
    result = _next_cron_run("invalid", now_value, None)
    assert result is None


def test_estimate_schedule_interval_handles_various_inputs() -> None:
    now_value = datetime(2024, 1, 1, tzinfo=UTC)
    assert estimate_schedule_interval({"schedule": 120}) == timedelta(seconds=120)
    assert estimate_schedule_interval({"schedule": "300"}) == timedelta(seconds=300)
    assert estimate_schedule_interval({"schedule": {"interval": 45}}) == timedelta(
        seconds=45
    )
    assert (
        estimate_schedule_interval({"minute": "*/10"}, reference=now_value) is not None
    )
    assert estimate_schedule_interval({"schedule": None}) == timedelta(hours=6)
    assert estimate_schedule_interval({"schedule": []}) is None
    assert (
        estimate_schedule_interval({"schedule": "invalid"}, reference=now_value) is None
    )
