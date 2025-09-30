from __future__ import annotations

from decimal import Decimal

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import AuditLog
from app.services.audit import record_audit_log


def test_record_audit_log_normalizes_context() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            entry = record_audit_log(
                session,
                action="demo.event",
                actor_id=42,
                entity_type="product",
                entity_id="123",
                ip_address="127.0.0.1",
                context={
                    "price": Decimal("12.34"),
                    "ids": {3, 1},
                    "details": {
                        "flag": True,
                        "data": {"raw": Decimal("0.50")},
                    },
                },
            )

        assert entry.actor_id == 42
        assert entry.action == "demo.event"
        assert entry.entity_type == "product"
        assert entry.entity_id == "123"
        assert entry.ip_address == "127.0.0.1"
        assert entry.context == {
            "price": 12.34,
            "ids": [1, 3],
            "details": {"flag": True, "data": {"raw": 0.5}},
        }

        with Session(engine) as verify_session:
            stored = verify_session.get(AuditLog, entry.id)
            assert stored is not None
            assert stored.context == entry.context
    finally:
        engine.dispose()
