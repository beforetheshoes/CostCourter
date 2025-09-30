from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.product_url import ProductURL
    from app.models.user import User


class Store(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_stores_user_slug"),)

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(index=True, nullable=False, max_length=255)
    slug: str = Field(index=True, nullable=False, max_length=255)
    website_url: str | None = Field(default=None, max_length=500)
    active: bool = Field(default=True, nullable=False)
    locale: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=12)
    domains: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    scrape_strategy: dict[str, dict[str, Any]] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    settings: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    notes: str | None = Field(default=None, max_length=2000)

    product_urls: list["ProductURL"] = Relationship(back_populates="store")
    owner: "User" = Relationship(back_populates="stores")


def _ensure_relationship_dependencies() -> None:
    import app.models.product_url as _product_url
    import app.models.user as _user

    _ = (_product_url, _user)


_ensure_relationship_dependencies()
