from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import func, or_
from sqlalchemy.sql.elements import BinaryExpression
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.config import settings as runtime_settings
from app.models import Role, User, UserRoleAssignment
from app.models.base import utcnow
from app.services.pricing_schedule import (
    describe_pricing_schedule,
    estimate_schedule_interval,
)

_LOGGER = structlog.get_logger(__name__)


@dataclass(slots=True)
class ScheduleAlert:
    """Represents a delayed Celery beat task."""

    name: str
    task: str
    last_run_at: datetime
    due_at: datetime
    interval: timedelta
    overdue: timedelta

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "task": self.task,
            "last_run_at": self.last_run_at.astimezone(UTC).isoformat(),
            "due_at": self.due_at.astimezone(UTC).isoformat(),
            "interval_seconds": int(self.interval.total_seconds()),
            "overdue_seconds": int(self.overdue.total_seconds()),
        }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ScheduleHealthService:
    """Detects and reports delayed Celery beat schedule executions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or runtime_settings

    def detect_alerts(
        self,
        session: Session,
        *,
        now: datetime | None = None,
    ) -> list[ScheduleAlert]:
        reference = _aware(now or utcnow())
        entries = describe_pricing_schedule(session, now=reference)
        multiplier = max(self._settings.celery_schedule_alert_multiplier, 1.0)
        grace_seconds = max(
            0,
            self._settings.celery_schedule_alert_min_grace_minutes * 60,
        )

        alerts: list[ScheduleAlert] = []
        for entry in entries:
            if entry.get("enabled", True) is False:
                continue

            last_run = entry.get("last_run_at")
            if last_run is None:
                # Skip alerting until at least one execution is recorded.
                continue

            interval = estimate_schedule_interval(entry, reference=reference)
            if interval is None or interval.total_seconds() <= 0:
                continue

            last_run_utc = _aware(last_run)
            elapsed_seconds = (reference - last_run_utc).total_seconds()
            if elapsed_seconds <= interval.total_seconds():
                continue

            threshold = max(interval.total_seconds() * multiplier, grace_seconds)
            if elapsed_seconds <= threshold:
                continue

            due_at = last_run_utc + interval
            overdue = reference - due_at
            if overdue.total_seconds() <= 0:
                continue

            alerts.append(
                ScheduleAlert(
                    name=str(entry.get("name", entry.get("task", ""))),
                    task=str(entry.get("task", entry.get("name", ""))),
                    last_run_at=last_run_utc,
                    due_at=due_at,
                    interval=interval,
                    overdue=overdue,
                )
            )

        return alerts

    def list_operator_recipients(self, session: Session) -> list[User]:
        """Return active users eligible for system alerts (admins/superusers)."""

        user_role_join = cast(
            BinaryExpression[bool], UserRoleAssignment.user_id == User.id
        )
        role_join = cast(BinaryExpression[bool], Role.id == UserRoleAssignment.role_id)
        active_column = cast(Any, User.is_active)
        superuser_column = cast(Any, User.is_superuser)
        statement = (
            select(User)
            .join(UserRoleAssignment, user_role_join, isouter=True)
            .join(Role, role_join, isouter=True)
            .where(active_column.is_(True))
            .where(
                or_(
                    superuser_column.is_(True),
                    func.lower(Role.slug) == "admin",
                )
            )
            .distinct()
            .order_by(User.email)
        )
        return list(session.exec(statement).all())


def format_alert_summary(alerts: Iterable[ScheduleAlert]) -> str:
    parts: list[str] = []
    for alert in alerts:
        overdue_minutes = int(alert.overdue.total_seconds() // 60)
        parts.append(
            f"{alert.task} overdue by {overdue_minutes} minutes (last run {alert.last_run_at.astimezone(UTC).isoformat()})"
        )
    return "; ".join(parts)


__all__ = [
    "ScheduleAlert",
    "ScheduleHealthService",
    "format_alert_summary",
]
