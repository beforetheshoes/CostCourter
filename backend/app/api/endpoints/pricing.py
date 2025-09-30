from __future__ import annotations

import json
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_session
from app.models import User
from app.schemas import (
    PriceFetchJobQueuedRead,
    PriceFetchSummaryRead,
    PricingScheduleEntry,
    PricingScheduleRead,
)
from app.services.price_fetcher import get_price_fetcher_service
from app.services.pricing_dispatcher import get_pricing_dispatcher
from app.services.pricing_schedule import (
    describe_pricing_schedule,
    resolve_schedule_path,
)

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    client = request.client
    return client.host if client is not None else None


@router.post(
    "/products/{product_id}/fetch",
    response_model=PriceFetchSummaryRead | PriceFetchJobQueuedRead,
)
def fetch_product_prices(
    product_id: int,
    request: Request,
    logging: bool = False,
    enqueue: bool = Query(
        default=False,
        description="Queue the refresh on the pricing worker instead of running inline.",
    ),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> PriceFetchSummaryRead | JSONResponse:
    audit_ip = _client_ip(request)

    if enqueue:
        dispatcher = get_pricing_dispatcher()
        job = dispatcher.queue_product_refresh(
            product_id=product_id,
            logging=logging,
            audit_actor_id=current_user.id,
            audit_ip=audit_ip,
        )
        payload = PriceFetchJobQueuedRead.model_validate(job.to_dict()).model_dump(
            exclude_none=True
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)

    service = get_price_fetcher_service()
    summary = service.update_product_prices(
        session,
        product_id,
        logging=logging,
        audit_actor_id=current_user.id,
        audit_ip=audit_ip,
    )
    return PriceFetchSummaryRead.model_validate(summary)


@router.post(
    "/products/fetch-all",
    response_model=PriceFetchSummaryRead | PriceFetchJobQueuedRead,
)
def fetch_all_product_prices(
    request: Request,
    logging: bool = False,
    enqueue: bool = Query(
        default=False,
        description="Queue the refresh on the pricing worker instead of running inline.",
    ),
    owner_id: int | None = Query(
        default=None,
        ge=1,
        description="Scope the refresh to products owned by this user.",
    ),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> PriceFetchSummaryRead | JSONResponse:
    audit_ip = _client_ip(request)

    target_owner_id = owner_id
    if target_owner_id is not None:
        target_user = session.get(User, target_owner_id)
        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

    if enqueue:
        dispatcher = get_pricing_dispatcher()
        job = dispatcher.queue_all_refresh(
            logging=logging,
            owner_id=target_owner_id,
            audit_actor_id=current_user.id,
            audit_ip=audit_ip,
        )
        payload = PriceFetchJobQueuedRead.model_validate(job.to_dict()).model_dump(
            exclude_none=True
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)

    service = get_price_fetcher_service()
    summary = service.update_all_products(
        session,
        logging=logging,
        owner_id=target_owner_id,
        audit_actor_id=current_user.id,
        audit_ip=audit_ip,
    )
    return PriceFetchSummaryRead.model_validate(summary)


@router.get("/schedule", response_model=PricingScheduleRead)
def read_pricing_schedule(
    session: Session = Depends(get_session),
) -> PricingScheduleRead:
    """Expose the configured Celery beat schedule with last/next run metadata."""

    entries = [
        PricingScheduleEntry(**entry) for entry in describe_pricing_schedule(session)
    ]
    return PricingScheduleRead(entries=entries)


@router.put("/schedule", response_model=PricingScheduleRead)
def update_pricing_schedule(
    body: PricingScheduleRead = Body(...),
    session: Session = Depends(get_session),
    _: object = Depends(require_admin),
) -> PricingScheduleRead:
    schedule_path = resolve_schedule_path(settings.celery_beat_schedule_path)
    if not schedule_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No schedule path configured",
        )
    mapping: dict[str, dict[str, Any]] = {}
    for e in body.entries:
        entry: dict[str, Any] = {"task": e.task}
        if e.schedule is not None:
            entry["schedule"] = e.schedule
        if e.args is not None:
            entry["args"] = e.args
        if e.kwargs is not None:
            entry["kwargs"] = e.kwargs
        if e.enabled is not None:
            entry["enabled"] = e.enabled
        for cron_field in (
            "minute",
            "hour",
            "day_of_week",
            "day_of_month",
            "month_of_year",
        ):
            value = getattr(e, cron_field)
            if value is not None:
                entry[cron_field] = value
        mapping[e.name] = entry

    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    with schedule_path.open("w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2)

    # Return canonicalised content with updated metadata
    entries = [
        PricingScheduleEntry(**entry) for entry in describe_pricing_schedule(session)
    ]
    return PricingScheduleRead(entries=entries)
