from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm.exc import FlushError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import get_session
from app.models import User, ensure_core_model_mappings
from app.services.user import user_has_role

_bearer_scheme = HTTPBearer(auto_error=not settings.auth_bypass)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if settings.auth_bypass:
        ensure_core_model_mappings()

        statement = select(User).where(User.email == "dev@example.com")
        for _ in range(5):
            user = session.exec(statement).first()
            if user is not None:
                return user

            new_user = User(
                email="dev@example.com",
                full_name="Developer",
                is_superuser=True,
                is_active=True,
            )
            session.add(new_user)
            try:
                session.commit()
            except (IntegrityError, FlushError, InterfaceError, OperationalError):
                session.rollback()
                continue

            persisted = session.exec(statement).first()
            if persisted is not None:
                return persisted

        msg = "Failed to provision bypass user"
        raise RuntimeError(msg)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from exc

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


__all__ = [
    "get_current_user",
    "get_price_refresh_dispatcher",
    "get_scraper_client_factory",
    "HttpClientFactory",
    "PriceRefreshDispatcher",
    "require_admin",
    "require_roles",
]


HttpClientFactory = Callable[[], httpx.Client]


class PriceRefreshDispatcher(Protocol):
    """Dispatcher responsible for scheduling price refreshes asynchronously."""

    def enqueue(self, product_id: int) -> None:
        """Enqueue a product for asynchronous price refresh."""


class _CeleryPriceRefreshDispatcher:
    """Default dispatcher that hands work to the Celery pricing task."""

    def enqueue(self, product_id: int) -> None:
        from app.tasks.pricing import update_product_prices_task

        update_product_prices_task.delay(product_id=product_id, logging=False)


def get_price_refresh_dispatcher() -> PriceRefreshDispatcher:
    """Return dispatcher used by request handlers to queue price refresh jobs."""

    return _CeleryPriceRefreshDispatcher()


def get_scraper_client_factory() -> HttpClientFactory:
    """Provide an HTTP client factory used for scraper metadata fetches."""

    def _factory() -> httpx.Client:
        return httpx.Client()

    return _factory


def require_roles(*role_slugs: str) -> Callable[[User, Session], User]:
    """Factory returning a FastAPI dependency enforcing role membership.

    The dependency allows superusers through automatically while ensuring the
    authenticated user has at least one of the provided ``role_slugs``.
    """

    normalized = [slug.strip() for slug in role_slugs if slug.strip()]
    if not normalized:
        msg = "At least one role must be specified"
        raise ValueError(msg)

    def _require_roles(
        user: User = Depends(get_current_user),
        session: Session = Depends(get_session),
    ) -> User:
        if user.is_superuser:
            return user

        if any(user_has_role(session, user, slug) for slug in normalized):
            return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role membership",
        )

    return _require_roles


def require_admin(user: User = Depends(require_roles("admin"))) -> User:
    """Dependency enforcing admin access via role or superuser flag."""

    return user
