from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as models
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.services.auth import issue_access_token


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
                default_user = models.User(email="test.user@example.com")
                session.add(default_user)
                session.commit()
                session.refresh(default_user)
            assert default_user.id is not None
            token = issue_access_token(settings, user_id=default_user.id)
            client.headers.update({"Authorization": f"Bearer {token}"})
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def create_user(engine: Engine) -> Callable[..., models.User]:
    def factory(
        *,
        email: str,
        full_name: str | None = None,
        is_superuser: bool = False,
    ) -> models.User:
        with Session(engine) as session:
            user = models.User(
                email=email,
                full_name=full_name,
                is_superuser=is_superuser,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user

    return factory


@pytest.fixture
def ensure_role(engine: Engine) -> Callable[[str], models.Role]:
    def factory(slug: str, *, name: str | None = None) -> models.Role:
        with Session(engine) as session:
            statement = select(models.Role).where(models.Role.slug == slug)
            role = session.exec(statement).first()
            if role is None:
                role = models.Role(
                    slug=slug,
                    name=name or slug.replace("-", " ").title(),
                )
                session.add(role)
                session.commit()
                session.refresh(role)
            session.expunge(role)
            return role

    return factory


@pytest.fixture
def assign_role(
    engine: Engine, ensure_role: Callable[[str], models.Role]
) -> Callable[[models.User, str], None]:
    def factory(user: models.User, slug: str = "admin") -> None:
        if user.id is None:
            raise ValueError("User must be persisted before assigning roles")

        ensure_role(slug)

        with Session(engine) as session:
            role = session.exec(
                select(models.Role).where(models.Role.slug == slug)
            ).one()
            exists = session.exec(
                select(models.UserRoleAssignment)
                .where(models.UserRoleAssignment.user_id == user.id)
                .where(models.UserRoleAssignment.role_id == role.id)
            ).first()
            if exists:
                return
            assignment = models.UserRoleAssignment(
                user_id=user.id,
                role_id=role.id,
            )
            session.add(assignment)
            session.commit()

    return factory


@pytest.fixture
def admin_user(create_user: Callable[..., models.User]) -> models.User:
    return create_user(email="admin@example.com", is_superuser=True)


@pytest.fixture
def standard_user(create_user: Callable[..., models.User]) -> models.User:
    return create_user(email="user@example.com")


@pytest.fixture
def make_auth_headers() -> Callable[[models.User], dict[str, str]]:
    def factory(user: models.User, scope: str | None = None) -> dict[str, str]:
        if user.id is None:
            raise ValueError("User must be persisted before issuing a token")
        token = issue_access_token(settings, user_id=user.id, scope=scope)
        return {"Authorization": f"Bearer {token}"}

    return factory


@pytest.fixture
def admin_auth_headers(
    admin_user: models.User, make_auth_headers: Callable[[models.User], dict[str, str]]
) -> dict[str, str]:
    return make_auth_headers(admin_user)


@pytest.fixture
def user_auth_headers(
    standard_user: models.User,
    make_auth_headers: Callable[[models.User], dict[str, str]],
) -> dict[str, str]:
    return make_auth_headers(standard_user)


@pytest.fixture
def authed_client(client: TestClient, user_auth_headers: dict[str, str]) -> TestClient:
    client.headers.update(user_auth_headers)
    return client
