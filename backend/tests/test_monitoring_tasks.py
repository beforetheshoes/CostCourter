from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models as models
from app.core.config import settings
from app.models import AppSetting
from app.services.notifications import (
    NotificationService,
    set_notification_service_factory,
)
from app.tasks.monitoring import (
    check_schedule_health_task,
    set_monitoring_session_factory,
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
def restore_factories() -> Iterator[None]:
    try:
        yield
    finally:
        set_monitoring_session_factory(None)
        set_notification_service_factory(None)


@pytest.fixture(autouse=True)
def restore_schedule_path() -> Iterator[None]:
    previous = settings.celery_beat_schedule_path
    try:
        yield
    finally:
        settings.celery_beat_schedule_path = previous


def _write_schedule(tmp_path: Path) -> None:
    payload = {
        "pricing.update_all_products": {
            "task": "pricing.update_all_products",
            "schedule": 3600,
        }
    }
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(json.dumps(payload), encoding="utf-8")
    settings.celery_beat_schedule_path = str(schedule_path)


def test_check_schedule_health_task_sends_notifications(
    engine: Engine, tmp_path: Path
) -> None:
    _write_schedule(tmp_path)

    with Session(engine) as session:
        session.add(
            AppSetting(
                key="schedule.last_run.pricing.update_all_products",
                value="2025-09-27T08:00:00+00:00",
            )
        )
        admin_role = models.Role(slug="admin", name="Admin")
        session.add(admin_role)
        session.commit()
        session.refresh(admin_role)

        admin_user = models.User(email="admin@example.com", is_active=True)
        session.add(admin_user)
        session.commit()
        session.refresh(admin_user)

        session.add(
            models.UserRoleAssignment(user_id=admin_user.id, role_id=admin_role.id)
        )
        session.commit()

    @contextmanager
    def _session_scope() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    set_monitoring_session_factory(lambda: _session_scope())

    class StubNotificationService(NotificationService):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, str, str]] = []

        def send_system_alert(
            self,
            session: Session,
            *,
            user: models.User,
            title: str,
            summary: str,
            link: str | None = None,
        ) -> bool:
            self.calls.append((user.email, title, summary))
            return True

    stub = StubNotificationService()
    set_notification_service_factory(lambda: stub)

    result = check_schedule_health_task()

    assert stub.calls
    assert result["notifications_sent"] == len(stub.calls)
    assert result["alerts"]
    assert result["recipients"] == ["admin@example.com"]
