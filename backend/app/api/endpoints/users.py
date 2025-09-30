from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas import UserCreate, UserRead
from app.services import user as user_service

router = APIRouter()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, session: Session = Depends(get_session)
) -> UserRead:
    return user_service.create_user(session, payload)


@router.get("", response_model=list[UserRead])
def list_users(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, min_length=1, max_length=255),
    role: str | None = Query(None, min_length=1, max_length=64),
    session: Session = Depends(get_session),
) -> list[UserRead]:
    normalized_search = search.strip() if search and search.strip() else None
    normalized_role = role.strip() if role and role.strip() else None
    return user_service.list_users(
        session,
        limit=limit,
        offset=offset,
        search=normalized_search,
        role_slug=normalized_role,
    )
