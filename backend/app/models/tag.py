from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin
from app.models.product_tag_link import ProductTagLink

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User


class Tag(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_tags_user_slug"),
        UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    slug: str = Field(nullable=False, max_length=255)

    products: list["Product"] = Relationship(
        back_populates="tags",
        link_model=ProductTagLink,
    )
    owner: "User" = Relationship(back_populates="tags")


def _ensure_relationship_dependencies() -> None:
    import app.models.product as _product
    import app.models.user as _user

    _ = (_product, _user)


_ensure_relationship_dependencies()
