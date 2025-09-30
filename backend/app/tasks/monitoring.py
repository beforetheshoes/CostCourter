from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, TypeVar

import structlog
from celery import shared_task
from sqlmodel import Session

from app.core.database import engine
from app.services.audit import record_audit_log
from app.services.notifications import get_notification_service
from app.services.schedule_health import (
    ScheduleHealthService,
    format_alert_summary,
)

_LOGGER = structlog.get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]
T = TypeVar("T")


@contextmanager
def _default_session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


_session_scope: SessionFactory = _default_session_scope


def set_monitoring_session_factory(factory: SessionFactory | None) -> None:
    global _session_scope
    _session_scope = factory or _default_session_scope


def _run_with_session(func: Callable[[Session], T]) -> T:
    with _session_scope() as session:
        return func(session)


@shared_task(name="schedule.check_health")
def check_schedule_health_task() -> dict[str, Any]:
    service = ScheduleHealthService()
    notification_service = get_notification_service()

    def runner(session: Session) -> dict[str, Any]:
        alerts = service.detect_alerts(session)
        recipients = service.list_operator_recipients(session) if alerts else []
        notifications_sent = 0

        if alerts and recipients:
            summary = format_alert_summary(alerts)
            title = "Celery schedule delayed"
            for user in recipients:
                delivered = notification_service.send_system_alert(
                    session,
                    user=user,
                    title=title,
                    summary=summary,
                )
                if delivered:
                    notifications_sent += 1

            if notifications_sent:
                record_audit_log(
                    session,
                    action="notification.schedule_alert",
                    entity_type="schedule",
                    entity_id=None,
                    context={
                        "alerts": [alert.to_dict() for alert in alerts],
                        "recipients": [user.email for user in recipients],
                    },
                )
            else:
                _LOGGER.info(
                    "schedule.health.alert.no_channels",
                    recipients=len(recipients),
                )
        elif alerts and not recipients:
            _LOGGER.info("schedule.health.alert.no_recipients")

        return {
            "alerts": [alert.to_dict() for alert in alerts],
            "recipients": [user.email for user in recipients],
            "notifications_sent": notifications_sent,
        }

    return _run_with_session(runner)


__all__ = [
    "check_schedule_health_task",
    "set_monitoring_session_factory",
]
