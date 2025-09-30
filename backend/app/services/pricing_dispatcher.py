from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from celery.result import AsyncResult

from app.tasks.pricing import (
    update_all_products_task,
    update_product_prices_task,
)


@dataclass(slots=True)
class PricingJobDispatch:
    """Representation of a queued pricing task."""

    task_id: str
    task_name: str
    status: str = "queued"
    eta: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status,
        }
        if self.eta is not None:
            payload["eta"] = self.eta
        return payload


class PricingDispatcher:
    """Dispatch pricing refresh work to Celery tasks."""

    def queue_product_refresh(
        self,
        *,
        product_id: int,
        logging: bool,
        audit_actor_id: int | None,
        audit_ip: str | None,
    ) -> PricingJobDispatch:
        result = update_product_prices_task.delay(
            product_id=product_id,
            logging=logging,
            audit_actor_id=audit_actor_id,
            audit_ip=audit_ip,
        )
        return self._result_from_async(result, update_product_prices_task.name)

    def queue_all_refresh(
        self,
        *,
        logging: bool,
        owner_id: int | None,
        audit_actor_id: int | None,
        audit_ip: str | None,
    ) -> PricingJobDispatch:
        result = update_all_products_task.delay(
            logging=logging,
            owner_id=owner_id,
            audit_actor_id=audit_actor_id,
            audit_ip=audit_ip,
        )
        return self._result_from_async(result, update_all_products_task.name)

    @staticmethod
    def _result_from_async(result: AsyncResult, task_name: str) -> PricingJobDispatch:
        status = getattr(result, "status", None) or getattr(result, "state", None)
        eta = getattr(result, "eta", None)
        if callable(eta):
            try:
                eta = eta()
            except TypeError:
                eta = None
        task_id = str(getattr(result, "id", getattr(result, "task_id", "")))
        return PricingJobDispatch(
            task_id=task_id,
            task_name=task_name,
            status=status or "queued",
            eta=eta if isinstance(eta, datetime) else None,
        )


DispatcherFactory = Callable[[], PricingDispatcher]

_dispatcher_factory: DispatcherFactory | None = None


def set_pricing_dispatcher_factory(factory: DispatcherFactory | None) -> None:
    global _dispatcher_factory
    _dispatcher_factory = factory


def get_pricing_dispatcher() -> PricingDispatcher:
    if _dispatcher_factory is not None:
        return _dispatcher_factory()
    return PricingDispatcher()
