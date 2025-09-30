from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.api.deps import (
    HttpClientFactory,
    get_current_user,
    get_scraper_client_factory,
)
from app.core.config import settings
from app.core.database import get_session
from app.models import User, ensure_core_model_mappings
from app.schemas import (
    StoreCreate,
    StoreQuickAddRequest,
    StoreQuickAddResponse,
    StoreRead,
    StoreUpdate,
)
from app.services import catalog
from app.services.product_quick_add import quick_add_store

router = APIRouter()


@router.post("", response_model=StoreRead, status_code=status.HTTP_201_CREATED)
def create_store(
    payload: StoreCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StoreRead:
    return catalog.create_store(session, payload, owner=current_user)


@router.post(
    "/quick-add",
    response_model=StoreQuickAddResponse,
    status_code=status.HTTP_201_CREATED,
)
def quick_add_store_endpoint(
    payload: StoreQuickAddRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    scraper_client_factory: HttpClientFactory = Depends(get_scraper_client_factory),
) -> StoreQuickAddResponse:
    ensure_core_model_mappings()
    result = quick_add_store(
        session,
        owner=current_user,
        website=payload.website,
        currency=payload.currency,
        locale=payload.locale,
        scraper_base_url=settings.scraper_base_url,
        http_client_factory=scraper_client_factory,
    )
    store_payload = StoreRead.model_validate(result.store)
    return StoreQuickAddResponse(
        store=store_payload,
        warnings=result.warnings,
        created=result.created,
    )


@router.get("", response_model=list[StoreRead])
def list_stores(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, min_length=1, max_length=255),
    active: bool | None = Query(None),
    owner_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[StoreRead]:
    normalized_search = search.strip() if search and search.strip() else None
    return catalog.list_stores(
        session,
        owner=current_user,
        limit=limit,
        offset=offset,
        search=normalized_search,
        active=active,
        for_user_id=owner_id,
    )


@router.patch("/{store_id}", response_model=StoreRead)
def update_store(
    store_id: int,
    payload: StoreUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StoreRead:
    return catalog.update_store(session, store_id, payload, owner=current_user)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_store(
    store_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    catalog.delete_store(session, store_id, owner=current_user)
