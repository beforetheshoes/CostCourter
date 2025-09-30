from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, TypeVar

from celery import shared_task
from sqlmodel import Session

from app.core.database import engine
from app.services.price_fetcher import (
    PriceFetcherService,
    PriceFetchSummary,
    get_price_fetcher_service,
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


@contextmanager
def _default_session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


_session_scope: SessionFactory = _default_session_scope


def set_task_session_factory(factory: SessionFactory | None) -> None:
    global _session_scope
    _session_scope = factory or _default_session_scope


T = TypeVar("T")


def _run_with_session(func: Callable[[Session, PriceFetcherService], T]) -> T:
    service = get_price_fetcher_service()
    with _session_scope() as session:
        return func(session, service)


def _summary_to_dict(summary: PriceFetchSummary) -> dict[str, Any]:
    return summary.to_dict()


@shared_task(name="pricing.update_product_prices")
def update_product_prices_task(
    *,
    product_id: int,
    logging: bool = False,
    owner_id: int | None = None,
    audit_actor_id: int | None = None,
    audit_ip: str | None = None,
) -> dict[str, Any]:
    def runner(session: Session, service: PriceFetcherService) -> dict[str, Any]:
        summary = service.update_product_prices(
            session,
            product_id,
            logging=logging,
            owner_id=owner_id,
            audit_actor_id=audit_actor_id,
            audit_ip=audit_ip,
        )
        return _summary_to_dict(summary)

    return _run_with_session(runner)


@shared_task(name="pricing.update_all_products")
def update_all_products_task(
    *,
    logging: bool = False,
    owner_id: int | None = None,
    audit_actor_id: int | None = None,
    audit_ip: str | None = None,
) -> dict[str, Any]:
    def runner(session: Session, service: PriceFetcherService) -> dict[str, Any]:
        summary = service.update_all_products(
            session,
            logging=logging,
            owner_id=owner_id,
            audit_actor_id=audit_actor_id,
            audit_ip=audit_ip,
        )
        return _summary_to_dict(summary)

    return _run_with_session(runner)
