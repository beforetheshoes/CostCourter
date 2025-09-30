from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import TagCreate, TagMergeRequest, TagMergeResponse, TagRead, TagUpdate
from app.services import catalog

router = APIRouter()


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TagRead:
    return catalog.create_tag(session, payload, owner=current_user)


@router.get("", response_model=list[TagRead])
def list_tags(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, min_length=1, max_length=255),
    owner_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[TagRead]:
    normalized_search = search.strip() if search and search.strip() else None
    return catalog.list_tags(
        session,
        owner=current_user,
        limit=limit,
        offset=offset,
        search=normalized_search,
        for_user_id=owner_id,
    )


@router.patch("/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TagRead:
    return catalog.update_tag(session, tag_id, payload, owner=current_user)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    catalog.delete_tag(session, tag_id, owner=current_user)


@router.post("/merge", response_model=TagMergeResponse)
def merge_tags_endpoint(
    payload: TagMergeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TagMergeResponse:
    return catalog.merge_tags(session, payload, owner=current_user)
