"""Tests for notification preference helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.models import NotificationSetting, User
from app.schemas.notifications import (
    NotificationChannelName,
    NotificationChannelUpdateRequest,
)
from app.services.notification_preferences import (
    SECRET_PLACEHOLDER,
    InvalidNotificationConfigError,
    NotificationChannelUnavailableError,
    UnknownNotificationChannelError,
    list_notification_channels_for_user,
    update_notification_channel_for_user,
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
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def _create_user(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_list_channels_includes_server_and_user_secrets(engine: Engine) -> None:
    settings = Settings(
        jwt_secret_key="super-secret-key",
        notify_email_enabled=True,
        smtp_host="smtp.local",
        notify_gotify_url=cast(AnyHttpUrl, "https://gotify.local"),
        notify_gotify_token="server-token",
        apprise_config_path="/etc/apprise.yml",
    )
    with Session(engine) as session:
        user = _create_user(session, "prefs@example.com")
        update_notification_channel_for_user(
            session,
            user,
            "pushover",
            NotificationChannelUpdateRequest(
                enabled=True,
                config={"api_token": "abc123", "user_key": "user456"},
            ),
            config=settings,
        )

        stored = session.exec(
            select(NotificationSetting).where(NotificationSetting.user_id == user.id)
        ).one()
        assert isinstance(stored.config, dict)
        assert stored.config.get("api_token") != "abc123"
        assert stored.config.get("user_key") != "user456"

        channels = list_notification_channels_for_user(session, user, config=settings)
        pushover = next(
            channel for channel in channels if channel.channel == "pushover"
        )
        assert pushover.enabled is True
        assert pushover.config["api_token"] == SECRET_PLACEHOLDER
        assert pushover.config["user_key"] == SECRET_PLACEHOLDER

        email = next(channel for channel in channels if channel.channel == "email")
        assert email.available is True
        gotify = next(channel for channel in channels if channel.channel == "gotify")
        assert gotify.available is True
        apprise = next(channel for channel in channels if channel.channel == "apprise")
        assert apprise.available is True


def test_update_channel_requires_required_credentials(engine: Engine) -> None:
    settings = Settings(jwt_secret_key="different-secret")
    with Session(engine) as session:
        user = _create_user(session, "missing@example.com")
        with pytest.raises(InvalidNotificationConfigError):
            update_notification_channel_for_user(
                session,
                user,
                "pushover",
                NotificationChannelUpdateRequest(
                    enabled=True,
                    config={"user_key": "only-user"},
                ),
                config=settings,
            )

        settings_with_defaults = Settings(
            jwt_secret_key="different-secret",
            notify_pushover_token="server-token",
            notify_pushover_user="server-user",
        )
        channel = update_notification_channel_for_user(
            session,
            user,
            "pushover",
            NotificationChannelUpdateRequest(enabled=True, config={}),
            config=settings_with_defaults,
        )
        assert channel.enabled is True
        assert channel.config == {}


def test_update_channel_validations(engine: Engine) -> None:
    settings = Settings(jwt_secret_key="validator-secret")
    with Session(engine) as session:
        user = _create_user(session, "validate@example.com")

        with pytest.raises(UnknownNotificationChannelError):
            update_notification_channel_for_user(
                session,
                user,
                cast(NotificationChannelName, "webhook"),
                NotificationChannelUpdateRequest(enabled=False, config={}),
                config=settings,
            )

        with pytest.raises(NotificationChannelUnavailableError):
            update_notification_channel_for_user(
                session,
                user,
                "gotify",
                NotificationChannelUpdateRequest(enabled=True, config={}),
                config=settings,
            )

        new_user = User(email="volatile@example.com")
        with pytest.raises(ValueError):
            list_notification_channels_for_user(session, new_user, config=settings)
