from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.pricing_dispatcher import (
    PricingDispatcher,
    PricingJobDispatch,
    get_pricing_dispatcher,
    set_pricing_dispatcher_factory,
)


class _ResultStub:
    def __init__(
        self, *, task_id: str = "task-id", status: str | None = "STARTED"
    ) -> None:
        self.id = task_id
        self.status = status
        self.eta = lambda: datetime.now(UTC) + timedelta(minutes=5)


def test_pricing_job_dispatch_to_dict_includes_eta() -> None:
    eta = datetime.now(UTC)
    dispatch = PricingJobDispatch(
        task_id="abc", task_name="test", status="done", eta=eta
    )
    payload = dispatch.to_dict()
    assert payload == {
        "task_id": "abc",
        "task_name": "test",
        "status": "done",
        "eta": eta,
    }


def test_queue_product_refresh_returns_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, dict[str, object]] = {}

    class _Task:
        name = "pricing.update_product_prices"

        def delay(self, **kwargs: object) -> _ResultStub:
            captured["kwargs"] = kwargs
            return _ResultStub(task_id="product", status="SUCCESS")

    monkeypatch.setattr(
        "app.services.pricing_dispatcher.update_product_prices_task",
        _Task(),
    )

    dispatcher = PricingDispatcher()
    dispatch = dispatcher.queue_product_refresh(
        product_id=1,
        logging=True,
        audit_actor_id=5,
        audit_ip="127.0.0.1",
    )

    assert dispatch.task_id == "product"
    assert dispatch.status == "SUCCESS"
    assert dispatch.task_name == "pricing.update_product_prices"
    assert captured["kwargs"] == {
        "product_id": 1,
        "logging": True,
        "audit_actor_id": 5,
        "audit_ip": "127.0.0.1",
    }


def test_queue_all_refresh_uses_update_all_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AsyncResult:
        def __init__(self) -> None:
            self.state = "PENDING"
            self.task_id = "bulk"
            self.eta = datetime.now(UTC) + timedelta(minutes=10)

    class _Task:
        name = "pricing.update_all_products"

        def delay(self, **kwargs: object) -> _AsyncResult:
            self.kwargs = kwargs
            return _AsyncResult()

    task = _Task()
    monkeypatch.setattr(
        "app.services.pricing_dispatcher.update_all_products_task",
        task,
    )

    dispatcher = PricingDispatcher()
    dispatch = dispatcher.queue_all_refresh(
        logging=False,
        owner_id=42,
        audit_actor_id=None,
        audit_ip=None,
    )

    assert dispatch.task_id == "bulk"
    assert dispatch.status == "PENDING"
    assert dispatch.task_name == "pricing.update_all_products"
    assert dispatch.eta is not None
    assert task.kwargs == {
        "logging": False,
        "owner_id": 42,
        "audit_actor_id": None,
        "audit_ip": None,
    }


def test_result_from_async_handles_callable_eta_failure() -> None:
    class _AsyncResult:
        def __init__(self) -> None:
            self.task_id = "task"
            self.state = None

        def eta(self) -> datetime:
            raise TypeError("not callable without args")

    dispatch = PricingDispatcher._result_from_async(_AsyncResult(), "unit-test")
    assert dispatch.task_id == "task"
    assert dispatch.task_name == "unit-test"
    assert dispatch.status == "queued"
    assert dispatch.eta is None


def test_result_from_async_uses_str_task_id_when_missing_id() -> None:
    class _AsyncResult:
        def __init__(self) -> None:
            self.task_id = 123
            self.status = "STARTED"
            self.eta = None

    dispatch = PricingDispatcher._result_from_async(_AsyncResult(), "worker")
    assert dispatch.task_id == "123"
    assert dispatch.status == "STARTED"


def test_pricing_dispatcher_factory_override() -> None:
    class _Stub(PricingDispatcher):
        pass

    try:
        set_pricing_dispatcher_factory(_Stub)
        instance = get_pricing_dispatcher()
        assert isinstance(instance, _Stub)
    finally:
        set_pricing_dispatcher_factory(None)

    assert isinstance(get_pricing_dispatcher(), PricingDispatcher)
