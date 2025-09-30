from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column, Enum, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin
from app.models.product_tag_link import ProductTagLink

if TYPE_CHECKING:
    from app.models.price_history import PriceHistory
    from app.models.product_url import ProductURL
    from app.models.tag import Tag
    from app.models.user import User


class ProductStatus(StrEnum):
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Product(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_products_user_slug"),
        UniqueConstraint("user_id", "name", name="uq_products_user_name"),
    )

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    slug: str = Field(nullable=False, max_length=255, index=True)
    description: str | None = Field(default=None)
    is_active: bool = Field(default=True, nullable=False)
    status: ProductStatus = Field(
        default=ProductStatus.PUBLISHED,
        sa_column=Column(
            Enum(
                ProductStatus,
                native_enum=False,
                length=20,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                validate_strings=True,
            ),
            nullable=False,
        ),
    )
    favourite: bool = Field(default=True, nullable=False)
    only_official: bool = Field(default=False, nullable=False)
    notify_price: float | None = Field(default=None)
    notify_percent: float | None = Field(default=None)
    current_price: float | None = Field(default=None)
    price_cache: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    ignored_urls: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    image_url: str | None = Field(default=None, max_length=1024)

    urls: list["ProductURL"] = Relationship(back_populates="product")
    tags: list["Tag"] = Relationship(
        back_populates="products",
        link_model=ProductTagLink,
    )
    price_history: list["PriceHistory"] = Relationship(back_populates="product")
    owner: "User" = Relationship(back_populates="products")


def _ensure_relationship_dependencies() -> None:
    import app.models.price_history as _price_history
    import app.models.product_url as _product_url
    import app.models.tag as _tag
    import app.models.user as _user

    _ = (_price_history, _product_url, _tag, _user)


_ensure_relationship_dependencies()
