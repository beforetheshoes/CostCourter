from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as models
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.services.audit import record_audit_log
from app.services.auth import issue_access_token
from app.services.price_fetcher import (
    PriceFetcherService,
    PriceFetchResult,
    PriceFetchSummary,
    set_price_fetcher_service_factory,
)
from app.services.pricing_dispatcher import (
    PricingDispatcher,
    PricingJobDispatch,
    set_pricing_dispatcher_factory,
)


@dataclass
class _StubService:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def update_product_prices(
        self,
        session: Session,
        product_id: int,
        *,
        logging: bool = False,
        owner_id: int | None = None,
        audit_actor_id: int | None = None,
        audit_ip: str | None = None,
    ) -> PriceFetchSummary:
        summary = PriceFetchSummary(
            total_urls=1,
            successful_urls=1,
            failed_urls=0,
            results=[
                PriceFetchResult(
                    product_url_id=101,
                    success=True,
                    price=12.34,
                    currency="USD",
                )
            ],
        )
        self.calls.append(
            {
                "mode": "product",
                "product_id": product_id,
                "logging": logging,
                "owner_id": owner_id,
                "actor_id": audit_actor_id,
                "ip": audit_ip,
            }
        )
        if audit_actor_id is not None:
            context_payload = summary.to_dict()
            if owner_id is not None:
                context_payload["owner_id"] = owner_id
            record_audit_log(
                session,
                action="pricing.refresh_product",
                actor_id=audit_actor_id,
                entity_type="product",
                entity_id=str(product_id),
                ip_address=audit_ip,
                context=context_payload,
            )
        return summary

    def update_all_products(
        self,
        session: Session,
        *,
        logging: bool = False,
        owner_id: int | None = None,
        audit_actor_id: int | None = None,
        audit_ip: str | None = None,
    ) -> PriceFetchSummary:
        summary = PriceFetchSummary(
            total_urls=2,
            successful_urls=1,
            failed_urls=1,
            results=[
                PriceFetchResult(
                    product_url_id=201,
                    success=False,
                    price=None,
                    currency=None,
                    reason="http_error",
                )
            ],
        )
        self.calls.append(
            {
                "mode": "all",
                "logging": logging,
                "owner_id": owner_id,
                "actor_id": audit_actor_id,
                "ip": audit_ip,
            }
        )
        if audit_actor_id is not None:
            context_payload = summary.to_dict()
            if owner_id is not None:
                context_payload["owner_id"] = owner_id
            record_audit_log(
                session,
                action="pricing.refresh_all",
                actor_id=audit_actor_id,
                entity_type="pricing",
                entity_id="all",
                ip_address=audit_ip,
                context=context_payload,
            )
        return summary


@dataclass
class _StubDispatcher:
    product_calls: list[dict[str, Any]] = field(default_factory=list)
    all_calls: list[dict[str, Any]] = field(default_factory=list)
    product_result: PricingJobDispatch = field(
        default_factory=lambda: PricingJobDispatch(
            task_id="product-123",
            task_name="pricing.update_product_prices",
        )
    )
    all_result: PricingJobDispatch = field(
        default_factory=lambda: PricingJobDispatch(
            task_id="all-456",
            task_name="pricing.update_all_products",
        )
    )

    def queue_product_refresh(
        self,
        *,
        product_id: int,
        logging: bool,
        audit_actor_id: int | None,
        audit_ip: str | None,
    ) -> PricingJobDispatch:
        self.product_calls.append(
            {
                "product_id": product_id,
                "logging": logging,
                "audit_actor_id": audit_actor_id,
                "audit_ip": audit_ip,
            }
        )
        return self.product_result

    def queue_all_refresh(
        self,
        *,
        logging: bool,
        owner_id: int | None,
        audit_actor_id: int | None,
        audit_ip: str | None,
    ) -> PricingJobDispatch:
        self.all_calls.append(
            {
                "logging": logging,
                "owner_id": owner_id,
                "audit_actor_id": audit_actor_id,
                "audit_ip": audit_ip,
            }
        )
        return self.all_result


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(name="client")
def client_fixture(engine: Engine) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            with Session(engine) as session:
                default_user = models.User(
                    email="pricing-client@example.com",
                    is_superuser=True,
                )
                session.add(default_user)
                session.commit()
                session.refresh(default_user)
                assert default_user.id is not None
                token = issue_access_token(settings, user_id=default_user.id)
            client.headers.update({"Authorization": f"Bearer {token}"})
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(name="stub_service")
def stub_service_fixture() -> Iterator[_StubService]:
    stub = _StubService()

    def factory() -> PriceFetcherService:
        return cast(PriceFetcherService, stub)

    set_price_fetcher_service_factory(factory)
    try:
        yield stub
    finally:
        set_price_fetcher_service_factory(None)


@pytest.fixture(name="stub_dispatcher")
def stub_dispatcher_fixture() -> Iterator[_StubDispatcher]:
    dispatcher = _StubDispatcher()

    def factory() -> PricingDispatcher:
        return cast(PricingDispatcher, dispatcher)

    set_pricing_dispatcher_factory(factory)
    try:
        yield dispatcher
    finally:
        set_pricing_dispatcher_factory(None)


def _seed_product(session: Session) -> models.Product:
    user = models.User(email=f"pricing-{uuid4().hex}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    store = models.Store(
        user_id=user.id,
        name="Demo Store",
        slug=f"demo-store-{uuid4().hex[:6]}",
    )
    product = models.Product(
        user_id=user.id,
        name="Demo Product",
        slug=f"demo-product-{uuid4().hex[:6]}",
    )
    session.add(store)
    session.add(product)
    session.commit()
    session.refresh(product)

    product_url = models.ProductURL(
        product_id=product.id,
        store_id=store.id,
        url="https://example.com/demo",
        active=True,
    )
    session.add(product_url)
    session.commit()
    return product


def test_fetch_product_prices_endpoint(
    client: TestClient, engine: Engine, stub_service: _StubService
) -> None:
    with Session(engine) as session:
        product = _seed_product(session)
        assert product.id is not None
        product_id = product.id

    response = client.post(f"/api/pricing/products/{product_id}/fetch?logging=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "total_urls": 1,
        "successful_urls": 1,
        "failed_urls": 0,
        "results": [
            {
                "product_url_id": 101,
                "success": True,
                "price": 12.34,
                "currency": "USD",
                "reason": None,
            }
        ],
    }
    assert len(stub_service.calls) == 1
    call = stub_service.calls[0]
    assert call["mode"] == "product"
    assert call["product_id"] == product_id
    assert call["logging"] is True
    actor_id = call["actor_id"]
    ip_address = call["ip"]
    assert isinstance(actor_id, int)
    assert ip_address == "testclient"

    with Session(engine) as session:
        audit_entries = session.exec(select(models.AuditLog)).all()
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "pricing.refresh_product"
    assert audit.actor_id == actor_id
    assert audit.context is not None
    assert audit.context["total_urls"] == 1


def test_fetch_all_product_prices_endpoint(
    client: TestClient, engine: Engine, stub_service: _StubService
) -> None:
    response = client.post("/api/pricing/products/fetch-all")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "total_urls": 2,
        "successful_urls": 1,
        "failed_urls": 1,
        "results": [
            {
                "product_url_id": 201,
                "success": False,
                "price": None,
                "currency": None,
                "reason": "http_error",
            }
        ],
    }
    assert len(stub_service.calls) == 1
    call = stub_service.calls[0]
    assert call["mode"] == "all"
    assert call["logging"] is False
    assert call["owner_id"] is None
    actor_id = call["actor_id"]
    ip_address = call["ip"]
    assert isinstance(actor_id, int)
    assert ip_address == "testclient"

    with Session(engine) as session:
        audit_entries = session.exec(select(models.AuditLog)).all()
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "pricing.refresh_all"
    assert audit.actor_id == actor_id
    assert audit.context is not None
    assert audit.context["total_urls"] == 2


def test_fetch_all_product_prices_endpoint_scopes_to_owner(
    client: TestClient,
    engine: Engine,
    stub_service: _StubService,
) -> None:
    with Session(engine) as session:
        owner = models.User(email="scoped-admin@example.com")
        session.add(owner)
        session.commit()
        session.refresh(owner)

    response = client.post(
        f"/api/pricing/products/fetch-all?owner_id={owner.id}&logging=true"
    )

    assert response.status_code == 200
    assert len(stub_service.calls) == 1
    call = stub_service.calls[0]
    assert call["mode"] == "all"
    assert call["owner_id"] == owner.id
    assert call["logging"] is True

    with Session(engine) as session:
        audit_entries = session.exec(select(models.AuditLog)).all()
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.action == "pricing.refresh_all"
    assert audit.context is not None
    assert audit.context.get("total_urls") == 2
    assert audit.context.get("owner_id") == owner.id


def test_fetch_product_prices_endpoint_enqueues_task_when_requested(
    client: TestClient,
    engine: Engine,
    stub_service: _StubService,
    stub_dispatcher: _StubDispatcher,
) -> None:
    with Session(engine) as session:
        product = _seed_product(session)
        assert product.id is not None
        product_id = product.id

    response = client.post(
        f"/api/pricing/products/{product_id}/fetch?enqueue=true&logging=false"
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "task_id": "product-123",
        "task_name": "pricing.update_product_prices",
        "status": "queued",
    }
    assert not stub_service.calls
    assert len(stub_dispatcher.product_calls) == 1
    dispatch_call = stub_dispatcher.product_calls[0]
    assert dispatch_call["product_id"] == product_id
    assert dispatch_call["logging"] is False
    assert isinstance(dispatch_call["audit_actor_id"], int)
    assert dispatch_call["audit_ip"] == "testclient"

    with Session(engine) as session:
        admin_user = session.exec(
            select(models.User).where(models.User.email == "pricing-client@example.com")
        ).first()
    assert admin_user is not None and admin_user.id == dispatch_call["audit_actor_id"]


def test_fetch_all_product_prices_endpoint_enqueues_task_when_requested(
    client: TestClient,
    stub_service: _StubService,
    stub_dispatcher: _StubDispatcher,
) -> None:
    response = client.post("/api/pricing/products/fetch-all?enqueue=true")

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "task_id": "all-456",
        "task_name": "pricing.update_all_products",
        "status": "queued",
    }
    assert not stub_service.calls
    assert len(stub_dispatcher.all_calls) == 1
    dispatch_call = stub_dispatcher.all_calls[0]
    assert dispatch_call["logging"] is False
    assert dispatch_call["owner_id"] is None
    assert isinstance(dispatch_call["audit_actor_id"], int)
    assert dispatch_call["audit_ip"] == "testclient"


def test_fetch_all_product_prices_endpoint_enqueues_task_with_owner(
    client: TestClient,
    engine: Engine,
    stub_service: _StubService,
    stub_dispatcher: _StubDispatcher,
) -> None:
    with Session(engine) as session:
        owner = models.User(email="owner-enqueue@example.com")
        session.add(owner)
        session.commit()
        session.refresh(owner)

    response = client.post(
        f"/api/pricing/products/fetch-all?enqueue=true&owner_id={owner.id}"
    )

    assert response.status_code == 202
    assert not stub_service.calls
    assert len(stub_dispatcher.all_calls) == 1
    dispatch_call = stub_dispatcher.all_calls[0]
    assert dispatch_call["owner_id"] == owner.id


def test_fetch_all_product_prices_endpoint_owner_not_found(
    client: TestClient,
    stub_service: _StubService,
) -> None:
    response = client.post("/api/pricing/products/fetch-all?owner_id=9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"
    assert not stub_service.calls


def test_fetch_product_prices_endpoint_requires_admin(
    client: TestClient,
) -> None:
    token = client.headers.pop("Authorization", None)
    try:
        response = client.post("/api/pricing/products/1/fetch")
    finally:
        if token is not None:
            client.headers["Authorization"] = token

    assert response.status_code in {401, 403}
    payload = response.json()
    assert "not authenticated" in payload["detail"].lower()


def test_fetch_all_product_prices_endpoint_requires_admin(
    client: TestClient,
) -> None:
    token = client.headers.pop("Authorization", None)
    try:
        response = client.post("/api/pricing/products/fetch-all")
    finally:
        if token is not None:
            client.headers["Authorization"] = token

    assert response.status_code in {401, 403}
    payload = response.json()
    assert "not authenticated" in payload["detail"].lower()
