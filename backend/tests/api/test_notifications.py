from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.core.config import settings
from app.models import NotificationSetting, User
from app.services.notification_preferences import (
    InvalidNotificationConfigError,
    NotificationChannelUnavailableError,
    UnknownNotificationChannelError,
)


@pytest.fixture(name="current_user")
def current_user_fixture(engine: Engine) -> User:
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.email == "test.user@example.com")
        ).first()
        assert user is not None
        session.expunge(user)
        return user


def _set_settings(**values: Any) -> dict[str, Any]:
    previous = {}
    for key, value in values.items():
        previous[key] = getattr(settings, key)
        setattr(settings, key, value)
    return previous


def _restore_settings(previous: dict[str, Any]) -> None:
    for key, value in previous.items():
        setattr(settings, key, value)


def test_list_notification_channels_returns_user_settings(
    client: TestClient,
    engine: Engine,
    current_user: User,
) -> None:
    previous = _set_settings(
        notify_email_enabled=True,
        smtp_host="smtp.example.com",
        notify_pushover_token="pushover-token",
        notify_pushover_user="default-user",
        notify_gotify_url=None,
        notify_gotify_token=None,
        apprise_config_path=None,
    )
    try:
        with Session(engine) as session:
            session.add(
                NotificationSetting(
                    user_id=current_user.id,
                    channel="pushover",
                    enabled=False,
                    config={"user_key": "override-user"},
                )
            )
            session.commit()

        response = client.get("/api/notifications/channels")
        assert response.status_code == 200
        payload = response.json()
        assert payload["channels"], payload
        channels = {entry["channel"]: entry for entry in payload["channels"]}

        email = channels["email"]
        assert email["available"] is True
        assert email["enabled"] is True
        assert email["config"] == {}
        assert email["config_fields"] == []

        pushover = channels["pushover"]
        assert pushover["available"] is True
        assert pushover["enabled"] is False
        assert pushover["config"] == {"user_key": "override-user"}
        assert pushover["config_fields"]
        assert pushover["config_fields"][0]["key"] == "user_key"
        assert pushover["config_fields"][0]["required"] is False

        gotify = channels["gotify"]
        assert gotify["available"] is False
        assert gotify["enabled"] is False
    finally:
        _restore_settings(previous)


def test_update_notification_channel_upserts_setting(
    client: TestClient,
    engine: Engine,
    current_user: User,
) -> None:
    previous = _set_settings(
        notify_email_enabled=True,
        smtp_host="smtp.example.com",
    )
    try:
        response = client.put(
            "/api/notifications/channels/email",
            json={"enabled": False, "config": None},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["channel"] == "email"
        assert body["enabled"] is False

        with Session(engine) as session:
            setting = session.exec(
                select(NotificationSetting)
                .where(NotificationSetting.user_id == current_user.id)
                .where(NotificationSetting.channel == "email")
            ).one()
        assert setting.enabled is False
        assert setting.config is None
    finally:
        _restore_settings(previous)


def test_update_notification_channel_pushover_persists_config(
    client: TestClient,
    engine: Engine,
    current_user: User,
) -> None:
    previous = _set_settings(
        notify_pushover_token="pushover-token",
        notify_pushover_user=None,
    )
    try:
        response = client.put(
            "/api/notifications/channels/pushover",
            json={"enabled": True, "config": {"user_key": "override"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["config"] == {"user_key": "override"}

        with Session(engine) as session:
            setting = session.exec(
                select(NotificationSetting)
                .where(NotificationSetting.user_id == current_user.id)
                .where(NotificationSetting.channel == "pushover")
            ).one()
        assert setting.enabled is True
        assert setting.config == {"user_key": "override"}
    finally:
        _restore_settings(previous)


def test_update_notification_channel_requires_available_channel(
    client: TestClient,
) -> None:
    previous = _set_settings(notify_pushover_token=None)
    try:
        response = client.put(
            "/api/notifications/channels/pushover",
            json={"enabled": True, "config": {"user_key": "abc"}},
        )
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"].lower()
    finally:
        _restore_settings(previous)


def test_update_notification_channel_rejects_unknown_config_keys(
    client: TestClient,
) -> None:
    previous = _set_settings(notify_pushover_token="token")
    try:
        response = client.put(
            "/api/notifications/channels/pushover",
            json={"enabled": True, "config": {"token": "bad"}},
        )
        assert response.status_code == 422
        assert "token" in response.json()["detail"]
    finally:
        _restore_settings(previous)


def test_list_notification_channels_handles_value_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*_: Any, **__: Any) -> None:
        raise ValueError("invalid state")

    monkeypatch.setattr(
        "app.api.endpoints.notifications.list_notification_channels_for_user",
        _raise,
    )

    response = client.get("/api/notifications/channels")
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid state"


@pytest.mark.parametrize(
    ("factory", "status_code"),
    [
        (lambda: UnknownNotificationChannelError("fax"), 404),
        (
            lambda: NotificationChannelUnavailableError("email", reason="maintenance"),
            400,
        ),
        (lambda: InvalidNotificationConfigError("bad config"), 422),
        (lambda: ValueError("bad request"), 400),
    ],
)
def test_update_notification_channel_maps_service_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[], Exception],
    status_code: int,
) -> None:
    def _raise(*_: Any, **__: Any) -> None:
        raise factory()

    monkeypatch.setattr(
        "app.api.endpoints.notifications.update_notification_channel_for_user",
        _raise,
    )

    response = client.put(
        "/api/notifications/channels/email",
        json={"enabled": True, "config": None},
    )
    assert response.status_code == status_code
    assert response.json()["detail"]
