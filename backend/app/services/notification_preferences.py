from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from app.core.config import Settings, settings
from app.models import NotificationSetting, User
from app.schemas import (
    NotificationChannelName,
    NotificationChannelRead,
    NotificationChannelUpdateRequest,
    NotificationConfigField,
)


class NotificationPreferenceError(Exception):
    """Base error for notification preference operations."""


class UnknownNotificationChannelError(NotificationPreferenceError):
    """Raised when an unknown notification channel is requested."""

    def __init__(self, channel: str) -> None:
        super().__init__(f"Unknown notification channel: {channel}")
        self.channel = channel


class NotificationChannelUnavailableError(NotificationPreferenceError):
    """Raised when a channel is disabled via server configuration."""

    def __init__(self, channel: str, reason: str | None = None) -> None:
        message = reason or "Channel is disabled in server configuration."
        super().__init__(message)
        self.channel = channel
        self.reason = reason


class InvalidNotificationConfigError(NotificationPreferenceError):
    """Raised when config payload contains unexpected keys."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(slots=True)
class _ChannelDefinition:
    name: NotificationChannelName
    display_name: str
    description: str
    availability: Callable[[Settings], tuple[bool, str | None]]
    config_fields: tuple[NotificationConfigField, ...] = ()
    default_config_factory: Callable[[Settings], dict[str, str | None]] | None = None

    @property
    def allowed_config_keys(self) -> frozenset[str]:
        return frozenset(field.key for field in self.config_fields)


def _email_availability(config: Settings) -> tuple[bool, str | None]:
    if not config.notify_email_enabled:
        return False, "Email notifications are disabled in server configuration."
    if not config.smtp_host:
        return False, "SMTP host is not configured."
    return True, None


def _pushover_availability(config: Settings) -> tuple[bool, str | None]:
    if not config.notify_pushover_token:
        return False, "Pushover API token is not configured."
    return True, None


def _pushover_default_config(config: Settings) -> dict[str, str | None]:
    return {"user_key": config.notify_pushover_user}


def _gotify_availability(config: Settings) -> tuple[bool, str | None]:
    if not config.notify_gotify_url or not config.notify_gotify_token:
        return False, "Gotify server URL or token is missing."
    return True, None


def _apprise_availability(config: Settings) -> tuple[bool, str | None]:
    if not config.apprise_config_path:
        return False, "Apprise configuration path is not set."
    return True, None


_CHANNEL_DEFINITIONS: dict[NotificationChannelName, _ChannelDefinition] = {
    "email": _ChannelDefinition(
        name="email",
        display_name="Email",
        description="Send alerts using the configured SMTP server.",
        availability=_email_availability,
    ),
    "pushover": _ChannelDefinition(
        name="pushover",
        display_name="Pushover",
        description="Send push alerts to the Pushover mobile/desktop apps.",
        availability=_pushover_availability,
        config_fields=(
            NotificationConfigField(
                key="user_key",
                label="User key",
                description="Override the default Pushover user key from server settings.",
            ),
        ),
        default_config_factory=_pushover_default_config,
    ),
    "gotify": _ChannelDefinition(
        name="gotify",
        display_name="Gotify",
        description="Send notifications to a Gotify server.",
        availability=_gotify_availability,
    ),
    "apprise": _ChannelDefinition(
        name="apprise",
        display_name="Apprise",
        description="Use Apprise configuration to broadcast alerts to multiple providers.",
        availability=_apprise_availability,
    ),
}


def _load_settings(session: Session, user_id: int) -> dict[str, NotificationSetting]:
    user_condition = cast(
        ColumnElement[bool],
        NotificationSetting.user_id == user_id,
    )
    statement = select(NotificationSetting).where(user_condition)
    records = session.exec(statement).all()
    return {record.channel: record for record in records}


def _merge_config(
    definition: _ChannelDefinition,
    record: NotificationSetting | None,
    config_obj: Settings,
) -> dict[str, str | None]:
    keys = definition.allowed_config_keys
    base: dict[str, str | None] = {}
    if definition.default_config_factory is not None:
        defaults = definition.default_config_factory(config_obj)
        base.update({k: defaults.get(k) for k in keys})
    if record and record.config:
        for key in keys:
            if key in record.config:
                value = record.config[key]
                base[key] = None if value in (None, "") else str(value)
    return {key: value for key, value in base.items() if value is not None}


def _build_channel_read(
    definition: _ChannelDefinition,
    available: bool,
    reason: str | None,
    record: NotificationSetting | None,
    config_obj: Settings,
) -> NotificationChannelRead:
    config = _merge_config(definition, record, config_obj) if available else {}
    enabled = bool(record.enabled) if record is not None else True
    if not available:
        enabled = False
    return NotificationChannelRead(
        channel=definition.name,
        display_name=definition.display_name,
        description=definition.description,
        available=available,
        unavailable_reason=reason,
        enabled=enabled,
        config=config,
        config_fields=list(definition.config_fields),
    )


def list_notification_channels_for_user(
    session: Session,
    user: User,
    *,
    config: Settings = settings,
) -> list[NotificationChannelRead]:
    if user.id is None:
        raise ValueError("User must be persisted before listing channels")
    records = _load_settings(session, user.id)
    channels: list[NotificationChannelRead] = []
    for definition in _CHANNEL_DEFINITIONS.values():
        available, reason = definition.availability(config)
        record = records.get(definition.name)
        channels.append(
            _build_channel_read(
                definition,
                available,
                reason,
                record,
                config,
            )
        )
    return channels


def _validate_config(
    definition: _ChannelDefinition,
    payload: NotificationChannelUpdateRequest,
) -> dict[str, str | int | float | bool | None]:
    provided = payload.config or {}
    unknown = sorted(set(provided.keys()) - definition.allowed_config_keys)
    if unknown:
        joined = ", ".join(unknown)
        raise InvalidNotificationConfigError(f"Unknown config keys: {joined}")
    sanitized: dict[str, str | int | float | bool | None] = {}
    for key in definition.allowed_config_keys:
        if key not in provided:
            continue
        value = provided[key]
        sanitized[key] = None if value in (None, "") else str(value)
    return sanitized


def update_notification_channel_for_user(
    session: Session,
    user: User,
    channel: NotificationChannelName,
    payload: NotificationChannelUpdateRequest,
    *,
    config: Settings = settings,
) -> NotificationChannelRead:
    if user.id is None:
        raise ValueError("User must be persisted before updating channels")
    definition = _CHANNEL_DEFINITIONS.get(channel)
    if definition is None:
        raise UnknownNotificationChannelError(channel)

    available, reason = definition.availability(config)
    if not available:
        raise NotificationChannelUnavailableError(channel, reason)

    sanitized_config = _validate_config(definition, payload)

    user_condition = cast(
        ColumnElement[bool],
        NotificationSetting.user_id == user.id,
    )
    channel_condition = cast(
        ColumnElement[bool],
        NotificationSetting.channel == channel,
    )
    statement = (
        select(NotificationSetting).where(user_condition).where(channel_condition)
    )
    record = session.exec(statement).first()
    if record is None:
        record = NotificationSetting(user_id=user.id, channel=channel)

    record.enabled = payload.enabled
    record.config = sanitized_config or None
    session.add(record)
    session.commit()
    session.refresh(record)

    return _build_channel_read(
        definition,
        available,
        reason,
        record,
        config,
    )


__all__ = [
    "list_notification_channels_for_user",
    "update_notification_channel_for_user",
    "NotificationPreferenceError",
    "UnknownNotificationChannelError",
    "NotificationChannelUnavailableError",
    "InvalidNotificationConfigError",
]
