from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import AppSetting
from app.services.schedule_tracker import fetch_last_run_map, record_schedule_run


def _make_engine() -> Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_record_schedule_run_persists_value() -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    try:
        reference = datetime(2025, 9, 27, 9, 0, tzinfo=UTC)
        with Session(engine) as session:
            record_schedule_run(
                session, "pricing.update_all_products", timestamp=reference
            )

        with Session(engine) as session:
            stored = session.get(
                AppSetting, "schedule.last_run.pricing.update_all_products"
            )
            assert stored is not None
            assert stored.value == "2025-09-27T09:00:00+00:00"
    finally:
        engine.dispose()


def test_fetch_last_run_map_handles_invalid_values() -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                AppSetting(
                    key="schedule.last_run.pricing.update_all_products",
                    value="2025-09-27T09:00:00+00:00",
                )
            )
            session.add(
                AppSetting(
                    key="schedule.last_run.invalid",
                    value="not-a-timestamp",
                )
            )
            session.commit()

        with Session(engine) as session:
            mapping = fetch_last_run_map(session)
            assert list(mapping.keys()) == ["pricing.update_all_products"]
            assert mapping["pricing.update_all_products"] == datetime(
                2025, 9, 27, 9, 0, tzinfo=UTC
            )
    finally:
        engine.dispose()


def test_record_schedule_run_updates_existing() -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    try:
        initial = datetime(2025, 9, 27, 9, 0, tzinfo=UTC)
        updated = initial + timedelta(hours=6)
        with Session(engine) as session:
            record_schedule_run(
                session, "pricing.update_all_products", timestamp=initial
            )
        with Session(engine) as session:
            record_schedule_run(
                session, "pricing.update_all_products", timestamp=updated
            )
        with Session(engine) as session:
            mapping = fetch_last_run_map(session)
            assert mapping["pricing.update_all_products"] == updated
    finally:
        engine.dispose()
