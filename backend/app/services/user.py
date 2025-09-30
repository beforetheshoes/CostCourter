from __future__ import annotations

from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.sql.elements import BinaryExpression
from sqlmodel import Session, select

from app.models import Role, User, UserIdentity, UserRoleAssignment
from app.models.base import utcnow
from app.schemas import CurrentUserRead, UserCreate, UserIdentityRead, UserRead

_ROLE_CACHE_ATTR = "_cached_role_slugs"


def _build_user_read(session: Session, user: User) -> UserRead:
    identities = session.exec(
        select(UserIdentity).where(UserIdentity.user_id == user.id)
    ).all()
    return UserRead.model_validate(
        {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "identities": [
                UserIdentityRead.model_validate(identity).model_dump()
                for identity in identities
            ],
        }
    )


def _load_role_slugs(session: Session, user: User) -> list[str]:
    cached = cast(list[str] | None, getattr(user, _ROLE_CACHE_ATTR, None))
    if cached is not None:
        return cached

    if user.id is None:
        slugs: list[str] = []
    else:
        join_on = cast(BinaryExpression[bool], UserRoleAssignment.role_id == Role.id)
        statement = (
            select(Role.slug)
            .join(UserRoleAssignment, join_on)
            .where(UserRoleAssignment.user_id == user.id)
            .order_by(Role.slug)
        )
        result = session.exec(statement)
        slugs = [str(value) for value in result]

    setattr(user, _ROLE_CACHE_ATTR, slugs)
    return slugs


def get_user_role_slugs(session: Session, user: User) -> list[str]:
    """Return a copy of the role slugs assigned to ``user``.

    Results are cached on the instance to avoid duplicate queries within a request.
    """

    return list(_load_role_slugs(session, user))


def user_has_role(session: Session, user: User, role_slug: str) -> bool:
    """Check whether ``user`` has a role matching ``role_slug`` (case-insensitive)."""

    normalized = role_slug.strip().lower()
    if not normalized or user.id is None:
        return False

    return any(slug.lower() == normalized for slug in _load_role_slugs(session, user))


def create_user(session: Session, payload: UserCreate) -> UserRead:
    identity = session.exec(
        select(UserIdentity)
        .where(UserIdentity.provider == payload.provider)
        .where(UserIdentity.provider_subject == payload.provider_subject)
    ).first()
    if identity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity already registered",
        )

    user = session.exec(select(User).where(User.email == payload.email)).first()
    if user is None:
        user = User(email=payload.email, full_name=payload.full_name)
        session.add(user)
        session.flush()

    new_identity = UserIdentity(
        user_id=user.id,
        provider=payload.provider,
        provider_subject=payload.provider_subject,
    )
    session.add(new_identity)
    session.commit()
    session.refresh(user)
    return _build_user_read(session, user)


def list_users(
    session: Session,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    role_slug: str | None = None,
) -> list[UserRead]:
    statement = select(User)
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(User.email).like(pattern)
            | func.lower(User.full_name).like(pattern)
        )
    if role_slug:
        user_join = cast(BinaryExpression[bool], UserRoleAssignment.user_id == User.id)
        role_join = cast(BinaryExpression[bool], Role.id == UserRoleAssignment.role_id)
        statement = (
            statement.join(UserRoleAssignment, user_join)
            .join(Role, role_join)
            .where(func.lower(Role.slug) == role_slug.lower())
        )
        statement = statement.distinct()

    statement = statement.order_by(User.email).offset(offset).limit(limit)
    users = session.exec(statement).all()
    return [_build_user_read(session, user) for user in users]


def ensure_user_with_identity(
    session: Session,
    *,
    email: str,
    full_name: str | None,
    provider: str,
    provider_subject: str,
) -> User:
    identity = session.exec(
        select(UserIdentity)
        .where(UserIdentity.provider == provider)
        .where(UserIdentity.provider_subject == provider_subject)
    ).first()
    if identity:
        user = session.get(User, identity.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Identity references missing user",
            )
        return user

    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, full_name=full_name)
        session.add(user)
        session.flush()
    elif full_name and not user.full_name:
        user.full_name = full_name

    new_identity = UserIdentity(
        user_id=user.id,
        provider=provider,
        provider_subject=provider_subject,
    )
    user.updated_at = utcnow()
    session.add(new_identity)
    session.commit()
    session.refresh(user)
    return user


def build_current_user_response(session: Session, user: User) -> CurrentUserRead:
    base = _build_user_read(session, user)
    roles = get_user_role_slugs(session, user)
    if user.is_superuser and "admin" not in {role.lower() for role in roles}:
        roles.append("admin")
    return CurrentUserRead.model_validate(
        {
            **base.model_dump(),
            "is_superuser": user.is_superuser,
            "roles": roles,
        }
    )
