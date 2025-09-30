from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

import app.models as models
from app.core.config import settings


def test_pricing_schedule_read_returns_default_without_path(client: TestClient) -> None:
    previous_path = settings.celery_beat_schedule_path
    settings.celery_beat_schedule_path = None
    try:
        response = client.get("/api/pricing/schedule")
        assert response.status_code == 200
        payload = response.json()
        assert payload["entries"]
        entry = payload["entries"][0]
        assert entry["name"] == "pricing.update_all_products"
        assert entry["next_run_at"] is not None
    finally:
        settings.celery_beat_schedule_path = previous_path


def test_pricing_schedule_read_resolves_relative_path(client: TestClient) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    app_root = backend_root / "app"
    with TemporaryDirectory(dir=app_root) as tmpdir:
        schedule_dir = Path(tmpdir)
        schedule_path = schedule_dir / "schedule.json"
        schedule_path.write_text("{}", encoding="utf-8")
        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = f"{schedule_dir.name}/{schedule_path.name}"

        try:
            response = client.get("/api/pricing/schedule")
            assert response.status_code == 200
            payload = response.json()
            assert payload["entries"]
            assert payload["entries"][0]["name"] == "pricing.update_all_products"
        finally:
            settings.celery_beat_schedule_path = previous_path


def test_read_and_update_schedule_requires_admin(
    client: TestClient,
    engine: Engine,
    admin_user: models.User,
    admin_auth_headers: dict[str, str],
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
) -> None:
    with TemporaryDirectory() as tmpdir:
        schedule_path = Path(tmpdir) / "schedule.json"
        schedule_path.write_text(
            json.dumps(
                {
                    "pricing.update_all_products": {
                        "task": "pricing.update_all_products",
                        "schedule": 3600,
                        "args": [],
                        "kwargs": {"logging": False},
                    }
                }
            ),
            encoding="utf-8",
        )

        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = str(schedule_path)

        try:
            user = create_user(email="user@example.com", is_superuser=False)
            user_headers = make_auth_headers(user)

            read = client.get("/api/pricing/schedule")
            assert read.status_code == 200
            assert read.json()["entries"][0]["task"] == "pricing.update_all_products"

            denied = client.put(
                "/api/pricing/schedule",
                json={
                    "entries": [
                        {
                            "name": "pricing.update_all_products",
                            "task": "pricing.update_all_products",
                            "schedule": 7200,
                        }
                    ]
                },
                headers=user_headers,
            )
            assert denied.status_code == 403

            updated = client.put(
                "/api/pricing/schedule",
                json={
                    "entries": [
                        {
                            "name": "pricing.update_all_products",
                            "task": "pricing.update_all_products",
                            "schedule": 7200,
                            "kwargs": {"logging": True},
                        }
                    ]
                },
                headers=admin_auth_headers,
            )
            assert updated.status_code == 200
            payload = updated.json()
            assert payload["entries"][0]["schedule"] == 7200
            assert payload["entries"][0]["kwargs"]["logging"] is True
            assert payload["entries"][0]["last_run_at"] is None

            saved = json.loads(schedule_path.read_text(encoding="utf-8"))
            assert saved["pricing.update_all_products"]["schedule"] == 7200
            assert saved["pricing.update_all_products"]["kwargs"]["logging"] is True
        finally:
            settings.celery_beat_schedule_path = previous_path


def test_pricing_schedule_update_allows_admin_role(
    client: TestClient,
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
    assign_role: Callable[[models.User, str], None],
) -> None:
    with TemporaryDirectory() as tmpdir:
        schedule_path = Path(tmpdir) / "schedule.json"
        schedule_path.write_text("{}", encoding="utf-8")

        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = str(schedule_path)

        try:
            user = create_user(email="role.admin@example.com", is_superuser=False)
            assign_role(user, "admin")
            headers = make_auth_headers(user)

            response = client.put(
                "/api/pricing/schedule",
                json={
                    "entries": [
                        {
                            "name": "pricing.update_all_products",
                            "task": "pricing.update_all_products",
                            "schedule": 3600,
                            "enabled": True,
                        }
                    ]
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["entries"][0]["name"] == "pricing.update_all_products"
            assert payload["entries"][0]["schedule"] == 3600
        finally:
            settings.celery_beat_schedule_path = previous_path


def test_pricing_schedule_update_requires_configured_path(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    previous_path = settings.celery_beat_schedule_path
    settings.celery_beat_schedule_path = None
    try:
        response = client.put(
            "/api/pricing/schedule",
            json={"entries": []},
            headers=admin_auth_headers,
        )
        assert response.status_code == 500
    finally:
        settings.celery_beat_schedule_path = previous_path


def test_pricing_schedule_includes_last_run_metadata(
    client: TestClient,
    engine: Engine,
) -> None:
    with TemporaryDirectory() as tmpdir:
        schedule_path = Path(tmpdir) / "schedule.json"
        schedule_path.write_text(
            json.dumps(
                {
                    "pricing.update_all_products": {
                        "task": "pricing.update_all_products",
                        "schedule": 3600,
                    }
                }
            ),
            encoding="utf-8",
        )

        previous_path = settings.celery_beat_schedule_path
        settings.celery_beat_schedule_path = str(schedule_path)

        try:
            with Session(engine) as session:
                setting = models.AppSetting(
                    key="schedule.last_run.pricing.update_all_products",
                    value="2025-09-27T09:00:00+00:00",
                )
                session.add(setting)
                session.commit()

            response = client.get("/api/pricing/schedule")
            assert response.status_code == 200
            entry = response.json()["entries"][0]
            recorded = entry["last_run_at"]
            assert recorded is not None
            parsed = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            assert parsed == datetime(2025, 9, 27, 9, 0, tzinfo=UTC)
            assert entry["next_run_at"] is not None
        finally:
            settings.celery_beat_schedule_path = previous_path
