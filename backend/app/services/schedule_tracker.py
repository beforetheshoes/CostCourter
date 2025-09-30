from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlmodel import Session, select

from app.models import AppSetting
from app.models.base import utcnow

_LOGGER = structlog.get_logger(__name__)

_PREFIX = "schedule.last_run."


def _setting_key(task_name: str) -> str:
    return f"{_PREFIX}{task_name}"


def record_schedule_run(
    session: Session,
    task_name: str,
    *,
    timestamp: datetime | None = None,
) -> datetime:
    """Persist the timestamp for the most recent execution of ``task_name``.

    The timestamp is normalised to UTC before persistence. The updated value is
    committed immediately to ensure observability even if the caller rolls back
    subsequent work.
    """

    when = timestamp or utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    iso_value = when.astimezone(UTC).isoformat()
    key = _setting_key(task_name)

    setting = session.get(AppSetting, key)
    description = f"Last run timestamp for {task_name}"
    if setting is None:
        setting = AppSetting(key=key, value=iso_value, description=description)
    else:
        setting.value = iso_value
        if not setting.description:
            setting.description = description
    session.add(setting)
    session.commit()
    session.refresh(setting)
    _LOGGER.info("schedule.run.recorded", task=task_name, timestamp=iso_value)
    return when


def fetch_last_run_map(session: Session) -> dict[str, datetime]:
    """Return a mapping of task name to the last recorded run timestamp."""

    rows = session.exec(select(AppSetting)).all()
    results: dict[str, datetime] = {}
    for row in rows:
        if not row.key.startswith(_PREFIX) or not row.value:
            continue
        task_name = row.key[len(_PREFIX) :]
        try:
            parsed = datetime.fromisoformat(row.value)
        except ValueError:
            _LOGGER.warning(
                "schedule.run.parse_failed",
                task=task_name,
                value=row.value,
            )
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        results[task_name] = parsed.astimezone(UTC)
    return results


__all__ = ["record_schedule_run", "fetch_last_run_map"]
