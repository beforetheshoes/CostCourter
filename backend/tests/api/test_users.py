from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as models
from app.core.database import get_session
from app.main import app


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
            yield client
    finally:
        app.dependency_overrides.clear()


def test_create_user_registers_identity(client: TestClient, engine: Engine) -> None:
    payload = {
        "email": "alice@example.com",
        "full_name": "Alice Example",
        "provider": "oidc",
        "provider_subject": "oidc|123",
    }

    response = client.post("/api/users", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]
    assert data["full_name"] == payload["full_name"]
    assert data["identities"] == [
        {
            "provider": payload["provider"],
            "provider_subject": payload["provider_subject"],
        }
    ]

    with Session(engine) as session:
        user = session.exec(select(models.User)).one()
        assert user.email == payload["email"]
        identity = session.exec(select(models.UserIdentity)).one()
        assert identity.provider == payload["provider"]
        assert identity.provider_subject == payload["provider_subject"]
        assert identity.user_id == user.id


def test_create_user_rejects_duplicate_identity(client: TestClient) -> None:
    payload = {
        "email": "alice@example.com",
        "full_name": "Alice Example",
        "provider": "oidc",
        "provider_subject": "oidc|123",
    }

    first = client.post("/api/users", json=payload)
    assert first.status_code == 201

    duplicate = client.post("/api/users", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Identity already registered"


def test_list_users_includes_identities(client: TestClient) -> None:
    client.post(
        "/api/users",
        json={
            "email": "user0@example.com",
            "full_name": "User 0",
            "provider": "oidc",
            "provider_subject": "oidc|0",
        },
    )
    client.post(
        "/api/users",
        json={
            "email": "user1@example.com",
            "full_name": "User 1",
            "provider": "passkey",
            "provider_subject": "webauthn-key-1",
        },
    )

    response = client.get("/api/users")

    assert response.status_code == 200
    data = response.json()
    by_email = {entry["email"]: entry for entry in data}
    assert set(by_email) == {"user0@example.com", "user1@example.com"}
    assert by_email["user0@example.com"]["identities"] == [
        {"provider": "oidc", "provider_subject": "oidc|0"}
    ]
    assert by_email["user1@example.com"]["identities"] == [
        {"provider": "passkey", "provider_subject": "webauthn-key-1"}
    ]


def test_list_users_supports_filters(client: TestClient, engine: Engine) -> None:
    client.post(
        "/api/users",
        json={
            "email": "alpha@example.com",
            "full_name": "Alpha",
            "provider": "oidc",
            "provider_subject": "oidc|alpha",
        },
    )
    client.post(
        "/api/users",
        json={
            "email": "beta@example.com",
            "full_name": "Beta",
            "provider": "oidc",
            "provider_subject": "oidc|beta",
        },
    )

    with Session(engine) as session:
        role = models.Role(slug="admin", name="Administrator")
        session.add(role)
        session.flush()

        beta_user = session.exec(
            select(models.User).where(models.User.email == "beta@example.com")
        ).one()
        assignment = models.UserRoleAssignment(
            user_id=beta_user.id,
            role_id=role.id,
        )
        session.add(assignment)
        session.commit()

    filtered = client.get("/api/users", params={"search": "alpha"})
    assert filtered.status_code == 200
    assert [user["email"] for user in filtered.json()] == ["alpha@example.com"]

    role_filter = client.get("/api/users", params={"role": "ADMIN"})
    assert role_filter.status_code == 200
    assert [user["email"] for user in role_filter.json()] == ["beta@example.com"]

    paginated = client.get("/api/users", params={"limit": 1, "offset": 1})
    assert paginated.status_code == 200
    assert len(paginated.json()) == 1
