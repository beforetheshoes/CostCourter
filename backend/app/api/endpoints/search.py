from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import SearchResponse
from app.services.search import (
    MAX_ALLOWED_PAGES,
    SearchExecutionError,
    SearxSearchService,
)

router = APIRouter()
_search_service = SearxSearchService()


@router.get("", response_model=SearchResponse)
def search_products(
    query: str = Query(..., min_length=1, max_length=255, description="Search query"),
    *,
    force_refresh: bool = Query(
        False, description="Bypass the cached response and query SearXNG"
    ),
    pages: int | None = Query(
        None,
        ge=1,
        le=MAX_ALLOWED_PAGES,
        description="Override configured page count for the request",
    ),
    owner_id: int | None = Query(
        None,
        ge=1,
        description="Scope store mapping to a specific user (admin only)",
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SearchResponse:
    target_user: User = current_user
    if owner_id is not None:
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can search on behalf of another user",
            )
        persisted = session.get(User, owner_id)
        if persisted is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requested user not found",
            )
        target_user = persisted

    try:
        return _search_service.search(
            session,
            query=query,
            owner=target_user,
            force_refresh=force_refresh,
            max_pages=pages,
        )
    except SearchExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
