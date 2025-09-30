from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import get_current_user, get_session
from app.models import User
from app.schemas import (
    NotificationChannelListResponse,
    NotificationChannelName,
    NotificationChannelRead,
    NotificationChannelUpdateRequest,
)
from app.services.notification_preferences import (
    InvalidNotificationConfigError,
    NotificationChannelUnavailableError,
    UnknownNotificationChannelError,
    list_notification_channels_for_user,
    update_notification_channel_for_user,
)

router = APIRouter()


@router.get(
    "/channels",
    response_model=NotificationChannelListResponse,
)
def list_notification_channels(
    *,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationChannelListResponse:
    try:
        channels = list_notification_channels_for_user(session, user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return NotificationChannelListResponse(channels=channels)


@router.put(
    "/channels/{channel}",
    response_model=NotificationChannelRead,
)
def update_notification_channel(
    *,
    channel: NotificationChannelName,
    payload: NotificationChannelUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationChannelRead:
    try:
        return update_notification_channel_for_user(
            session,
            user,
            channel,
            payload,
        )
    except UnknownNotificationChannelError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except NotificationChannelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.reason or str(exc),
        ) from exc
    except InvalidNotificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = [
    "router",
    "list_notification_channels",
    "update_notification_channel",
]
