from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.models import AppSetting
from app.services.pricing_schedule import (
    describe_pricing_schedule,
    estimate_schedule_interval,
)


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


@pytest.fixture(autouse=True)
def restore_schedule_path() -> Iterator[None]:
    previous = settings.celery_beat_schedule_path
    try:
        yield
    finally:
        settings.celery_beat_schedule_path = previous


def test_describe_pricing_schedule_interval(engine: Engine, tmp_path: Path) -> None:
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(
        json.dumps(
            {
                "pricing.update_all_products": {
                    "task": "pricing.update_all_products",
                    "schedule": 3600,
                    "enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    settings.celery_beat_schedule_path = str(schedule_path)

    reference = datetime(2025, 9, 27, 9, 0, tzinfo=UTC)

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="2025-09-27T08:00:00+00:00",
            )
        )
        session.commit()
        entries = describe_pricing_schedule(session, now=reference)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["last_run_at"].isoformat() == "2025-09-27T08:00:00+00:00"
    assert entry["next_run_at"] == datetime(2025, 9, 27, 9, 0, tzinfo=UTC)


def test_describe_pricing_schedule_cron_fields(engine: Engine, tmp_path: Path) -> None:
    schedule_path = tmp_path / "cron_schedule.json"
    schedule_path.write_text(
        json.dumps(
            {
                "pricing.update_all_products": {
                    "task": "pricing.update_all_products",
                    "minute": 15,
                    "hour": "*/3",
                    "day_of_week": "*",
                }
            }
        ),
        encoding="utf-8",
    )
    settings.celery_beat_schedule_path = str(schedule_path)

    reference = datetime(2025, 9, 27, 3, 10, tzinfo=UTC)

    entries = describe_pricing_schedule(None, now=reference)
    assert len(entries) == 1
    assert entries[0]["next_run_at"] is not None
    assert entries[0]["next_run_at"] > reference


def test_describe_pricing_schedule_handles_invalid_json(
    engine: Engine, tmp_path: Path
) -> None:
    schedule_path = tmp_path / "invalid.json"
    schedule_path.write_text("[]", encoding="utf-8")
    settings.celery_beat_schedule_path = str(schedule_path)

    with Session(engine) as session:
        entries = describe_pricing_schedule(
            session, now=datetime(2025, 9, 27, tzinfo=UTC)
        )

    assert entries
    assert entries[0]["name"] == "pricing.update_all_products"
    assert entries[0]["enabled"] is True
    assert entries[0]["next_run_at"] is not None

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="invalid",
            )
        )
        session.commit()
        entries = describe_pricing_schedule(
            session, now=datetime(2025, 9, 27, tzinfo=UTC)
        )

    assert entries[0]["last_run_at"] is None


def test_estimate_schedule_interval_from_numeric() -> None:
    entry = {
        "name": "pricing.update_all_products",
        "task": "pricing.update_all_products",
        "schedule": 1800,
    }
    interval = estimate_schedule_interval(entry)
    assert interval is not None
    assert interval.total_seconds() == 1800


def test_estimate_schedule_interval_from_cron_fields() -> None:
    entry = {
        "name": "pricing.update_all_products",
        "task": "pricing.update_all_products",
        "minute": 0,
        "hour": "*/2",
    }
    interval = estimate_schedule_interval(
        entry, reference=datetime(2025, 9, 27, 0, 0, tzinfo=UTC)
    )
    assert interval is not None
    assert interval.total_seconds() == 7200
