from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models as models
from app.core.config import settings
from app.models import AppSetting
from app.services.schedule_health import (
    ScheduleHealthService,
    format_alert_summary,
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


def _write_schedule(tmp_path: Path, schedule: dict[str, dict[str, object]]) -> Path:
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")
    settings.celery_beat_schedule_path = str(schedule_path)
    return schedule_path


def test_detect_alerts_returns_alert_when_interval_exceeded(
    engine: Engine, tmp_path: Path
) -> None:
    _write_schedule(
        tmp_path,
        {
            "pricing.update_all_products": {
                "task": "pricing.update_all_products",
                "schedule": 3600,
            }
        },
    )

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="2025-09-27T08:00:00+00:00",
            )
        )
        session.commit()

        service = ScheduleHealthService()
        alerts = service.detect_alerts(
            session, now=datetime(2025, 9, 27, 12, 0, tzinfo=UTC)
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.task == "pricing.update_all_products"
    assert int(alert.interval.total_seconds()) == 3600
    assert alert.overdue.total_seconds() > 0


def test_detect_alerts_skips_recent_runs(engine: Engine, tmp_path: Path) -> None:
    _write_schedule(
        tmp_path,
        {
            "pricing.update_all_products": {
                "task": "pricing.update_all_products",
                "schedule": 3600,
            }
        },
    )

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="2025-09-27T10:30:00+00:00",
            )
        )
        session.commit()

        service = ScheduleHealthService()
        alerts = service.detect_alerts(
            session, now=datetime(2025, 9, 27, 11, 0, tzinfo=UTC)
        )

    assert alerts == []


def test_list_operator_recipients_includes_superusers_and_admins(
    engine: Engine, tmp_path: Path
) -> None:
    _write_schedule(
        tmp_path,
        {
            "pricing.update_all_products": {
                "task": "pricing.update_all_products",
                "schedule": 3600,
            }
        },
    )

    with Session(engine) as session:
        admin_role = models.Role(slug="admin", name="Admin")
        session.add(admin_role)
        session.commit()
        session.refresh(admin_role)

        superuser = models.User(email="super@example.com", is_superuser=True)
        admin = models.User(email="admin@example.com", is_superuser=False)
        normal = models.User(email="user@example.com", is_superuser=False)
        session.add_all([superuser, admin, normal])
        session.commit()

        session.add(models.UserRoleAssignment(user_id=admin.id, role_id=admin_role.id))
        session.commit()

        service = ScheduleHealthService()
        recipients = service.list_operator_recipients(session)

    emails = {user.email for user in recipients}
    assert emails == {"super@example.com", "admin@example.com"}


def test_format_alert_summary(engine: Engine, tmp_path: Path) -> None:
    _write_schedule(
        tmp_path,
        {
            "pricing.update_all_products": {
                "task": "pricing.update_all_products",
                "schedule": 3600,
            }
        },
    )

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="2025-09-27T08:00:00+00:00",
            )
        )
        session.commit()

        service = ScheduleHealthService()
        alerts = service.detect_alerts(
            session, now=datetime(2025, 9, 27, 12, 0, tzinfo=UTC)
        )

    summary = format_alert_summary(alerts)
    assert "pricing.update_all_products" in summary
    assert "overdue" in summary
