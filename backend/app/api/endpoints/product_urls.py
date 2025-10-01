from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import AnyHttpUrl
from sqlmodel import Session

from app.api.deps import (
    HttpClientFactory,
    PriceRefreshDispatcher,
    get_current_user,
    get_price_refresh_dispatcher,
    get_scraper_client_factory,
)
from app.core.config import settings
from app.core.database import get_session
from app.models import Product, User, ensure_core_model_mappings
from app.schemas import (
    BulkImportCreatedURL,
    BulkImportRequest,
    BulkImportResponse,
    BulkImportSkipped,
    ProductURLCreate,
    ProductURLRead,
    ProductURLRefreshResponse,
    ProductURLUpdate,
)
from app.services import catalog
from app.services.product_bulk_import import (
    ImportItemPayload,
)
from app.services.product_bulk_import import (
    bulk_import_product_urls as perform_bulk_import,
)
from app.services.product_quick_add import HTTP_URL_ADAPTER, quick_add_product

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    client = request.client
    return client.host if client is not None else None


@router.post("", response_model=ProductURLRead, status_code=status.HTTP_201_CREATED)
def create_product_url(
    payload: ProductURLCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductURLRead:
    return catalog.create_product_url(session, payload, owner=current_user)


@router.get("", response_model=list[ProductURLRead])
def list_product_urls(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    product_id: int | None = Query(None, ge=1),
    store_id: int | None = Query(None, ge=1),
    active: bool | None = Query(None),
    owner_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[ProductURLRead]:
    return catalog.list_product_urls(
        session,
        owner=current_user,
        limit=limit,
        offset=offset,
        product_id=product_id,
        store_id=store_id,
        active=active,
        for_user_id=owner_id,
    )


@router.patch("/{product_url_id}", response_model=ProductURLRead)
def update_product_url(
    product_url_id: int,
    payload: ProductURLUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ProductURLRead:
    return catalog.update_product_url(
        session, product_url_id, payload, owner=current_user
    )


@router.delete("/{product_url_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_url(
    product_url_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    catalog.delete_product_url(session, product_url_id, owner=current_user)


@router.post("/quick-add", status_code=status.HTTP_201_CREATED)
def quick_add_by_url(
    *,
    url: AnyHttpUrl = Body(..., embed=True),
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    price_refresh_dispatcher: PriceRefreshDispatcher = Depends(
        get_price_refresh_dispatcher
    ),
    scraper_client_factory: HttpClientFactory = Depends(get_scraper_client_factory),
) -> dict[str, Any]:
    """Create minimal store/product/url by scraping metadata for the given URL."""

    ensure_core_model_mappings()

    try:
        result = quick_add_product(
            session,
            owner=current_user,
            url=str(url),
            scraper_base_url=settings.scraper_base_url,
            price_refresh=price_refresh_dispatcher.enqueue,
            http_client_factory=scraper_client_factory,
            audit_ip=_client_ip(request),
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive handling
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to quick-add product",
        ) from exc

    return {
        "product_id": result.product_id,
        "product_url_id": result.product_url_id,
        "store_id": result.store_id,
        "title": result.title,
        "price": result.price,
        "currency": result.currency,
        "image": result.image,
        "warnings": result.warnings,
    }


@router.post(
    "/{product_url_id}/refresh",
    response_model=ProductURLRefreshResponse,
    status_code=status.HTTP_200_OK,
)
def refresh_product_url_metadata_endpoint(
    product_url_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    scraper_client_factory: HttpClientFactory = Depends(get_scraper_client_factory),
) -> ProductURLRefreshResponse:
    ensure_core_model_mappings()
    return catalog.refresh_product_url_metadata(
        session,
        owner=current_user,
        product_url_id=product_url_id,
        scraper_base_url=settings.scraper_base_url,
        http_client_factory=scraper_client_factory,
    )


@router.post("/bulk-import", response_model=BulkImportResponse)
def bulk_import_product_urls_endpoint(
    request: BulkImportRequest,
    response: Response,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    price_refresh_dispatcher: PriceRefreshDispatcher = Depends(
        get_price_refresh_dispatcher
    ),
    scraper_client_factory: HttpClientFactory = Depends(get_scraper_client_factory),
) -> BulkImportResponse:
    ensure_core_model_mappings()

    target_product: Product | None = None
    if request.product_id is not None:
        target_product = session.get(Product, request.product_id)
        if target_product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )
        if not current_user.is_superuser and target_product.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot import URLs for another user's product",
            )

    items = [
        ImportItemPayload(url=str(item.url), set_primary=item.set_primary)
        for item in request.items
    ]

    result = perform_bulk_import(
        session,
        current_user,
        items=items,
        search_query=request.search_query,
        product=target_product,
        scraper_base_url=settings.scraper_base_url,
        http_client_factory=scraper_client_factory,
        price_refresh=(
            price_refresh_dispatcher.enqueue if request.enqueue_refresh else None
        ),
        audit_ip=_client_ip(raw_request),
    )

    response.status_code = (
        status.HTTP_201_CREATED if result.created_product else status.HTTP_200_OK
    )

    if result.product.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk import completed without a persisted product identifier",
        )
    created_payloads = [
        BulkImportCreatedURL(
            product_url_id=entry.product_url_id,
            store_id=entry.store_id,
            url=HTTP_URL_ADAPTER.validate_python(entry.url),
            is_primary=entry.is_primary,
            price=entry.price,
            currency=entry.currency,
        )
        for entry in result.created_urls
    ]
    skipped_payloads = [
        BulkImportSkipped(
            url=HTTP_URL_ADAPTER.validate_python(skipped_url), reason=reason
        )
        for skipped_url, reason in result.skipped
    ]

    return BulkImportResponse(
        product_id=result.product.id,
        product_name=result.product.name,
        product_slug=result.product.slug,
        created_product=result.created_product,
        created_urls=created_payloads,
        skipped=skipped_payloads,
    )
