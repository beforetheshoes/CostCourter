from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import CatalogBackup, CatalogImportResponse
from app.services import catalog_backup

router = APIRouter()


@router.get("/products", response_model=CatalogBackup)
def export_products_backup(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CatalogBackup:
    return catalog_backup.export_catalog_backup(session, owner=current_user)


@router.post(
    "/products",
    response_model=CatalogImportResponse,
    status_code=status.HTTP_200_OK,
)
def import_products_backup(
    payload: CatalogBackup,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CatalogImportResponse:
    return catalog_backup.import_catalog_backup(session, payload, owner=current_user)
