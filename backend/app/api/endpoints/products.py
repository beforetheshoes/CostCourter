from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import (
    ProductBulkUpdateRequest,
    ProductBulkUpdateResponse,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services import catalog

router = APIRouter()


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductRead:
    return catalog.create_product(session, payload, owner=current_user)


@router.get("", response_model=list[ProductRead])
def list_products(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, min_length=1, max_length=255),
    is_active: bool | None = Query(None),
    tag: str | None = Query(None, min_length=1, max_length=255),
    owner_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[ProductRead]:
    normalized_search = search.strip() if search and search.strip() else None
    normalized_tag = tag.strip() if tag and tag.strip() else None
    return catalog.list_products(
        session,
        owner=current_user,
        limit=limit,
        offset=offset,
        search=normalized_search,
        is_active=is_active,
        tag=normalized_tag,
        for_user_id=owner_id,
    )


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductRead:
    return catalog.get_product(session, product_id, owner=current_user)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductRead:
    return catalog.update_product(session, product_id, payload, owner=current_user)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    catalog.delete_product(session, product_id, owner=current_user)


@router.post("/bulk-update", response_model=ProductBulkUpdateResponse)
def bulk_update_products_endpoint(
    payload: ProductBulkUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductBulkUpdateResponse:
    return catalog.bulk_update_products(session, payload, owner=current_user)
