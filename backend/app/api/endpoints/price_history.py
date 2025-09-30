from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import PriceHistoryCreate, PriceHistoryRead
from app.services import catalog

router = APIRouter()


@router.post("", response_model=PriceHistoryRead, status_code=status.HTTP_201_CREATED)
def create_price_history(
    payload: PriceHistoryCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PriceHistoryRead:
    return catalog.create_price_history(session, payload, owner=current_user)


@router.get("", response_model=list[PriceHistoryRead])
def list_price_history(
    product_id: int | None = Query(default=None),
    product_url_id: int | None = Query(default=None),
    owner_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[PriceHistoryRead]:
    return catalog.list_price_history(
        session,
        owner=current_user,
        product_id=product_id,
        product_url_id=product_url_id,
        for_user_id=owner_id,
    )
