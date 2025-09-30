from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import AppSetting, Role


@dataclass(frozen=True, slots=True)
class ReferenceRole:
    slug: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ReferenceSetting:
    key: str
    value: str
    description: str


REFERENCE_ROLES: tuple[ReferenceRole, ...] = (
    ReferenceRole(
        slug="admin",
        name="Administrator",
        description="Full system access",
    ),
    ReferenceRole(
        slug="operator",
        name="Operator",
        description="May manage catalog entries and pricing",
    ),
)

REFERENCE_APP_SETTINGS: tuple[ReferenceSetting, ...] = (
    ReferenceSetting(
        key="feature.vue_admin_enabled",
        value="false",
        description="Toggle new Vue admin UI",
    ),
    ReferenceSetting(
        key="pricing.default_currency",
        value="USD",
        description="Fallback currency for price importers",
    ),
)


def _upsert_roles(session: Session, roles: Iterable[ReferenceRole]) -> None:
    for role in roles:
        existing = session.exec(select(Role).where(Role.slug == role.slug)).first()
        if existing is None:
            session.add(
                Role(
                    slug=role.slug,
                    name=role.name,
                    description=role.description,
                )
            )
        else:
            existing.name = role.name
            existing.description = role.description
            session.add(existing)


def _upsert_settings(session: Session, settings: Iterable[ReferenceSetting]) -> None:
    for setting in settings:
        existing = session.exec(
            select(AppSetting).where(AppSetting.key == setting.key)
        ).first()
        if existing is None:
            session.add(
                AppSetting(
                    key=setting.key,
                    value=setting.value,
                    description=setting.description,
                )
            )
        else:
            existing.value = setting.value
            existing.description = setting.description
            session.add(existing)


def install_reference_data(session: Session) -> None:
    """Seed core reference data shared by dev environments and automated tests."""

    _upsert_roles(session, REFERENCE_ROLES)
    _upsert_settings(session, REFERENCE_APP_SETTINGS)
    session.commit()
