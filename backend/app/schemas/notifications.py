from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NotificationConfigField(BaseModel):
    key: str
    label: str
    description: str | None = None
    required: bool = False
    secret: bool = False
    placeholder: str | None = None


class NotificationChannelRead(BaseModel):
    channel: str
    display_name: str
    description: str | None = None
    available: bool
    unavailable_reason: str | None = None
    enabled: bool
    config: dict[str, str | None]
    config_fields: list[NotificationConfigField]


class NotificationChannelListResponse(BaseModel):
    channels: list[NotificationChannelRead]


class NotificationChannelUpdateRequest(BaseModel):
    enabled: bool
    config: dict[str, str | None] | None = None


NotificationChannelName = Literal["email", "pushover", "gotify", "apprise"]


__all__ = [
    "NotificationChannelListResponse",
    "NotificationChannelRead",
    "NotificationChannelUpdateRequest",
    "NotificationChannelName",
    "NotificationConfigField",
]
